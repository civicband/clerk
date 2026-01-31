# Grafana Dashboard Quick Start (5 Minutes)

For when you just want to get it working.

## 1. Test Queries (1 min)

```bash
psql $DATABASE_URL -f deployment/grafana/test-queries.sql
```

✅ All queries return data → Continue
❌ Queries fail → Check DATABASE_URL and schema

## 2. Import Dashboard (2 min)

1. Grafana → Dashboards → Import
2. Upload `clerk-pipeline-dashboard.json`
3. Select data sources:
   - PostgreSQL: `civic-db`
   - Loki: `loki`
4. Click Import

## 3. Check It Works (1 min)

Open: `https://grafana/d/clerk-pipeline`

- Panel 1.1 shows stuck sites count
- Panel 1.2 shows health %
- Panel 3.2 shows logs

✅ All panels show data → Success!
❌ "No data" → Check time range, extend to "Last 7 days"

## 4. Import Alerts (1 min)

1. Grafana → Alerting → Alert rules → Import
2. Paste contents of each file in `alerts/`:
   - `stuck-sites-critical.json`
   - `health-degraded.json`
   - `ocr-failures-high.json`
3. Update notification channels (Slack, PagerDuty)

Done!

## Troubleshooting

**No data in panels:**
- Check time range (try "Last 7 days")
- Verify: `psql $DATABASE_URL -c "SELECT COUNT(*) FROM sites;"`

**Variables empty:**
- Normal if no sites processed recently
- Run a test site to populate

**Logs panel empty:**
- Check LOKI_URL in .env
- Verify workers are running

**Full docs:** See `README.md` in this directory
