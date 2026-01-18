# Pipeline State Consolidation - Production Migration Guide

**Created:** 2026-01-18
**Branch:** `fix-ocr-failure-resilience`
**Related Docs:**
- Design: `docs/plans/2026-01-18-pipeline-state-consolidation-design.md`
- Implementation Plan: `docs/plans/2026-01-18-pipeline-state-consolidation.md`

## Overview

This migration consolidates pipeline state from 3 sources of truth (site_progress table, sites.status field, RQ job state) into a single source using atomic counters. This eliminates the root cause of stuck sites.

**Expected Impact:**
- Unsticks 105 sites currently in OCR stage
- Clears 82 deferred coordinators
- Clears 2,695 failed OCR jobs
- Enables self-healing via reconciliation job

## Pre-Migration Checklist

- [ ] All code from `fix-ocr-failure-resilience` branch is merged to main
- [ ] New code is deployed to production servers
- [ ] Database backup completed
- [ ] Maintenance window scheduled (estimate: 30 minutes)
- [ ] Tested migration script with `--dry-run` on production

## Step-by-Step Migration

### Step 1: Backup Database (5 minutes)

```bash
# On production server
pg_dump $DATABASE_URL > backup_before_migration_$(date +%Y%m%d_%H%M%S).sql

# Verify backup
ls -lh backup_before_migration_*.sql
```

**Expected:** Backup file created, size ~XXX MB

---

### Step 2: Apply Schema Migration (5 minutes)

```bash
# On production server
psql $DATABASE_URL < migrations/001_add_pipeline_state_columns.sql
```

**Expected output:**
```
ALTER TABLE
ALTER TABLE
ALTER TABLE
... (21 ALTER TABLE statements)
CREATE INDEX
CREATE INDEX
CREATE INDEX
COMMENT
COMMENT
```

**Verify schema changes:**
```bash
psql $DATABASE_URL -c "\d sites" | grep -E "(ocr_total|coordinator_enqueued|current_stage)"
```

**Expected:** New columns visible with correct types

---

### Step 3: Migration Script - Dry Run (5 minutes)

Test the migration script without making changes:

```bash
# On production server, in clerk directory
uv run python scripts/migrate_stuck_sites.py --dry-run
```

**Expected output:**
```
================================================================================
MIGRATION: Stuck Sites to Atomic Counter System
================================================================================

DRY RUN MODE - no changes will be made

Found 105 stuck sites in OCR stage

  site1.ca.us: 12/15 completed, 3 failed
  site2.ca.us: 0/0 completed, 0 failed
  ...

Would migrate 105 sites (dry-run)

Dry run complete - run without --dry-run to apply changes
```

**Review:** Check the inferred counts make sense (completed should match txt file counts)

---

### Step 4: Run Migration Script (10 minutes)

```bash
# On production server
uv run python scripts/migrate_stuck_sites.py
```

**Expected output:**
```
================================================================================
MIGRATION: Stuck Sites to Atomic Counter System
================================================================================

Found 105 stuck sites in OCR stage

  site1.ca.us: 12/15 completed, 3 failed
  site2.ca.us: 0/0 completed, 0 failed
  ...

Migrated 105 sites

Clearing 82 deferred coordinators...
  Cancelled 82 deferred coordinators

Clearing 2695 failed OCR jobs...
  Deleted 2695 failed OCR jobs

RQ cleanup complete

Migration complete!
Next step: Run reconciliation job to unstick sites
  python scripts/reconcile_pipeline.py
```

**Verify migration:**
```bash
psql $DATABASE_URL -c "
SELECT subdomain, current_stage, ocr_total, ocr_completed, ocr_failed, coordinator_enqueued
FROM sites
WHERE current_stage = 'ocr'
LIMIT 5;
"
```

**Expected:** Migrated sites with inferred counters visible

---

### Step 5: Verify RQ Cleanup (2 minutes)

Check that RQ queues are cleared:

```bash
# On production server
uv run python -c "
from clerk.queue import get_compilation_queue, get_ocr_queue
comp_q = get_compilation_queue()
ocr_q = get_ocr_queue()
print(f'Deferred coordinators: {len(comp_q.deferred_job_registry)}')
print(f'Failed OCR jobs: {len(ocr_q.failed_job_registry)}')
"
```

**Expected:**
```
Deferred coordinators: 0
Failed OCR jobs: 0
```

---

### Step 6: Run Initial Reconciliation (5 minutes)

Trigger recovery for migrated sites:

```bash
# On production server
uv run python scripts/reconcile_pipeline.py
```

**Expected output:**
```
================================================================================
RECONCILIATION: 2026-01-18T20:30:00+00:00
================================================================================

Found 105 stuck sites:

  site1.ca.us: Found 12 txt files, enqueueing coordinator
  site2.ca.us: No txt files found - ALL OCR failed
  ...

Recovered 103 sites
```

**Monitor:** Watch RQ compilation queue for new coordinator jobs being processed

---

### Step 7: Set Up Periodic Reconciliation (2 minutes)

Add reconciliation to cron for automatic recovery:

```bash
# On production server
crontab -e

# Add this line (runs every 15 minutes):
*/15 * * * * cd /path/to/clerk && uv run python scripts/reconcile_pipeline.py >> /var/log/clerk-reconcile.log 2>&1
```

**Verify cron entry:**
```bash
crontab -l | grep reconcile
```

---

### Step 8: Monitor Pipeline Progress (Ongoing)

Watch sites progress through the pipeline:

```bash
# Check pipeline state distribution
psql $DATABASE_URL -c "
SELECT current_stage, COUNT(*) as count
FROM sites
WHERE current_stage IS NOT NULL
GROUP BY current_stage
ORDER BY count DESC;
"
```

**Expected progression over next hours:**
```
 current_stage | count
---------------+-------
 completed     |   189  (increasing)
 extraction    |    45  (new)
 compilation   |    23  (new)
 ocr          |    12  (decreasing)
```

**Check for stuck sites (should be minimal):**
```bash
psql $DATABASE_URL -c "
SELECT COUNT(*) as stuck_count
FROM sites
WHERE current_stage != 'completed'
  AND current_stage IS NOT NULL
  AND updated_at < NOW() - INTERVAL '2 hours';
"
```

**Expected:** < 5 stuck sites (reconciliation should auto-recover these every 15 min)

---

## Verification Queries

### Overall Health Check
```sql
-- Sites by stage
SELECT current_stage, COUNT(*) as count
FROM sites WHERE current_stage IS NOT NULL
GROUP BY current_stage ORDER BY count DESC;

-- Failure rates
SELECT
  ROUND(100.0 * SUM(ocr_failed) / NULLIF(SUM(ocr_total), 0), 1) as ocr_failure_rate,
  ROUND(100.0 * SUM(compilation_failed) / NULLIF(SUM(compilation_total), 0), 1) as compilation_failure_rate
FROM sites WHERE ocr_total > 0;
```

### Sites That Need Attention
```sql
-- Sites stuck >2 hours
SELECT subdomain, current_stage, updated_at,
       ocr_total, ocr_completed, ocr_failed,
       EXTRACT(EPOCH FROM (NOW() - updated_at))/3600 as hours_stuck
FROM sites
WHERE current_stage != 'completed'
  AND updated_at < NOW() - INTERVAL '2 hours'
ORDER BY hours_stuck DESC
LIMIT 10;

-- Sites with high failure rates
SELECT subdomain, current_stage,
       ocr_total, ocr_completed, ocr_failed,
       ROUND(100.0 * ocr_failed / NULLIF(ocr_total, 0), 1) as failure_rate
FROM sites
WHERE ocr_total > 0
  AND ocr_failed > 0
ORDER BY failure_rate DESC
LIMIT 10;
```

---

## Rollback Plan

### If Issues During Migration (Before Step 4)

**Just stop and revert:**
```bash
# New columns don't affect old code, can deploy later
# No rollback needed - old code continues working
```

### If Issues After Migration (Steps 4-6)

**Revert code deployment:**
```bash
git revert <commit-sha>
# Deploy old code
# Old code still works with site_progress table
# New column data preserved for retry
```

**Data is NOT lost** - both systems work during transition.

### After Cleanup (site_progress dropped)

**Cannot easily rollback** - would need to restore from backup.

**Prevention:** Wait 24-48 hours and verify thoroughly before cleanup (Task 9).

---

## Success Criteria

### Immediate (First 24 Hours)
- ✅ Schema migration applied successfully
- ✅ 105 stuck sites migrated
- ✅ 0 deferred coordinators in RQ
- ✅ 0 failed OCR jobs blocking pipeline
- ✅ New sites complete pipeline end-to-end
- ✅ Reconciliation running every 15 minutes

### Ongoing (Next Week)
- ✅ <1% of sites stuck >2 hours
- ✅ Single SQL query shows accurate pipeline state
- ✅ No manual intervention needed for transient failures
- ✅ Errors tracked in logs/Sentry but not blocking

---

## Troubleshooting

### Issue: Migration script fails partway through

**Symptom:** Script crashes with database error
**Solution:**
```bash
# Check how many sites were migrated before error
psql $DATABASE_URL -c "SELECT COUNT(*) FROM sites WHERE current_stage = 'ocr' AND ocr_total > 0;"

# Re-run migration script (idempotent)
uv run python scripts/migrate_stuck_sites.py
```

### Issue: Reconciliation keeps finding same stuck sites

**Symptom:** Same sites appear in reconciliation output every run
**Investigation:**
```bash
# Check if coordinator is being enqueued
psql $DATABASE_URL -c "SELECT subdomain, coordinator_enqueued, ocr_total, ocr_completed FROM sites WHERE subdomain = 'stuck-site';"

# Check RQ compilation queue
uv run python -c "from clerk.queue import get_compilation_queue; q = get_compilation_queue(); print(f'Active: {len(q)}, Started: {len(q.started_job_registry)}')"
```

**Common causes:**
- Workers not running (check `supervisorctl status clerk-workers`)
- Coordinator jobs failing (check RQ failed registry)
- Database write permission issues

### Issue: High failure rates (>20%)

**Symptom:** Many sites showing high ocr_failed counts
**Investigation:**
```bash
# Check error messages
psql $DATABASE_URL -c "SELECT last_error_stage, last_error_message, COUNT(*) FROM sites WHERE last_error_stage = 'ocr' GROUP BY last_error_stage, last_error_message ORDER BY COUNT(*) DESC LIMIT 5;"

# Common errors and solutions:
# - "PDF corrupted" → Expected for some PDFs, not a system issue
# - "Permission denied" → Check filesystem permissions
# - "Timeout" → Increase job timeout or worker resources
```

---

## Timeline

**Estimated total time: 30-45 minutes**

- Step 1 (Backup): 5 min
- Step 2 (Schema): 5 min
- Step 3 (Dry-run): 5 min
- Step 4 (Migration): 10 min
- Step 5 (RQ check): 2 min
- Step 6 (Reconciliation): 5 min
- Step 7 (Cron setup): 2 min
- Step 8 (Monitoring setup): 5 min

**Recommended:** Schedule during low-traffic period, though migration is non-blocking.

---

## Post-Migration (24-48 Hours Later)

After verifying the new system works:

### Task 9: Cleanup Deprecated Tables

See Task 9 in implementation plan for detailed cleanup steps:
- Drop site_progress table
- (Optional) Remove deprecated columns from sites table
- Update documentation

**Do not rush cleanup** - ensure system is stable first.

---

## Support

**Questions during migration:**
- Check implementation plan: `docs/plans/2026-01-18-pipeline-state-consolidation.md`
- Check design doc: `docs/plans/2026-01-18-pipeline-state-consolidation-design.md`
- Review code commits on `fix-ocr-failure-resilience` branch

**Monitoring:**
- RQ dashboard: Check active/failed/deferred jobs
- Database queries: Use verification queries above
- Logs: Check `/var/log/clerk-reconcile.log` for reconciliation output
