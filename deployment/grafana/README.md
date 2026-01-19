# Grafana Pipeline Dashboard Deployment

This directory contains Grafana dashboard and alert configurations for the Clerk pipeline monitoring system.

## Files

- `clerk-pipeline-dashboard.json` - Main dashboard with 12 panels across 3 rows
- `test-queries.sql` - SQL validation script (test before deploying)
- `alerts/stuck-sites-critical.json` - Alert for >10 stuck sites
- `alerts/health-degraded.json` - Alert for <85% health score
- `alerts/ocr-failures-high.json` - Alert for >20% OCR failure rate

## Prerequisites

1. **Grafana** - Version 9.0+ (tested on 10.x)
2. **PostgreSQL Data Source** - Connected to civic.db
3. **Loki Data Source** - Connected to log aggregation server
4. **LOKI_URL configured** - Workers sending logs to Loki (see `.env.example`)

## Pre-Deployment Testing

### Step 1: Validate SQL Queries

Test all dashboard queries against your database:

```bash
# On production server (or server with DATABASE_URL access)
psql $DATABASE_URL -f deployment/grafana/test-queries.sql
```

**Expected:** All queries execute without errors, return sample data.

**If queries fail:**
- Check DATABASE_URL is correct
- Verify sites table exists with atomic counter columns
- Check you have read permissions

### Step 2: Verify Loki Has Logs

Check Loki is receiving logs from workers:

```bash
# Test Loki query
curl -G -s "http://<loki-host>:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={job="clerk"}' \
  --data-urlencode 'start=1h' | jq '.data.result | length'
```

**Expected:** Returns number > 0

**If no logs:**
- Check LOKI_URL in .env
- Verify workers are running
- Check Loki logs for ingestion errors

## Deployment

### Option 1: Grafana UI (Recommended for First Install)

#### Deploy Dashboard

1. Open Grafana → Dashboards → Import
2. Upload `clerk-pipeline-dashboard.json`
3. Select data sources:
   - PostgreSQL → `civic-db` (or your PostgreSQL data source name)
   - Loki → `loki` (or your Loki data source name)
4. Click Import

**First-time setup:**
- Dashboard variables should auto-populate
- If subdomain dropdown is empty: No sites in last 24h (normal for new install)
- If panels show "No data": Check data source connections

#### Deploy Alert Rules

1. Open Grafana → Alerting → Alert rules → New alert rule
2. For each alert JSON file:
   - Click "Import" (top right)
   - Paste contents of alert JSON
   - Update data source UIDs if needed (see below)
   - Click Save

**Data Source UIDs:**

If your data source UIDs differ from `${DS_CIVIC_DB}`:

1. Find your data source UID:
   - Grafana → Configuration → Data sources → Click your PostgreSQL data source
   - UID is in the URL: `/datasources/edit/<UID>`

2. Replace in alert JSONs:
   ```bash
   # Example: Replace placeholder with actual UID
   sed -i 's/${DS_CIVIC_DB}/abc123xyz/g' deployment/grafana/alerts/*.json
   ```

#### Configure Notification Channels

Alerts need notification channels to send alerts:

1. Open Grafana → Alerting → Notification channels
2. Add channel for Slack:
   - Type: Slack
   - Webhook URL: `<your-slack-webhook>`
   - Default channel: `#alerts`
3. Add channel for PagerDuty (optional):
   - Type: PagerDuty
   - Integration Key: `<your-pagerduty-key>`

4. Edit each alert rule:
   - Open Alerting → Alert rules → Click alert
   - Scroll to "Notification channels"
   - Select Slack and/or PagerDuty
   - Save

### Option 2: Grafana API (Automated Deployment)

Deploy via API for reproducible deployments:

```bash
#!/bin/bash
# deploy-dashboard.sh

GRAFANA_URL="https://grafana.example.com"
GRAFANA_API_KEY="<your-api-key>"

# Import dashboard
curl -X POST "$GRAFANA_URL/api/dashboards/db" \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  -H "Content-Type: application/json" \
  -d @clerk-pipeline-dashboard.json

# Import alert rules (Grafana 9+)
for alert in alerts/*.json; do
  curl -X POST "$GRAFANA_URL/api/v1/provisioning/alert-rules" \
    -H "Authorization: Bearer $GRAFANA_API_KEY" \
    -H "Content-Type: application/json" \
    -d @"$alert"
done
```

### Option 3: Grafana Provisioning (GitOps)

For infrastructure-as-code deployments:

1. Copy files to Grafana provisioning directory:
   ```bash
   cp clerk-pipeline-dashboard.json /etc/grafana/provisioning/dashboards/
   cp alerts/*.json /etc/grafana/provisioning/alerting/
   ```

2. Create datasource provisioning (if not exists):
   ```yaml
   # /etc/grafana/provisioning/datasources/clerk.yaml
   apiVersion: 1
   datasources:
     - name: civic-db
       type: postgres
       url: <postgres-host>:5432
       database: clerk
       user: grafana_readonly
       secureJsonData:
         password: <password>
       jsonData:
         sslmode: require
         postgresVersion: 1400

     - name: loki
       type: loki
       url: http://<loki-host>:3100
       access: proxy
   ```

3. Restart Grafana:
   ```bash
   systemctl restart grafana-server
   ```

## Post-Deployment Verification

### Test Dashboard

1. Open dashboard: `https://grafana/d/clerk-pipeline`
2. Check Panel 1.1 (Stuck Sites):
   - Should show count (may be 0 if healthy)
   - Click to verify SQL query executes
3. Check Panel 1.2 (Health Score):
   - Should show percentage
   - Gauge should be colored (green/yellow/red)
4. Check Panel 3.2 (Log Search):
   - Should show recent logs
   - Try live tail mode

**If panels show "No data":**
- Check time range (default: last 24h)
- Verify sites exist in database with `updated_at` in range
- Check data source connections

### Test Variables

1. Click "Subdomain" dropdown:
   - Should show list of subdomains
   - Select one → panels should filter
2. Click "Stage" dropdown:
   - Should show: fetch, ocr, compilation, extraction, deploy, completed
   - Select one → panels should filter
3. Click "Run ID" dropdown:
   - Should show recent run_ids
   - Select one → Row 3 panels should filter to that run

**If variables are empty:**
- Subdomain: No sites processed in last 24h
- Run ID: No logs in Loki with that label

### Test Alerts

Trigger a test alert:

```bash
# Make a site appear stuck (set updated_at to 3 hours ago)
psql $DATABASE_URL -c "UPDATE sites SET updated_at = NOW() - INTERVAL '3 hours' WHERE subdomain = 'test-site' AND current_stage = 'ocr';"
```

Wait 15 minutes (alert "for" duration), then:

1. Check Grafana → Alerting → Alert rules
2. "Clerk: Stuck Sites Critical" should be firing
3. Check Slack #alerts channel for notification
4. Ack alert and reset test site:
   ```bash
   psql $DATABASE_URL -c "UPDATE sites SET updated_at = NOW() WHERE subdomain = 'test-site';"
   ```

## Troubleshooting

### Dashboard Shows "No data"

**Check data sources:**
```bash
# Test PostgreSQL connection
psql $DATABASE_URL -c "SELECT COUNT(*) FROM sites;"

# Test Loki connection
curl -s "http://<loki-host>:3100/ready"
```

**Check time range:**
- Dashboard default is "Last 24 hours"
- If no sites processed recently, extend to "Last 7 days"

**Check query syntax:**
- Open panel → Edit → Query tab
- Look for red error indicators
- Common issue: Data source UID mismatch

### Variables Not Populating

**Subdomain dropdown empty:**
- No sites in database with `updated_at` in last 24h
- Query: `SELECT DISTINCT subdomain FROM sites WHERE updated_at > NOW() - INTERVAL '24 hours';`

**Run ID dropdown empty:**
- No logs in Loki with `run_id` label
- Check Loki query: `{job="clerk"} | json | run_id != ""`

**Stage dropdown empty:**
- This is a custom variable (not query-based)
- If empty, dashboard JSON may not have imported correctly
- Re-import dashboard

### Alerts Not Firing

**Check alert state:**
1. Grafana → Alerting → Alert rules
2. Click alert name
3. Check "State" column:
   - Normal: Condition not met (good)
   - Pending: Condition met, waiting "for" duration
   - Firing: Alert active

**Manually test query:**
```bash
# Run alert query in psql
psql $DATABASE_URL -f test-queries.sql
# Look at "Alert 1: Stuck Sites" output
# If stuck_count > 10, alert should fire
```

**Check notification channels:**
- Grafana → Alerting → Notification channels
- Send test notification
- Check Slack/PagerDuty receives it

### Logs Panel Shows Old Logs

**Check Loki retention:**
- Default Loki retention: 30 days
- If logs older than retention, they're deleted

**Check worker logging:**
```bash
# Verify LOKI_URL in .env
grep LOKI_URL .env

# Check if workers are sending logs
curl -s "http://<loki-host>:3100/loki/api/v1/label" | jq .
# Should show "job" label with value "clerk"
```

## Customization

### Adjust Alert Thresholds

Edit alert JSON files before deploying:

```json
// In stuck-sites-critical.json
"evaluator": {
  "params": [10],  // Change threshold here (default: 10)
  "type": "gt"
}
```

### Add More Panels

1. Open dashboard in Grafana
2. Click "Add panel"
3. Configure query and visualization
4. Save dashboard
5. Export JSON: Dashboard settings → JSON Model → Copy to clipboard
6. Overwrite `clerk-pipeline-dashboard.json` with exported JSON

**Recommended additions:**
- Panel: "Sites by Scraper Type" (pie chart)
- Panel: "Processing Duration Distribution" (histogram)
- Panel: "Documents per Site" (stat panel)

### Adjust Refresh Intervals

In `clerk-pipeline-dashboard.json`:

```json
{
  "dashboard": {
    "refresh": "1m",  // Change to "30s", "5m", etc.
    ...
  }
}
```

Faster refresh = more database queries. Recommended:
- Development: 30s
- Production: 1-5m

## Maintenance

### Weekly Tasks

- Review alert frequency (too noisy? adjust thresholds)
- Check dashboard performance (slow panels? optimize queries)
- Update documentation with new panels

### Monthly Tasks

- Review Grafana analytics (which panels are used?)
- Remove unused panels
- Add panels for new questions

### As Needed

- Update dashboard when schema changes
- Tune alert "for" durations based on patterns
- Add derived fields for new Loki labels

## Support

**Dashboard not working?**
1. Check this README first
2. Review design doc: `docs/plans/2026-01-19-grafana-pipeline-dashboard-design.md`
3. Test queries: Run `test-queries.sql`
4. Check Grafana logs: `journalctl -u grafana-server -f`

**Questions about queries?**
- All queries documented in design doc
- SQL validation script has comments
- PostgreSQL slow query log: Check for optimization opportunities

## References

- Design: `docs/plans/2026-01-19-grafana-pipeline-dashboard-design.md`
- Migration Guide: `docs/plans/MIGRATION-pipeline-state-consolidation-UPDATED.md`
- Monitoring Guide: `docs/user-guide/monitoring.md`
