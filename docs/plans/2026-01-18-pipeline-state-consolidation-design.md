# Pipeline State Consolidation Design

**Date:** 2026-01-18
**Status:** Design Approved
**Problem:** Multiple sources of truth (sites table, site_progress table, RQ job state) get out of sync, causing sites to get stuck in pipeline

## Executive Summary

This design consolidates pipeline state management into a single source of truth (the `sites` table) using atomic counters and eliminates dependency on RQ's job dependency mechanism. The new system is resilient to failures, observable via SQL queries, and self-healing via reconciliation.

**Key changes:**
- Merge `site_progress` table into `sites` table
- Use atomic counters (`stage_total`, `stage_completed`, `stage_failed`) for all stages
- Last job in fan-out atomically triggers coordinator (no RQ dependencies)
- Reconciliation job detects and recovers stuck sites
- Best-effort progression: failures tracked but don't block pipeline

## Current State Problems

**Evidence gathered 2026-01-18:**
- 105 sites stuck in `site_progress.current_stage = 'ocr'`
- 91 sites stuck in `sites.status = 'needs_ocr'`
- 82 deferred coordinators in RQ compilation queue
- 2,695 failed OCR jobs in RQ failed registry
- Tables out of sync: 108 sites not "completed" vs 85 sites not "deployed"

**Root causes:**
1. **Multiple sources of truth**: `sites.status`, `sites.extraction_status`, `site_progress.current_stage`, RQ job states
2. **RQ dependencies blocking**: Coordinators use `depends_on=ocr_jobs`. When OCR jobs fail → coordinator moves to deferred → stuck forever
3. **No reconciliation**: Failed jobs accumulate, no automatic recovery
4. **State updates scattered**: Different code paths update different tables inconsistently

## Architecture Principles

### 1. Single Source of Truth: Database

The `sites` table owns all pipeline state. RQ is purely an execution engine.

**What this means:**
- To know "what stage is site X in?" → query `sites.current_stage`
- To know "how much OCR is done?" → query `sites.ocr_completed / sites.ocr_total`
- To know "is site stuck?" → query `sites.updated_at`
- RQ job state (queued/started/failed) is ephemeral and doesn't control pipeline flow

### 2. Atomic Counters

Every pipeline stage uses the same counter pattern:
- `{stage}_total`: How many jobs for this stage
- `{stage}_completed`: How many succeeded
- `{stage}_failed`: How many failed

**Completion logic:** `completed + failed == total` means stage is done

### 3. Best-Effort Progression

Failures are tracked for observability but don't block the pipeline.

**Example:** Site has 100 PDFs for OCR. 95 succeed, 5 fail.
- `ocr_total = 100`, `ocr_completed = 95`, `ocr_failed = 5`
- Coordinator runs when `95 + 5 == 100`
- Coordinator checks: "are there ANY txt files?" (yes: 95)
- Pipeline proceeds to compilation with 95 documents
- 5 failures logged to Sentry for investigation

### 4. Self-Triggering Coordinators

No RQ `depends_on`. Last job atomically claims coordinator enqueue.

**Pattern:**
```python
# Each OCR job finishes with:
UPDATE sites
SET ocr_completed = ocr_completed + 1
WHERE subdomain = 'example'

# Then checks:
if ocr_completed + ocr_failed == ocr_total
   AND coordinator_enqueued == FALSE:

    # Atomic claim (only one job succeeds):
    UPDATE sites
    SET coordinator_enqueued = TRUE
    WHERE subdomain = 'example'
      AND coordinator_enqueued = FALSE

    if rowcount == 1:
        enqueue_coordinator()
```

### 5. Reconciliation-Based Recovery

Separate job runs every 15 minutes to detect and fix stuck sites.

**Detects:**
- Sites with `updated_at` > 2 hours old
- Sites with incomplete counters but no active RQ jobs
- Sites with work done (txt files exist) but coordinator not enqueued

**Recovers:**
- Infers state from reality (counts files on disk)
- Updates database to match reality
- Enqueues missing coordinators
- Re-enqueues lost jobs

## Unified Schema

### Sites Table (Extended)

```sql
-- Existing columns (kept)
subdomain VARCHAR PRIMARY KEY
name VARCHAR
state VARCHAR  -- US state
kind VARCHAR
scraper VARCHAR
pages INT
start_year INT
extra VARCHAR
country VARCHAR
lat VARCHAR
lng VARCHAR

-- NEW: Pipeline state
current_stage VARCHAR  -- fetch|ocr|compilation|extraction|deploy|completed
started_at TIMESTAMP
updated_at TIMESTAMP

-- NEW: Fetch stage counters
fetch_total INT DEFAULT 0
fetch_completed INT DEFAULT 0
fetch_failed INT DEFAULT 0

-- NEW: OCR stage counters
ocr_total INT DEFAULT 0
ocr_completed INT DEFAULT 0
ocr_failed INT DEFAULT 0

-- NEW: Compilation stage counters
compilation_total INT DEFAULT 0
compilation_completed INT DEFAULT 0
compilation_failed INT DEFAULT 0

-- NEW: Extraction stage counters
extraction_total INT DEFAULT 0
extraction_completed INT DEFAULT 0
extraction_failed INT DEFAULT 0

-- NEW: Deploy stage counters
deploy_total INT DEFAULT 0
deploy_completed INT DEFAULT 0
deploy_failed INT DEFAULT 0

-- NEW: Coordinator tracking
coordinator_enqueued BOOLEAN DEFAULT FALSE

-- NEW: Error observability
last_error_stage VARCHAR
last_error_message TEXT
last_error_at TIMESTAMP

-- DEPRECATED (keep during migration, remove later)
status VARCHAR  -- replaced by current_stage + counters
extraction_status VARCHAR  -- replaced by extraction_* counters
last_updated VARCHAR  -- replaced by updated_at
last_deployed VARCHAR  -- keep for backward compat
last_extracted VARCHAR  -- keep for backward compat
```

### Supporting Tables (Unchanged)

**job_tracking** - Audit log of RQ jobs created (used for debugging/cancellation)
- `rq_job_id`, `subdomain`, `job_type`, `stage`, `created_at`

**site_progress** - Deprecated after migration, eventually drop

## Job Workflow Pattern

All jobs follow this pattern:

```python
def stage_job_template(subdomain, job_specific_args):
    """Template pattern all pipeline jobs follow."""

    # 1. Do the actual work
    try:
        result = perform_work(job_specific_args)
        success = True
        error = None
    except Exception as e:
        log_error(e)
        success = False
        error = e

    # 2. Atomic database update
    with civic_db_connection() as conn:
        if success:
            stmt = update(sites_table).where(
                sites_table.c.subdomain == subdomain
            ).values(
                stage_completed=sites_table.c.stage_completed + 1,
                updated_at=datetime.now(UTC)
            )
        else:
            stmt = update(sites_table).where(
                sites_table.c.subdomain == subdomain
            ).values(
                stage_failed=sites_table.c.stage_failed + 1,
                last_error_stage='stage_name',
                last_error_message=str(error)[:500],  # truncate
                last_error_at=datetime.now(UTC),
                updated_at=datetime.now(UTC)
            )

        conn.execute(stmt)

        # 3. Check if we're the last job (fan-in trigger)
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == subdomain)
        ).fetchone()

        if (site.stage_completed + site.stage_failed == site.stage_total
            and not site.coordinator_enqueued):

            # Atomic claim of coordinator enqueue
            claim = update(sites_table).where(
                sites_table.c.subdomain == subdomain,
                sites_table.c.coordinator_enqueued == False
            ).values(
                coordinator_enqueued=True
            )

            claim_result = conn.execute(claim)

            if claim_result.rowcount == 1:
                # We won the race - enqueue coordinator
                get_next_queue().enqueue(
                    stage_coordinator,
                    subdomain=subdomain,
                    run_id=get_run_id()
                )
```

**Key points:**
- Job always updates database (success or failure)
- Failed jobs contribute to progress (`stage_failed` increments)
- Last job atomically claims coordinator enqueue via WHERE clause
- Database transaction ensures no race conditions

## Coordinator Role

**Purpose:** Transition between pipeline stages after fan-out work completes

**Example - OCR Coordinator:**

```python
def ocr_complete_coordinator(subdomain, run_id):
    """Runs after all OCR jobs finish (success or failure)."""

    # 1. Sanity check: did ANY work succeed?
    txt_dir = Path(f"{STORAGE_DIR}/{subdomain}/txt")
    txt_files = list(txt_dir.glob("**/*.txt"))

    if len(txt_files) == 0:
        raise ValueError(f"No txt files found - ALL OCR jobs failed")

    # 2. Update database: transition to next stage
    with civic_db_connection() as conn:
        conn.execute(
            update(sites_table).where(
                sites_table.c.subdomain == subdomain
            ).values(
                current_stage='extraction',
                compilation_total=1,
                extraction_total=1,
                coordinator_enqueued=False,  # reset for next stage
                updated_at=datetime.now(UTC)
            )
        )

    # 3. Fan out to next stage(s)
    get_compilation_queue().enqueue(compile_db_job, subdomain, ...)
    get_extraction_queue().enqueue(extract_entities_job, subdomain, ...)
```

**What coordinator is NOT:**
- ❌ Waiting on RQ dependencies (no `depends_on`)
- ❌ Managing state (database does that)
- ❌ Deciding if work is complete (counters do that)

**What coordinator IS:**
- ✓ Sanity checking (e.g., "at least one txt file exists")
- ✓ Transitioning stages in database
- ✓ Kicking off next stage jobs

## Reconciliation Job

Runs every 15 minutes via cron/scheduler.

```python
def reconcile_pipeline():
    """Detect and recover stuck sites."""

    with civic_db_connection() as conn:
        # Query 1: Sites stuck too long
        stuck_sites = conn.execute("""
            SELECT * FROM sites
            WHERE current_stage != 'completed'
              AND updated_at < NOW() - INTERVAL '2 hours'
        """).fetchall()

        for site in stuck_sites:
            diagnose_and_recover(site)

        # Query 2: Sites with incomplete counters but no active jobs
        incomplete_sites = conn.execute("""
            SELECT * FROM sites
            WHERE current_stage != 'completed'
              AND (stage_completed + stage_failed) < stage_total
        """).fetchall()

        for site in incomplete_sites:
            if not has_active_rq_jobs(site.subdomain, site.current_stage):
                log_warning(f"{site.subdomain} stuck: no jobs but incomplete")
                recover_stuck_site(site)

def diagnose_and_recover(site):
    """Infer state from reality and fix."""

    if site.current_stage == 'ocr':
        # Count actual txt files
        txt_count = count_txt_files(site.subdomain)

        if txt_count > 0 and not site.coordinator_enqueued:
            # Work was done but coordinator never enqueued
            log_info(f"Recovering {site.subdomain}: {txt_count} txt files, enqueueing coordinator")

            with civic_db_connection() as conn:
                conn.execute(
                    update(sites_table).where(
                        sites_table.c.subdomain == site.subdomain
                    ).values(
                        ocr_completed=txt_count,
                        coordinator_enqueued=True,
                        updated_at=datetime.now(UTC)
                    )
                )

            get_compilation_queue().enqueue(
                ocr_complete_coordinator,
                subdomain=site.subdomain,
                run_id=f"{site.subdomain}_recovered"
            )

        elif txt_count == 0:
            log_error(f"{site.subdomain}: ALL OCR failed, needs investigation")
            # Manual intervention needed

    elif site.current_stage in ['compilation', 'extraction', 'deploy']:
        # These are 1:1 jobs, simpler
        if not has_active_rq_jobs(site.subdomain, site.current_stage):
            log_warning(f"{site.subdomain}: {site.current_stage} job lost, re-enqueueing")
            reenqueue_stage(site.subdomain, site.current_stage)
```

**Recovery actions:**
- Infer state from filesystem (count txt files, PDF files)
- Update database to match reality
- Enqueue missing coordinators
- Re-enqueue lost jobs
- Log errors for manual investigation (e.g., ALL jobs failed)

## Testing Strategy

### Unit Tests

1. **Atomic counter updates**
   - Concurrent jobs updating same site
   - Verify all increments counted
   - Verify last job claims coordinator exactly once

2. **Coordinator enqueue race**
   - 100 jobs finish simultaneously
   - Only 1 coordinator enqueued
   - Database constraint prevents duplicates

3. **Stage transitions**
   - Verify `current_stage` updates correctly
   - Verify counters reset for next stage

### Integration Tests

4. **End-to-end happy path**
   - Site flows through: fetch → ocr → compilation → extraction → deploy → completed
   - Verify database state at each stage
   - Verify exactly one coordinator per stage

5. **Partial failure scenarios**
   - 50% of OCR jobs fail → coordinator still runs
   - Pipeline completes with partial data
   - Failures logged to Sentry

6. **Complete failure**
   - ALL OCR jobs fail → coordinator runs → fails sanity check
   - Site marked as error state
   - Manual intervention required

### Reconciliation Tests

7. **Stuck site detection**
   - Site stuck >2 hours → detected
   - Txt files exist → coordinator enqueued
   - Site unstuck automatically

8. **Lost job recovery**
   - Job crashes without updating database
   - Reconciliation detects incomplete counters + no active jobs
   - Job re-enqueued

### Migration Tests

9. **Stuck site migration**
   - 105 stuck sites migrated
   - State inferred from filesystem
   - All coordinators triggered
   - Sites unstuck

10. **Dual-write period**
    - New jobs use new system
    - Old in-flight jobs still work
    - No conflicts

## Migration Plan

### Step 1: Schema Changes (Deploy to Production)

**File:** `migrations/add_pipeline_state_columns.sql`

```sql
-- Add new columns to sites table (all nullable for gradual migration)
ALTER TABLE sites ADD COLUMN current_stage VARCHAR;
ALTER TABLE sites ADD COLUMN started_at TIMESTAMP;
ALTER TABLE sites ADD COLUMN updated_at TIMESTAMP;

ALTER TABLE sites ADD COLUMN fetch_total INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN fetch_completed INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN fetch_failed INT DEFAULT 0;

ALTER TABLE sites ADD COLUMN ocr_total INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN ocr_completed INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN ocr_failed INT DEFAULT 0;

ALTER TABLE sites ADD COLUMN compilation_total INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN compilation_completed INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN compilation_failed INT DEFAULT 0;

ALTER TABLE sites ADD COLUMN extraction_total INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN extraction_completed INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN extraction_failed INT DEFAULT 0;

ALTER TABLE sites ADD COLUMN deploy_total INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN deploy_completed INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN deploy_failed INT DEFAULT 0;

ALTER TABLE sites ADD COLUMN coordinator_enqueued BOOLEAN DEFAULT FALSE;

ALTER TABLE sites ADD COLUMN last_error_stage VARCHAR;
ALTER TABLE sites ADD COLUMN last_error_message TEXT;
ALTER TABLE sites ADD COLUMN last_error_at TIMESTAMP;

-- Create index on current_stage for queries
CREATE INDEX idx_sites_current_stage ON sites(current_stage);

-- Create index on updated_at for reconciliation queries
CREATE INDEX idx_sites_updated_at ON sites(updated_at);
```

**Execution:**
```bash
psql $DATABASE_URL < migrations/add_pipeline_state_columns.sql
```

**Verification:**
```sql
-- Verify columns exist
\d sites

-- Verify indexes created
\di idx_sites_*
```

### Step 2: Migrate Stuck Sites

**File:** `scripts/migrate_stuck_sites.py`

```python
#!/usr/bin/env python3
"""Migrate 105 stuck sites from site_progress to sites table."""

from pathlib import Path
from clerk.db import civic_db_connection
from clerk.models import site_progress_table, sites_table
from clerk.queue import get_compilation_queue
from sqlalchemy import select, update

def count_txt_files(subdomain):
    """Count txt files on filesystem."""
    txt_dir = Path(f"../sites/{subdomain}/txt")
    if not txt_dir.exists():
        return 0
    return len(list(txt_dir.glob("**/*.txt")))

def count_pdf_files(subdomain):
    """Count PDF files on filesystem."""
    pdf_dir = Path(f"../sites/{subdomain}/pdfs")
    if not pdf_dir.exists():
        return 0
    return len(list(pdf_dir.glob("**/*.pdf")))

def migrate_stuck_sites():
    """Migrate stuck sites to new system."""

    with civic_db_connection() as conn:
        # Get all stuck sites from site_progress
        stuck = conn.execute(
            select(site_progress_table).where(
                site_progress_table.c.current_stage == 'ocr'
            )
        ).fetchall()

        print(f"Found {len(stuck)} stuck sites in OCR stage")

        migrated = 0
        for site_prog in stuck:
            subdomain = site_prog.subdomain

            # Infer actual state from filesystem
            txt_count = count_txt_files(subdomain)
            pdf_count = count_pdf_files(subdomain)

            # Conservative estimate of totals
            ocr_total = pdf_count if pdf_count > 0 else site_prog.stage_total
            if ocr_total == 0:
                ocr_total = 1  # avoid division by zero

            ocr_completed = txt_count
            ocr_failed = max(0, ocr_total - ocr_completed)

            # Update sites table
            conn.execute(
                update(sites_table).where(
                    sites_table.c.subdomain == subdomain
                ).values(
                    current_stage='ocr',
                    ocr_total=ocr_total,
                    ocr_completed=ocr_completed,
                    ocr_failed=ocr_failed,
                    coordinator_enqueued=False,
                    started_at=site_prog.started_at,
                    updated_at=site_prog.updated_at
                )
            )

            migrated += 1
            print(f"  {subdomain}: {ocr_completed}/{ocr_total} completed, {ocr_failed} failed")

        print(f"\nMigrated {migrated} sites")

def clear_rq_state():
    """Clear deferred coordinators and failed OCR jobs."""
    from clerk.queue import get_ocr_queue

    # Clear deferred coordinators
    comp_queue = get_compilation_queue()
    deferred = comp_queue.deferred_job_registry

    print(f"\nClearing {len(deferred)} deferred coordinators...")
    for job_id in deferred.get_job_ids():
        job = comp_queue.fetch_job(job_id)
        if job:
            job.cancel()
            job.delete()

    # Clear failed OCR jobs
    ocr_queue = get_ocr_queue()
    failed = ocr_queue.failed_job_registry

    print(f"Clearing {len(failed)} failed OCR jobs...")
    for job_id in failed.get_job_ids():
        job = ocr_queue.fetch_job(job_id)
        if job:
            job.delete()

    print("RQ cleanup complete")

if __name__ == "__main__":
    print("=" * 80)
    print("MIGRATION: Stuck Sites to New System")
    print("=" * 80)
    migrate_stuck_sites()
    clear_rq_state()
    print("\nMigration complete. Run reconciliation job to unstick sites.")
```

**Execution:**
```bash
python scripts/migrate_stuck_sites.py
```

**Expected output:**
```
Found 105 stuck sites in OCR stage
  rockisland-county.il: 0/0 completed, 0 failed
  mmasc.ca: 0/0 completed, 0 failed
  lake-county.fl: 2/2 completed, 0 failed
  ...
Migrated 105 sites

Clearing 82 deferred coordinators...
Clearing 2695 failed OCR jobs...
RQ cleanup complete

Migration complete. Run reconciliation job to unstick sites.
```

### Step 3: Deploy New Code

**Branch:** `pipeline-state-consolidation`

**Files changed:**
- `src/clerk/workers.py` - Update all job functions to use atomic counter pattern
- `src/clerk/queue_db.py` - Update helper functions to read from sites table
- `scripts/reconcile_pipeline.py` - New reconciliation job
- Tests for all of the above

**Deployment process:**
```bash
# 1. Merge PR to main
git checkout main
git pull

# 2. Deploy to production
# (your deployment process here - e.g., pip install --upgrade, restart workers)

# 3. Verify deployment
python -c "from clerk.workers import fetch_site_job; print('Import successful')"
```

**Backward compatibility during deployment:**
- New jobs: write to `sites` table columns
- Old in-flight jobs: may still write to `site_progress` (harmless, ignored)
- Migrated stuck sites: use new system
- Code handles both for 24 hours

### Step 4: Run Reconciliation

**Immediately after deployment:**

```bash
# Run reconciliation once manually
python scripts/reconcile_pipeline.py
```

**Expected outcome:**
- Detects ~105 migrated sites with `coordinator_enqueued=FALSE`
- For sites with `ocr_completed + ocr_failed == ocr_total`: enqueues coordinators
- Sites begin flowing through pipeline
- Monitor logs for coordinator execution

**Set up periodic reconciliation:**

```bash
# Add to cron (runs every 15 minutes)
*/15 * * * * cd /path/to/clerk && python scripts/reconcile_pipeline.py >> /var/log/clerk-reconcile.log 2>&1
```

### Step 5: Monitor & Verify

**Queries to run:**

```sql
-- How many sites in each stage?
SELECT current_stage, COUNT(*)
FROM sites
WHERE current_stage IS NOT NULL
GROUP BY current_stage;

-- Sites with high failure rates?
SELECT subdomain, ocr_total, ocr_completed, ocr_failed,
       ROUND(100.0 * ocr_failed / NULLIF(ocr_total, 0), 1) as failure_rate_pct
FROM sites
WHERE ocr_total > 0 AND ocr_failed > 0
ORDER BY failure_rate_pct DESC
LIMIT 20;

-- Sites stuck > 2 hours?
SELECT subdomain, current_stage, updated_at,
       EXTRACT(EPOCH FROM (NOW() - updated_at))/3600 as hours_stuck
FROM sites
WHERE current_stage != 'completed'
  AND updated_at < NOW() - INTERVAL '2 hours'
ORDER BY hours_stuck DESC;

-- Recently recovered sites (from reconciliation logs)
-- Check /var/log/clerk-reconcile.log
```

**Success criteria:**
- Stuck sites decrease over next few hours
- New sites progress smoothly through pipeline
- No duplicate coordinators (check RQ dashboard)
- Reconciliation logs show recoveries

### Step 6: Cleanup (After 24-48 Hours)

Once all in-flight jobs complete:

```sql
-- Verify site_progress not being written to
SELECT COUNT(*) FROM site_progress WHERE updated_at > NOW() - INTERVAL '24 hours';
-- Should be 0

-- Drop deprecated table
DROP TABLE site_progress;

-- Remove deprecated columns (optional, keep for backward compat)
-- ALTER TABLE sites DROP COLUMN status;
-- ALTER TABLE sites DROP COLUMN extraction_status;
-- ALTER TABLE sites DROP COLUMN last_updated;
```

**Rollback plan (if needed):**
- Revert code deployment
- Old system still works (site_progress table exists)
- New columns don't affect old code
- Can fix issues and redeploy

## Observability

### SQL Queries for Monitoring

```sql
-- Overall pipeline health
SELECT
    current_stage,
    COUNT(*) as site_count,
    AVG(EXTRACT(EPOCH FROM (NOW() - updated_at))/3600) as avg_hours_in_stage
FROM sites
WHERE current_stage != 'completed'
GROUP BY current_stage;

-- Sites with failures
SELECT
    subdomain,
    current_stage,
    ocr_total, ocr_completed, ocr_failed,
    compilation_failed,
    last_error_stage,
    last_error_message
FROM sites
WHERE ocr_failed > 0 OR compilation_failed > 0
ORDER BY updated_at DESC
LIMIT 50;

-- Throughput: completions per day
SELECT
    DATE(updated_at) as date,
    COUNT(*) as sites_completed
FROM sites
WHERE current_stage = 'completed'
  AND updated_at > NOW() - INTERVAL '7 days'
GROUP BY DATE(updated_at)
ORDER BY date DESC;

-- Success rates by stage
SELECT
    'ocr' as stage,
    SUM(ocr_total) as total_jobs,
    SUM(ocr_completed) as succeeded,
    SUM(ocr_failed) as failed,
    ROUND(100.0 * SUM(ocr_completed) / NULLIF(SUM(ocr_total), 0), 1) as success_rate
FROM sites
WHERE ocr_total > 0
UNION ALL
SELECT
    'compilation',
    SUM(compilation_total),
    SUM(compilation_completed),
    SUM(compilation_failed),
    ROUND(100.0 * SUM(compilation_completed) / NULLIF(SUM(compilation_total), 0), 1)
FROM sites
WHERE compilation_total > 0;
```

### Logs to Monitor

- **Reconciliation logs:** `/var/log/clerk-reconcile.log`
  - Look for: "Recovering site X", "Enqueueing coordinator for Y"
  - Alert on: same site recovered multiple times (indicates bug)

- **Sentry/Bugsink:** Errors from pipeline jobs
  - Fingerprinted by PR #84
  - Group by: `pdf-failed-to-read`, `pdf-failed-to-process`, etc.

- **Worker logs:** Job execution
  - Look for: "ocr_completed", "coordinator_started", etc.

### Metrics to Track (Future Enhancement)

If you add metrics infrastructure:
- `pipeline_stage_duration_seconds{stage="ocr"}` - histogram
- `pipeline_stage_success_rate{stage="ocr"}` - gauge
- `pipeline_stuck_sites_count` - gauge
- `reconciliation_recoveries_total` - counter

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| **Migration breaks in-flight jobs** | Gradual migration: old jobs still work, new columns don't affect them |
| **Coordinator race condition creates duplicates** | Database-level constraint in WHERE clause prevents it |
| **Reconciliation creates duplicate work** | Check `coordinator_enqueued` flag before enqueueing |
| **All OCR fails, site never completes** | Coordinator sanity check fails, logs error for manual intervention |
| **Counter increments lost** | Database transaction ensures atomicity |
| **Filesystem and DB out of sync** | Reconciliation infers state from filesystem (source of truth) |

## Success Metrics

**Immediate (first 24 hours):**
- ✅ 105 stuck sites unstuck and progressing
- ✅ 0 deferred coordinators in RQ
- ✅ 0 failed OCR jobs blocking coordinators
- ✅ New sites complete pipeline end-to-end

**Ongoing:**
- ✅ <1% of sites stuck >2 hours (detected and auto-recovered by reconciliation)
- ✅ Single SQL query shows accurate pipeline state
- ✅ No manual intervention needed for transient failures
- ✅ Sentry shows detailed error patterns, but not blocking issues

## Future Enhancements

**Not in scope for initial implementation:**

1. **Metrics dashboard** - Real-time graphs of pipeline health
2. **Retry logic** - Automatic retry of failed stages with backoff
3. **Parallel extraction** - Multiple extraction jobs per site (would use same counter pattern)
4. **Historical tracking** - Keep history of past runs (currently just latest)
5. **Admin UI** - Web interface to view pipeline state, manually trigger stages

**These can be added incrementally using the same counter pattern.**

---

## Appendix: Key Files

**Schema:**
- `src/clerk/models.py` - Table definitions
- `migrations/add_pipeline_state_columns.sql` - Schema changes

**Core Logic:**
- `src/clerk/workers.py` - Job implementations (fetch, OCR, compilation, etc.)
- `src/clerk/queue_db.py` - Helper functions for state updates

**Recovery:**
- `scripts/reconcile_pipeline.py` - Reconciliation job
- `scripts/migrate_stuck_sites.py` - One-time migration

**Monitoring:**
- `docs/plans/pipeline-queries.sql` - Useful SQL queries
- `/var/log/clerk-reconcile.log` - Reconciliation output

## Questions/Clarifications

For questions about this design, contact: (your contact info)

**Design approved by:** Phil Dini
**Implementation tracking:** (create GitHub issue/project)
