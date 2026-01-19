# Pipeline State Consolidation - Production Migration Guide (UPDATED)

**Created:** 2026-01-18
**Updated:** 2026-01-19 (after document counting fix)
**Related Docs:**
- Design: `docs/plans/2026-01-18-pipeline-state-consolidation-design.md`
- Implementation Plan: `docs/plans/2026-01-18-pipeline-state-consolidation.md`
- Original Migration Guide: `docs/plans/MIGRATION-pipeline-state-consolidation.md`

## What's Changed

**Critical Fix Applied (PR #89):** The migration logic was mixing units:
- `ocr_total` counted PDF files (documents) ✅
- `ocr_completed` counted txt files (pages) ❌

This caused `ocr_completed > ocr_total` for sites where PDFs had multiple pages.

**Fix:** `count_txt_files()` now counts document directories (not individual txt files), ensuring both counters use document-level units.

**Impact:** The dry-run you ran previously showed incorrect counts. The instructions below start fresh with the fixed code.

---

## Overview

This migration consolidates pipeline state from 3 sources of truth (site_progress table, sites.status field, RQ job state) into a single source using atomic counters. This eliminates the root cause of stuck sites.

**Expected Impact:**
- Unsticks 105 sites currently in OCR stage
- Clears 82 deferred coordinators
- Clears 2,695 failed OCR jobs
- Enables self-healing via reconciliation job

---

## Current Status

You've completed:
- ✅ Step 1: Database backup
- ✅ Step 2: Schema migration (`clerk db upgrade`)
- ⚠️ Step 3: Dry-run (with buggy code - need to re-run)

Next:
- 🔄 Upgrade to fixed version
- 🔄 Re-run dry-run to verify counts
- ⏭️ Execute migration

---

## Step-by-Step Migration (From Current State)

### Step 0: Upgrade to Fixed Version (2 minutes)

**On production server:**

```bash
# Upgrade clerk to get the document counting fix (PR #89)
pip install --upgrade clerk

# Verify you have the latest version
clerk --version
```

**Expected:** Version should be >= the version that includes PR #89 merge

---

### Step 1: Re-run Migration Dry-Run (5 minutes)

The previous dry-run showed incorrect counts because it was counting pages instead of documents. Re-run to verify the fix:

```bash
# On production server
clerk migrate-stuck-sites --dry-run
```

**Expected output:**
```
================================================================================
MIGRATION: Stuck Sites to Atomic Counter System
================================================================================

DRY RUN MODE - no changes will be made

Found 105 stuck sites in OCR stage

  site1.ca.us: 12/15 completed, 3 failed
  site2.ca.us: 8/10 completed, 2 failed
  ...

Migrated 105 sites
```

**What to check:**
- ✅ `ocr_completed <= ocr_total` for ALL sites (no more 120/50 impossible ratios)
- ✅ Counts should be much smaller than before (documents, not pages)
- ✅ For sites where all PDFs completed OCR: `ocr_completed ≈ ocr_total`

**Note:** The counts represent DOCUMENTS (PDFs), not individual pages:
- `ocr_total` = number of PDF files
- `ocr_completed` = number of document directories with txt files
- Each document may have multiple txt files (one per page)

---

### Step 2: Execute Migration (10 minutes)

Once dry-run looks correct, execute the migration:

```bash
# On production server
clerk migrate-stuck-sites
```

**Expected output:**
```
================================================================================
MIGRATION: Stuck Sites to Atomic Counter System
================================================================================

Found 105 stuck sites in OCR stage

  site1.ca.us: 12/15 completed, 3 failed
  site2.ca.us: 8/10 completed, 2 failed
  ...

Migrated 105 sites

Clearing 82 deferred coordinators...
  Cancelled 82 deferred coordinators

Clearing 2695 failed OCR jobs...
  Deleted 2695 failed OCR jobs

Migration complete!
Next step: Run reconciliation job to unstick sites
  clerk reconcile-pipeline
```

**Verify migration:**
```bash
psql $DATABASE_URL -c "
SELECT subdomain, current_stage, ocr_total, ocr_completed, ocr_failed, coordinator_enqueued
FROM sites
WHERE current_stage = 'ocr'
LIMIT 10;
"
```

**Expected:** Migrated sites with document-level counters visible

---

### Step 3: Verify RQ Cleanup (2 minutes)

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

### Step 4: Run Initial Reconciliation (5 minutes)

Trigger recovery for migrated sites:

```bash
# On production server
clerk reconcile-pipeline
```

**Expected output:**
```
================================================================================
RECONCILIATION: 2026-01-19T20:30:00+00:00
================================================================================

Found 105 stuck sites:

  site1.ca.us: Found 12 completed documents, enqueueing coordinator
  site2.ca.us: Found 8 completed documents, enqueueing coordinator
  site3.ca.us: No completed OCR documents found - ALL OCR failed
  ...

Recovered 103 sites
```

**What to expect:**
- Sites with completed documents (ocr_completed > 0) will have coordinators enqueued
- Sites with no completed documents will be logged as "ALL OCR failed"
- The coordinator will process completed documents and move sites to next stage

**Monitor:** Watch RQ compilation queue for new coordinator jobs being processed:
```bash
uv run python -c "
from clerk.queue import get_compilation_queue
q = get_compilation_queue()
print(f'Active jobs: {len(q)}')
print(f'Started jobs: {len(q.started_job_registry)}')
"
```

---

### Step 5: Set Up Periodic Reconciliation (2 minutes)

Add reconciliation to cron for automatic recovery:

```bash
# On production server
crontab -e

# Add this line (runs every 15 minutes):
*/15 * * * * cd /path/to/civic-band && clerk reconcile-pipeline >> /var/log/clerk-reconcile.log 2>&1
```

**Verify cron entry:**
```bash
crontab -l | grep reconcile
```

---

### Step 6: Monitor Pipeline Progress (Ongoing)

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
 ocr           |    12  (decreasing)
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

## Understanding Document vs Page Counts

**Important:** All counters track DOCUMENTS (PDFs), not individual pages:

**Directory structure:**
```
storage/
  {subdomain}/
    pdfs/
      meeting1/
        2024-01-15.pdf          ← 1 document
        2024-02-20.pdf          ← 1 document
    txt/
      meeting1/
        2024-01-15/             ← 1 document directory
          page-1.txt            ← page 1 of document
          page-2.txt            ← page 2 of document
          page-3.txt            ← page 3 of document
        2024-02-20/             ← 1 document directory
          page-1.txt
```

**Counting logic:**
- `ocr_total` = 2 (counts PDF files in pdfs/)
- `ocr_completed` = 2 (counts directories in txt/ with at least one .txt file)
- `ocr_failed` = 0 (calculated as total - completed)

**Why this matters:**
- OCR jobs process entire documents (PDFs), not individual pages
- Coordinator triggers when `(completed + failed) == total` (all documents processed)
- Mixing units (documents vs pages) would break this equation

---

## Troubleshooting

### Issue: Still seeing ocr_completed > ocr_total

**Symptom:** After upgrade and re-running dry-run, still see impossible ratios

**Investigation:**
```bash
# Check clerk version
clerk --version

# Check which count_txt_files is being used
uv run python -c "
from clerk.migrations import count_txt_files
import inspect
print(inspect.getsource(count_txt_files))
"
```

**Expected:** Should see the fixed version that iterates over directories, not `glob("**/*.txt")`

**If still buggy:** pip cache might be stale
```bash
pip uninstall clerk
pip install clerk --no-cache-dir
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

---

## Success Criteria

### Immediate (First 24 Hours)
- ✅ Upgrade to fixed version completed
- ✅ Dry-run shows sensible document-level counts (no ocr_completed > ocr_total)
- ✅ 105 stuck sites migrated
- ✅ 0 deferred coordinators in RQ
- ✅ 0 failed OCR jobs blocking pipeline
- ✅ Coordinators being enqueued for recovered sites
- ✅ Reconciliation running every 15 minutes

### Ongoing (Next Week)
- ✅ <1% of sites stuck >2 hours
- ✅ Single SQL query shows accurate pipeline state
- ✅ No manual intervention needed for transient failures
- ✅ Errors tracked in logs/Sentry but not blocking

---

## Timeline

**Estimated total time: 20-25 minutes** (from current state)

- Step 0 (Upgrade): 2 min
- Step 1 (Re-run dry-run): 5 min
- Step 2 (Execute migration): 10 min
- Step 3 (RQ check): 2 min
- Step 4 (Reconciliation): 5 min
- Step 5 (Cron setup): 2 min
- Step 6 (Monitoring setup): 5 min

**Note:** No downtime required - migration is non-blocking.

---

## What Happens Next

After migration completes:

1. **Coordinators process completed documents** (5-30 min)
   - Sites move from `ocr` → `compilation` → `extraction` → `deploy` → `completed`
   - Progress visible in database: `SELECT current_stage, COUNT(*) FROM sites GROUP BY current_stage;`

2. **Reconciliation job auto-recovers any new stuck sites** (every 15 min)
   - Detects sites with stale `updated_at` timestamps
   - Infers state from filesystem
   - Enqueues missing coordinators

3. **Pipeline becomes self-healing**
   - Transient failures no longer permanently stick sites
   - Manual intervention rarely needed
   - All state in single source of truth (database)

---

## Support

**Questions during migration:**
- Check this guide first
- Review original migration guide: `docs/plans/MIGRATION-pipeline-state-consolidation.md`
- Check design doc: `docs/plans/2026-01-18-pipeline-state-consolidation-design.md`

**Monitoring:**
- RQ dashboard: Check active/failed/deferred jobs
- Database queries: Use verification queries above
- Logs: Check `/var/log/clerk-reconcile.log` for reconciliation output
