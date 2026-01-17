# Monitoring Your Clerk Pipeline

This guide covers monitoring and health checking for your clerk pipeline.

## Health Check Command

The `clerk health` command provides a comprehensive health check of your clerk pipeline, checking Redis connectivity, PostgreSQL connectivity, queue depths, worker status, and failed jobs.

### Basic Usage

```bash
# Quick health check
clerk health

# Detailed output with verbose logging
clerk health --verbose

# JSON output for monitoring systems
clerk health --json
```

### Exit Codes

The command returns different exit codes for automation:

- **0**: System healthy - all checks passed
- **1**: System degraded - warnings present but system operational
- **2**: System unhealthy - critical errors detected

### What Gets Checked

The health command performs the following checks:

#### 1. Redis Connectivity
Verifies Redis is accessible and responsive.

**Critical**: If Redis is down, no jobs can be enqueued or processed.

#### 2. PostgreSQL Connectivity
Verifies PostgreSQL civic.db database is accessible.

**Critical**: If PostgreSQL is down, job tracking and site metadata is unavailable.

#### 3. Queue Depths
Checks the number of pending jobs in each queue and compares against thresholds:

| Queue | Warning Threshold | Critical Threshold |
|-------|------------------|-------------------|
| high | 50 | 100 |
| fetch | 25 | 50 |
| ocr | 250 | 500 |
| compilation | 50 | 100 |
| extraction | 50 | 100 |
| deploy | 25 | 50 |

**Warning**: If queue depth exceeds warning threshold, you may need to scale workers.

**Critical**: If queue depth exceeds critical threshold, the system is likely overloaded.

#### 4. Worker Status
Checks the number of workers by status:

- **Total workers**: Total number of registered workers
- **Active workers**: Workers currently processing jobs
- **Busy workers**: Workers that are occupied
- **Idle workers**: Workers waiting for jobs

**Warning**: If idle workers is 0, all workers are busy and new jobs will queue.

#### 5. Failed Jobs
Counts the number of failed jobs in the last 24 hours.

**Warning**: More than 5 failed jobs indicates potential issues.

**Critical**: More than 20 failed jobs indicates serious problems.

#### 6. Job Completion Rate
Calculates the percentage of jobs that completed successfully in the last hour.

**Warning**: Less than 95% completion rate indicates issues.

**Critical**: Less than 80% completion rate indicates serious problems.

#### 7. Stuck Sites
Identifies sites that have been in progress for more than 2 hours without completing.

**Warning**: Sites stuck in progress may have failed jobs or infinite loops.

### Example Output

#### Healthy System

```bash
$ clerk health

===================
Clerk Health Check
===================

✓ Redis: Connected
✓ PostgreSQL: Connected

Queue Depths:
  high: 0
  fetch: 2
  ocr: 45
  compilation: 1
  extraction: 3
  deploy: 0

Workers:
  Total: 12
  Active: 8
  Busy: 5
  Idle: 7

✓ Failed jobs (24h): 0
✓ Job completion rate (1h): 100.0%
✓ No sites stuck in progress

Status: ✓ Healthy
```

#### Degraded System

```bash
$ clerk health

===================
Clerk Health Check
===================

✓ Redis: Connected
✓ PostgreSQL: Connected

Queue Depths:
  high: 5
  fetch: 150 ⚠ (threshold: 50)
  ocr: 350 ⚠ (threshold: 500)
  compilation: 12
  extraction: 8
  deploy: 2

Workers:
  Total: 4
  Active: 4
  Busy: 4
  Idle: 0 ⚠

⚠ Failed jobs (24h): 12
✓ Job completion rate (1h): 92.5%
⚠ Sites stuck in progress (2): example.civic.band, test.civic.band

Status: ⚠ Degraded

$ echo $?
1
```

#### Unhealthy System

```bash
$ clerk health

===================
Clerk Health Check
===================

✗ Redis: Connection refused
✓ PostgreSQL: Connected

Queue Depths:
  Cannot check - Redis unavailable

Workers:
  Cannot check - Redis unavailable

✗ Failed jobs (24h): Unable to check
✗ Job completion rate (1h): Unable to check
✗ Sites stuck in progress: Unable to check

Status: ✗ Unhealthy

$ echo $?
2
```

### JSON Output

The `--json` flag outputs structured JSON for integration with monitoring systems:

```bash
$ clerk health --json
```

```json
{
  "status": "healthy",
  "exit_code": 0,
  "checks": {
    "redis": {
      "status": "ok",
      "message": "Connected"
    },
    "postgresql": {
      "status": "ok",
      "message": "Connected"
    },
    "queue_depths": {
      "high": 0,
      "fetch": 2,
      "ocr": 45,
      "compilation": 1,
      "extraction": 3,
      "deploy": 0,
      "warnings": []
    },
    "workers": {
      "total": 12,
      "active": 8,
      "busy": 5,
      "idle": 7,
      "warnings": []
    },
    "failed_jobs_24h": {
      "count": 0,
      "status": "ok"
    },
    "completion_rate_1h": {
      "rate": 100.0,
      "status": "ok"
    },
    "stuck_sites": {
      "count": 0,
      "sites": [],
      "status": "ok"
    }
  }
}
```

### Integration with Monitoring Systems

#### Nagios/Icinga

```bash
# /etc/nagios/commands.cfg
define command {
    command_name check_clerk_health
    command_line /usr/local/bin/clerk health
}
```

#### Prometheus + Alertmanager

Create a script that exports metrics:

```bash
#!/bin/bash
# /usr/local/bin/clerk-health-exporter.sh

clerk health --json | jq -r '
  .checks.queue_depths | to_entries[] |
  "clerk_queue_depth{queue=\"\(.key)\"} \(.value)"
'
```

#### Cron-based Monitoring

```bash
# Check health every 5 minutes, alert on failure
*/5 * * * * clerk health || /usr/local/bin/alert-on-clerk-failure.sh
```

## Job Completion Verification

As of Phase 1 resilience improvements, all worker jobs now include completion verification:

### Fetch Stage Verification
- Warns if no PDFs were downloaded
- Logs directory existence for debugging

### OCR Completion Verification
- Verifies text files exist before proceeding to compilation
- Fails fast if OCR produced no output

### Database Compilation Verification
- Verifies meetings.db file was created
- Verifies meetings.db contains tables (not empty)
- Verifies page count was updated in PostgreSQL
- Warns if page count is 0 after update

### Deployment Verification
- Verifies sites.db was created by post_deploy hook
- Warns if sites.db is missing
- Verifies site status is "deployed" in database
- Warns if status is incorrect

All verification failures are logged with structured context including subdomain, run_id, and stage for easy debugging.

## Troubleshooting

### High Queue Depths

If queue depths are consistently high:

1. **Scale workers horizontally**: Add more worker processes or machines
2. **Check worker logs**: Look for slow or failing jobs
3. **Profile jobs**: Identify bottlenecks in the pipeline

### Failed Jobs

If you see many failed jobs:

1. **Check job logs**: `clerk logs --failed`
2. **Retry failed jobs**: Jobs with transient failures can be retried
3. **Fix root cause**: Address underlying issues (network, permissions, etc.)

### Stuck Sites

If sites are stuck in progress:

1. **Check job status**: `clerk status --subdomain example.civic.band`
2. **Check worker logs**: Look for errors or infinite loops
3. **Check queue**: Verify jobs aren't stuck in queue
4. **Manual intervention**: May need to reset site progress or retry jobs

### No Idle Workers

If all workers are busy:

1. **Check job duration**: Are jobs taking longer than expected?
2. **Scale workers**: Add more worker capacity
3. **Optimize jobs**: Profile and optimize slow operations

## See Also

- [Troubleshooting Workers](troubleshooting-workers.md) - Worker-specific issues
- [Task Queue Guide](task-queue.md) - Understanding the queue system
