# Grafana Pipeline Monitoring Dashboard Design

**Created:** 2026-01-19
**Status:** Approved - Ready for Implementation

## Overview

Design for a unified Grafana dashboard that provides operations visibility and deep debugging capabilities for the Clerk pipeline. Combines real-time metrics from PostgreSQL with rich log drilling via Loki.

## Goals

1. **At-a-glance health check** - Answer "is everything OK?" in <5 seconds
2. **Spot trends and bottlenecks** - See patterns over time (throughput, failure rates)
3. **Debug stuck sites** - Drill from alert → logs → root cause without leaving dashboard

## Non-Goals

- Real-time alerting for individual job failures (use Sentry for that)
- Historical analysis beyond 30 days (use data warehouse)
- Per-PDF performance metrics (too granular, use sampling)

---

## Architecture

### Data Sources

**1. PostgreSQL (civic.db)**
- **Purpose:** Fast queries for metrics panels
- **Tables:** `sites` table with atomic counters
- **Columns Used:**
  - `subdomain`, `current_stage`, `started_at`, `updated_at`
  - `ocr_total`, `ocr_completed`, `ocr_failed`
  - `compilation_total`, `compilation_completed`, `compilation_failed`
  - `extraction_total`, `extraction_completed`, `extraction_failed`
  - `deploy_total`, `deploy_completed`, `deploy_failed`

**2. Loki**
- **Purpose:** Log drilling for debugging
- **Labels:** `job="clerk"`
- **Structured Fields:** `subdomain`, `run_id`, `stage`, `job_id`, `parent_job_id`, `level`
- **Log Format:** JSON from `log_with_context()` function

### Integration Points

```
┌──────────────┐
│   Workers    │─── log_with_context() ───> Loki (logs)
└──────────────┘                              │
       │                                      │
       ├─── atomic counter updates ───> PostgreSQL (metrics)
       │                                      │
       │                                      │
┌──────────────────────────────────────────────┐
│            Grafana Dashboard                 │
│  ┌────────────────────────────────────┐     │
│  │ PostgreSQL Queries (Row 1-2)       │<────┤
│  └────────────────────────────────────┘     │
│  ┌────────────────────────────────────┐     │
│  │ Loki Queries (Row 3)               │<────┤
│  └────────────────────────────────────┘     │
└──────────────────────────────────────────────┘
       │
       └──> Alerts (Slack/PagerDuty)
```

---

## Dashboard Layout

### Single Unified Dashboard: "Clerk Pipeline"

**Layout Philosophy:** Top-down workflow
- **Top:** What's wrong? (health check)
- **Middle:** Trends (context)
- **Bottom:** Debugging (drill-down)

```
┌─────────────────────────────────────────────────────────────┐
│ Dashboard Variables: [Time▼] [Subdomain▼] [Stage▼] [Run▼] │
├─────────────────────────────────────────────────────────────┤
│ ROW 1: AT-A-GLANCE HEALTH                                   │
│ ┌───────────────┐ ┌───────────────┐ ┌───────────────────┐ │
│ │ Stuck Sites   │ │ Health Score  │ │ Stage             │ │
│ │     5         │ │    92%        │ │ Distribution      │ │
│ │  🟡 WARNING   │ │  🟡 DEGRADED  │ │   [Pie Chart]     │ │
│ └───────────────┘ └───────────────┘ └───────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│ ROW 2: TRENDS (LAST 24H)                                    │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Completions per Hour         [Time Series Graph]        │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Failure Rate by Stage        [Multi-line Graph]         │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Avg Time in Stage            [Bar Chart]                │ │
│ └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│ ROW 3: DEBUGGING (FILTERED BY VARIABLES)                    │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Recent Errors (Last Hour)    [Table]                    │ │
│ │ Time | Subdomain | Stage | Message | Job ID             │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Log Search                   [Logs Panel]               │ │
│ │ [Live tail mode supported]                              │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Pipeline Run Trace           [Table/Flame Graph]        │ │
│ │ fetch → ocr → compilation → extraction → deploy         │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## Panel Specifications

### Row 1: At-a-Glance Health

#### Panel 1.1: Stuck Sites Alert
**Type:** Stat panel (big number with threshold coloring)

**Data Source:** PostgreSQL

**Query:**
```sql
SELECT COUNT(*) as stuck_count
FROM sites
WHERE current_stage != 'completed'
  AND current_stage IS NOT NULL
  AND updated_at < NOW() - INTERVAL '2 hours'
  AND updated_at > NOW() - INTERVAL '$__range';
```

**Thresholds:**
- Green: 0-4 (Healthy)
- Yellow: 5-10 (Warning)
- Red: 11+ (Critical)

**Refresh:** 1 minute

**Click action:** Populate subdomain variable with stuck site list

---

#### Panel 1.2: Health Score
**Type:** Gauge (0-100%)

**Data Source:** PostgreSQL

**Query:**
```sql
SELECT ROUND(100.0 *
    COUNT(*) FILTER (
        WHERE current_stage = 'completed'
           OR updated_at >= NOW() - INTERVAL '2 hours'
    ) / NULLIF(COUNT(*), 0),
1) as health_score
FROM sites
WHERE current_stage IS NOT NULL
  AND started_at > NOW() - INTERVAL '$__range';
```

**Thresholds:**
- Green: 95-100% (Healthy)
- Yellow: 85-95% (Degraded)
- Red: <85% (Unhealthy)

**Rationale:** Matches success criteria from migration guide

**Refresh:** 1 minute

---

#### Panel 1.3: Stage Distribution
**Type:** Pie chart

**Data Source:** PostgreSQL

**Query:**
```sql
SELECT
    current_stage,
    COUNT(*) as count
FROM sites
WHERE current_stage IS NOT NULL
  AND updated_at > NOW() - INTERVAL '$__range'
GROUP BY current_stage
ORDER BY count DESC;
```

**Display:**
- Show percentages
- Legend on right
- Click slice → filters Stage variable

**Refresh:** 2 minutes

---

### Row 2: Trends (Last 24h)

#### Panel 2.1: Completions per Hour
**Type:** Time series graph (line chart)

**Data Source:** PostgreSQL

**Query:**
```sql
SELECT
    DATE_TRUNC('hour', updated_at) as time,
    COUNT(*) as completions
FROM sites
WHERE current_stage = 'completed'
  AND updated_at >= NOW() - INTERVAL '$__range'
  AND updated_at <= NOW()
GROUP BY time
ORDER BY time;
```

**Display:**
- Fill: 20% opacity
- Line width: 2px
- Y-axis: Completions
- Show null values as gaps (worker downtime)

**Refresh:** 5 minutes

---

#### Panel 2.2: Failure Rate by Stage
**Type:** Time series graph (multi-line)

**Data Source:** PostgreSQL

**Query:**
```sql
-- OCR failures
SELECT
    DATE_TRUNC('hour', updated_at) as time,
    'ocr' as stage,
    ROUND(100.0 * SUM(ocr_failed) / NULLIF(SUM(ocr_total), 0), 1) as failure_rate
FROM sites
WHERE ocr_total > 0
  AND updated_at >= NOW() - INTERVAL '$__range'
GROUP BY time

UNION ALL

-- Compilation failures
SELECT
    DATE_TRUNC('hour', updated_at) as time,
    'compilation' as stage,
    ROUND(100.0 * SUM(compilation_failed) / NULLIF(SUM(compilation_total), 0), 1) as failure_rate
FROM sites
WHERE compilation_total > 0
  AND updated_at >= NOW() - INTERVAL '$__range'
GROUP BY time

UNION ALL

-- Extraction failures
SELECT
    DATE_TRUNC('hour', updated_at) as time,
    'extraction' as stage,
    ROUND(100.0 * SUM(extraction_failed) / NULLIF(SUM(extraction_total), 0), 1) as failure_rate
FROM sites
WHERE extraction_total > 0
  AND updated_at >= NOW() - INTERVAL '$__range'
GROUP BY time

UNION ALL

-- Deploy failures
SELECT
    DATE_TRUNC('hour', updated_at) as time,
    'deploy' as stage,
    ROUND(100.0 * SUM(deploy_failed) / NULLIF(SUM(deploy_total), 0), 1) as failure_rate
FROM sites
WHERE deploy_total > 0
  AND updated_at >= NOW() - INTERVAL '$__range'
GROUP BY time

ORDER BY time, stage;
```

**Display:**
- Legend: show min/max/avg
- Y-axis: 0-100% (failure rate)
- Color by stage (consistent with other panels)

**Refresh:** 5 minutes

---

#### Panel 2.3: Average Time in Stage
**Type:** Bar chart (horizontal)

**Data Source:** PostgreSQL

**Query:**
```sql
SELECT
    current_stage as stage,
    AVG(EXTRACT(EPOCH FROM (updated_at - started_at))/3600) as avg_hours
FROM sites
WHERE started_at IS NOT NULL
  AND updated_at > NOW() - INTERVAL '$__range'
  AND current_stage IS NOT NULL
GROUP BY current_stage
ORDER BY avg_hours DESC;
```

**Display:**
- X-axis: Hours
- Y-axis: Stage names
- Show value labels on bars

**Use case:** Spot slowdowns (OCR normally 2hrs, now 8hrs?)

**Refresh:** 5 minutes

---

### Row 3: Debugging

#### Panel 3.1: Recent Errors (Last Hour)
**Type:** Table panel

**Data Source:** Loki

**Query (LogQL):**
```logql
{job="clerk"}
  |= `level`
  | json
  | level=~"error|warning"
  | subdomain=~"$subdomain"
  | stage=~"$stage"
  | line_format "{{.time}} | {{.subdomain}} | {{.stage}} | {{.message}}"
```

**Columns:**
- Time (timestamp)
- Subdomain (string)
- Stage (string)
- Message (string, width: auto-grow)
- Job ID (string, hidden if empty)

**Display:**
- Max rows: 50
- Sort: Time DESC
- Click row → expands JSON

**Refresh:** 30 seconds

---

#### Panel 3.2: Log Search
**Type:** Logs panel

**Data Source:** Loki

**Query (LogQL):**
```logql
{job="clerk"}
  | json
  | subdomain=~"$subdomain"
  | stage=~"$stage"
  | run_id=~"$run_id"
  | line_format "{{.time}} [{{.level}}] {{.subdomain}}/{{.stage}}: {{.message}}"
```

**Features:**
- Live tail toggle
- Full JSON view on expand
- Time highlighting
- Copy log line button

**Display:**
- Show labels: subdomain, stage, run_id, job_id
- Wrap lines: Yes
- Dedupe: None (show all)

**Refresh:** On demand (use live tail for real-time)

---

#### Panel 3.3: Pipeline Run Trace
**Type:** Table (or Trace panel if available)

**Data Source:** Loki

**Query (LogQL):**
```logql
{job="clerk"}
  | json
  | subdomain=~"$subdomain"
  | run_id=~"$run_id"
  | stage != ""
  | line_format "{{.stage}}: {{.message}} (job={{.job_id}})"
```

**Table Columns:**
- Time (timestamp)
- Stage (string, colored by stage)
- Message (string)
- Job ID (string)
- Duration (calculated: time between stages)

**Display:**
- Group by run_id
- Sort by time ASC (chronological)
- Highlight transitions (stage changes)

**Use case:** See full pipeline progression:
```
10:00:00 fetch: Started processing example.civic.band
10:05:23 fetch: Downloaded 12 PDFs
10:05:24 ocr: Initialized OCR stage with 12 documents
10:05:25 ocr: Spawned 12 OCR jobs
10:15:42 ocr: Completed 12/12 documents
10:15:43 compilation: Started compilation
10:16:12 compilation: Created meetings.db with 12 documents
10:16:13 extraction: Started extraction
10:18:45 extraction: Completed extraction
10:18:46 deploy: Deploying to S3
10:19:00 deploy: Deployment complete
```

**Refresh:** On demand

---

## Dashboard Variables

### Variable 1: Time Range
**Type:** Built-in time picker

**Default:** Last 24 hours

**Options:**
- Last 1 hour
- Last 6 hours
- Last 24 hours
- Last 7 days
- Custom range

---

### Variable 2: Subdomain
**Type:** Query variable (dropdown with multi-select)

**Data Source:** PostgreSQL

**Query:**
```sql
SELECT DISTINCT subdomain
FROM sites
WHERE updated_at > NOW() - INTERVAL '24 hours'
ORDER BY subdomain;
```

**Config:**
- Multi-value: Yes
- Include All: Yes (default)
- Regex filter: Yes
- Refresh: On dashboard load

**Used in:** All panels (filters by subdomain)

---

### Variable 3: Stage
**Type:** Custom variable (dropdown)

**Values:**
```
fetch
ocr
compilation
extraction
deploy
completed
```

**Config:**
- Multi-value: Yes
- Include All: Yes (default)

**Used in:** Rows 2-3 (filters by stage)

---

### Variable 4: Run ID
**Type:** Query variable (dropdown)

**Data Source:** Loki

**Query (LogQL):**
```logql
label_values({job="clerk", subdomain=~"$subdomain"}, run_id)
```

**Config:**
- Multi-value: No (one run at a time)
- Include All: Yes (default)
- Refresh: On dashboard load and time range change
- Sort: Descending (newest first)

**Used in:** Row 3 (filters to specific run)

**Use case:** After selecting subdomain, pick specific run to trace

---

## Alert Rules

### Alert 1: Stuck Sites Critical

**Name:** `clerk_stuck_sites_critical`

**Condition:** Stuck sites > 10 for 15 minutes

**Query:**
```sql
SELECT COUNT(*) as stuck_count
FROM sites
WHERE current_stage != 'completed'
  AND current_stage IS NOT NULL
  AND updated_at < NOW() - INTERVAL '2 hours';
```

**Evaluation:** Every 1 minute

**For:** 15 minutes (avoid false alarms)

**Threshold:** stuck_count > 10

**Severity:** Critical

**Notification:**
```
🚨 Clerk Pipeline Alert: Stuck Sites Critical

{{ $values.stuck_count }} sites have been stuck for >2 hours.

Dashboard: <link-to-dashboard>
Runbook: <link-to-runbook>
```

**Channels:** Slack #alerts, PagerDuty

---

### Alert 2: Health Score Degraded

**Name:** `clerk_health_degraded`

**Condition:** Health score < 85% for 10 minutes

**Query:**
```sql
SELECT ROUND(100.0 *
    COUNT(*) FILTER (
        WHERE current_stage = 'completed'
           OR updated_at >= NOW() - INTERVAL '2 hours'
    ) / NULLIF(COUNT(*), 0),
1) as health_score
FROM sites
WHERE current_stage IS NOT NULL
  AND started_at > NOW() - INTERVAL '24 hours';
```

**Evaluation:** Every 1 minute

**For:** 10 minutes

**Threshold:** health_score < 85

**Severity:** Warning

**Notification:**
```
⚠️ Clerk Pipeline Alert: Health Degraded

Pipeline health score is {{ $values.health_score }}% (threshold: 85%).

Dashboard: <link-to-dashboard>
```

**Channels:** Slack #alerts

---

### Alert 3: High OCR Failure Rate

**Name:** `clerk_ocr_failures_high`

**Condition:** OCR failure rate > 20% for any stage in last hour

**Query:**
```sql
SELECT
    'ocr' as stage,
    ROUND(100.0 * SUM(ocr_failed) / NULLIF(SUM(ocr_total), 0), 1) as failure_rate
FROM sites
WHERE ocr_total > 0
  AND updated_at >= NOW() - INTERVAL '1 hour';
```

**Evaluation:** Every 5 minutes

**For:** 15 minutes

**Threshold:** failure_rate > 20

**Severity:** Warning

**Notification:**
```
⚠️ Clerk Pipeline Alert: High OCR Failure Rate

OCR failure rate is {{ $values.failure_rate }}% in the last hour (threshold: 20%).

This may indicate:
- Batch of corrupted PDFs
- OCR service issues
- Tesseract configuration problem

Dashboard: <link-to-dashboard>
```

**Channels:** Slack #alerts

---

## Data Source Configuration

### PostgreSQL Data Source

**Name:** `civic-db`

**Type:** PostgreSQL

**Connection:**
```yaml
Host: <postgres-host>:5432
Database: clerk
User: grafana_readonly
Password: <from-secret>
SSL Mode: require (production)
Version: 14+ (supports FILTER clause)
```

**Recommended: Create read-only user**
```sql
-- On PostgreSQL server
CREATE USER grafana_readonly WITH PASSWORD 'secure_password';
GRANT CONNECT ON DATABASE clerk TO grafana_readonly;
GRANT USAGE ON SCHEMA public TO grafana_readonly;
GRANT SELECT ON sites TO grafana_readonly;

-- Verify
\c clerk grafana_readonly
SELECT COUNT(*) FROM sites; -- Should work
INSERT INTO sites VALUES (...); -- Should fail
```

**Query timeout:** 30 seconds

**Max open connections:** 5

---

### Loki Data Source

**Name:** `loki`

**Type:** Loki

**Connection:**
```yaml
URL: http://<loki-host>:3100
Timeout: 30s
Max lines: 5000
```

**Derived Fields** (make fields clickable):
```yaml
- Name: run_id
  Regex: run_id="([^"]+)"
  URL: /d/clerk-pipeline?var-run_id=${__value.raw}
  Internal link: Yes

- Name: subdomain
  Regex: subdomain="([^"]+)"
  URL: /d/clerk-pipeline?var-subdomain=${__value.raw}
  Internal link: Yes
```

**Why derived fields:** Click run_id in logs → filters entire dashboard to that run

---

## Implementation Plan

### Phase 1: Core Monitoring (Week 1)

**Goals:** Get basic health visibility working

**Tasks:**
1. Create read-only PostgreSQL user
2. Add PostgreSQL data source to Grafana
3. Add Loki data source to Grafana
4. Create dashboard with Row 1 panels (health check)
5. Add dashboard variables (time, subdomain, stage)
6. Test with production data
7. Deploy Alert 1 (stuck sites)

**Success criteria:**
- Panel 1.1 matches `clerk pipeline-status` output
- Can select subdomain from dropdown
- Alert fires when test site set to stuck

**Time estimate:** 2-3 hours

---

### Phase 2: Trends (Week 1-2)

**Goals:** Add historical context

**Tasks:**
1. Add Row 2 panels (completions, failure rates, time in stage)
2. Tune time series display (colors, legends, thresholds)
3. Deploy Alerts 2-3 (health score, failure rate)
4. Tune alert thresholds based on 1 week of data

**Success criteria:**
- Time series graphs show 24h of data
- Alerts fire with reasonable frequency (not too noisy)

**Time estimate:** 2 hours

---

### Phase 3: Debugging (Week 2)

**Goals:** Enable drill-down investigation

**Tasks:**
1. Add Row 3 panels (errors table, log search, run trace)
2. Configure derived fields for clickable run_id
3. Test drill-down workflow: Alert → Dashboard → Logs → Root cause
4. Add run_id variable for trace filtering
5. Document debugging workflow in runbook

**Success criteria:**
- Click stuck site → logs auto-filter to that site
- Can trace full pipeline run from fetch → deploy
- Errors table shows recent failures with context

**Time estimate:** 2 hours

---

### Phase 4: Refinement (Ongoing)

**Goals:** Tune based on usage

**Tasks:**
- Adjust alert thresholds (too noisy? too quiet?)
- Add panels based on questions ("How long per PDF?")
- Optimize slow queries (add indexes if needed)
- Archive old dashboard versions

**Time estimate:** Ad-hoc

---

## Testing & Validation

### Pre-Deployment Checklist

**Before deploying to production:**

1. **Verify PostgreSQL queries return data**
   ```bash
   psql $DATABASE_URL -f dashboard-queries.sql
   ```

2. **Verify Loki has recent logs**
   ```bash
   curl -G -s "http://loki:3100/loki/api/v1/query_range" \
     --data-urlencode 'query={job="clerk"}' | jq '.data.result | length'
   ```
   Expected: > 0 results

3. **Trigger test stuck site**
   ```sql
   UPDATE sites
   SET updated_at = NOW() - INTERVAL '3 hours'
   WHERE subdomain = 'test-site' AND current_stage = 'ocr';
   ```

4. **Verify dashboard shows stuck site**
   - Panel 1.1 should show count = 1
   - Health score should drop

5. **Verify alert fires**
   - Wait 15 minutes
   - Check Slack/PagerDuty for alert
   - Ack and resolve

6. **Verify drill-down workflow**
   - Select test-site in subdomain variable
   - Row 3 logs should filter to just that site
   - Should see OCR stage logs

7. **Reset test site**
   ```sql
   UPDATE sites
   SET updated_at = NOW()
   WHERE subdomain = 'test-site';
   ```

---

### Success Criteria

**Dashboard is production-ready when:**

- ✅ Panel 1.1 (stuck sites) matches `clerk pipeline-status` output exactly
- ✅ Panel 1.2 (health score) matches SQL query from migration guide
- ✅ Can click subdomain variable → all panels filter correctly
- ✅ Time series graphs show last 24h of activity (no data gaps)
- ✅ Alerts fire for test stuck site within 15 minutes
- ✅ Run trace shows full pipeline progression for a completed site
- ✅ Logs panel supports live tail mode
- ✅ Error table shows recent warnings/errors with full context

---

## Maintenance

### Daily Operations

**What ops team does:**
1. Check dashboard first thing (morning health check)
2. Investigate any red/yellow panels
3. Use filters to drill into stuck sites
4. Acknowledge alerts after investigation

**Time:** 2-5 minutes per day (if healthy)

---

### Weekly Tuning

**After first week:**
1. Review alert frequency
   - Too noisy? Increase thresholds or "for" duration
   - Too quiet? Decrease thresholds
2. Check query performance
   - Slow panels? Add indexes to PostgreSQL
3. Add missing panels based on questions asked

**Time:** 30 minutes per week

---

### Monthly Review

**Review dashboard usage:**
1. Which panels are most useful? (Grafana analytics)
2. Which panels are never used? (remove to declutter)
3. What questions still require manual queries? (add panels)

---

## Runbook Integration

### When Alert Fires

**Alert 1: Stuck Sites Critical**

1. Open dashboard → Panel 1.1 shows count
2. Click stuck sites → populates subdomain variable
3. Scroll to Row 3 → Recent Errors table
4. Look for errors in stuck site's logs
5. Common causes:
   - OCR job failures (check RQ failed registry)
   - Coordinator not enqueued (check coordinator_enqueued flag)
   - Worker crashed mid-job (restart workers)
6. Resolution:
   - If recoverable: Run `clerk reconcile-pipeline`
   - If stuck permanently: Investigate root cause, may need manual intervention

**Alert 2: Health Score Degraded**

1. Open dashboard → Panel 1.3 (stage distribution)
2. Large wedge in one stage? That's the bottleneck
3. Check Panel 2.2 (failure rates) for that stage
4. Drill into logs for that stage
5. Common causes:
   - Worker capacity (all workers busy)
   - External service issues (S3, OCR)
   - Bad batch of PDFs
6. Resolution:
   - Scale workers if capacity issue
   - Wait if transient spike
   - Investigate logs if consistent failures

**Alert 3: High OCR Failure Rate**

1. Open dashboard → Panel 2.2 (failure rate graph)
2. When did spike start? Recent batch of sites?
3. Filter Stage variable to "ocr"
4. Row 3 → Recent Errors → Look for patterns
5. Common causes:
   - Corrupted PDFs in a batch
   - Tesseract out of memory
   - Disk space full
6. Resolution:
   - Skip bad sites, investigate later
   - Restart OCR workers
   - Free up disk space

---

## Future Enhancements

**Not included in v1, but possible:**

1. **Cost tracking panel** - Show $ per site (S3, OCR API costs)
2. **PDF quality metrics** - Track page count, file size distribution
3. **Worker utilization heatmap** - See busy hours, optimize scheduling
4. **Anomaly detection** - ML-based alerts for unusual patterns
5. **Multi-tenant filtering** - If multiple customers, filter by customer
6. **Mobile view** - Responsive layout for phone monitoring

**Prioritize based on:** What questions come up most in first month

---

## Related Documentation

- **Monitoring Guide:** `docs/user-guide/monitoring.md` (existing `clerk health` command)
- **Migration Guide:** `docs/plans/MIGRATION-pipeline-state-consolidation-UPDATED.md` (SQL queries for monitoring)
- **Logging Design:** `docs/plans/2026-01-16-comprehensive-pipeline-logging-design.md` (log_with_context structure)
- **Pipeline State:** `docs/plans/2026-01-18-pipeline-state-consolidation-design.md` (atomic counter system)

---

## Appendix: Query Reference

### All PostgreSQL Queries (for dashboard-queries.sql)

```sql
-- Panel 1.1: Stuck Sites
SELECT COUNT(*) as stuck_count
FROM sites
WHERE current_stage != 'completed'
  AND current_stage IS NOT NULL
  AND updated_at < NOW() - INTERVAL '2 hours';

-- Panel 1.2: Health Score
SELECT ROUND(100.0 *
    COUNT(*) FILTER (
        WHERE current_stage = 'completed'
           OR updated_at >= NOW() - INTERVAL '2 hours'
    ) / NULLIF(COUNT(*), 0),
1) as health_score
FROM sites
WHERE current_stage IS NOT NULL
  AND started_at > NOW() - INTERVAL '24 hours';

-- Panel 1.3: Stage Distribution
SELECT
    current_stage,
    COUNT(*) as count
FROM sites
WHERE current_stage IS NOT NULL
  AND updated_at > NOW() - INTERVAL '24 hours'
GROUP BY current_stage
ORDER BY count DESC;

-- Panel 2.1: Completions per Hour
SELECT
    DATE_TRUNC('hour', updated_at) as time,
    COUNT(*) as completions
FROM sites
WHERE current_stage = 'completed'
  AND updated_at >= NOW() - INTERVAL '24 hours'
  AND updated_at <= NOW()
GROUP BY time
ORDER BY time;

-- Panel 2.2: Failure Rate by Stage (OCR example)
SELECT
    DATE_TRUNC('hour', updated_at) as time,
    'ocr' as stage,
    ROUND(100.0 * SUM(ocr_failed) / NULLIF(SUM(ocr_total), 0), 1) as failure_rate
FROM sites
WHERE ocr_total > 0
  AND updated_at >= NOW() - INTERVAL '24 hours'
GROUP BY time
ORDER BY time;

-- Panel 2.3: Average Time in Stage
SELECT
    current_stage as stage,
    AVG(EXTRACT(EPOCH FROM (updated_at - started_at))/3600) as avg_hours
FROM sites
WHERE started_at IS NOT NULL
  AND updated_at > NOW() - INTERVAL '24 hours'
  AND current_stage IS NOT NULL
GROUP BY current_stage
ORDER BY avg_hours DESC;

-- Variable 2: Subdomain dropdown
SELECT DISTINCT subdomain
FROM sites
WHERE updated_at > NOW() - INTERVAL '24 hours'
ORDER BY subdomain;
```

### All Loki Queries (LogQL)

```logql
# Panel 3.1: Recent Errors
{job="clerk"}
  |= `level`
  | json
  | level=~"error|warning"
  | subdomain=~"$subdomain"
  | stage=~"$stage"

# Panel 3.2: Log Search
{job="clerk"}
  | json
  | subdomain=~"$subdomain"
  | stage=~"$stage"
  | run_id=~"$run_id"

# Panel 3.3: Pipeline Run Trace
{job="clerk"}
  | json
  | subdomain=~"$subdomain"
  | run_id=~"$run_id"
  | stage != ""

# Variable 4: Run ID dropdown
label_values({job="clerk", subdomain=~"$subdomain"}, run_id)
```

---

## Design Decisions

### Why Single Dashboard (Not Multiple)?

**Considered:**
- Option A: One "Pipeline Health" + one "Pipeline Debugging"
- Option B: Multi-page dashboard with drill-downs
- **Option C: Single unified dashboard (chosen)**

**Rationale:**
- Alert → Investigate workflow is seamless (no navigation)
- Variables filter entire dashboard (consistent context)
- Less maintenance (one dashboard to keep updated)
- Grafana's row collapse feature keeps it manageable

**Trade-off:** Dashboard can feel crowded, but row collapse helps

---

### Why PostgreSQL + Loki (Not Just Loki)?

**Considered:**
- Option A: Loki only (parse metrics from logs)
- **Option B: PostgreSQL + Loki (chosen)**
- Option C: Prometheus exporter + Loki

**Rationale:**
- PostgreSQL queries are fast (indexed, optimized)
- Atomic counters already in database (no extra infrastructure)
- Loki for what it's good at (log searching, not metrics)
- Don't need real-time metrics (1min delay acceptable)

**Trade-off:** Two data sources to maintain, but simpler than adding Prometheus

---

### Why No Prometheus?

**Considered:**
- Adding Prometheus exporter for real-time metrics
- Using StatsD/Graphite for counters

**Rationale:**
- PostgreSQL queries fast enough (1min refresh acceptable)
- Don't need sub-second granularity
- Atomic counters already persisted in DB
- YAGNI - Can add Prometheus later if needed

**When to reconsider:** If dashboard queries slow down PostgreSQL or need <1min refresh

---

## Conclusion

This dashboard provides:
- **3-row layout:** Health → Trends → Debugging
- **4 variables:** Time, subdomain, stage, run_id
- **2 data sources:** PostgreSQL (metrics) + Loki (logs)
- **3 alerts:** Stuck sites, health score, failure rates
- **Single pane of glass:** No context switching from alert to root cause

**Estimated setup time:** 4-6 hours total (2hr core + 2hr trends + 2hr debugging)

**Maintenance:** 30min/week tuning + 2-5min/day monitoring
