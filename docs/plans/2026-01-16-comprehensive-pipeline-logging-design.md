# Comprehensive Pipeline Logging Design

**Date:** 2026-01-16
**Status:** Approved
**Goal:** Enable complete pipeline visibility in Grafana/Loki by filtering on subdomain field, with full tracing via run_id

## Problem Statement

Current logging lacks:
- **Entry/exit visibility** - Can't see when pipeline runs start/end or track stage transitions
- **Error context** - Errors appear but can't trace back to which file/page/stage failed
- **Cross-job correlation** - Can't connect related jobs (fetch → OCR → compilation → deploy) for the same subdomain

## Requirements

User needs:
1. **Single query shows everything** - Filter by `subdomain=foo` and see entire pipeline flow with stage transitions and errors
2. **Trace with run_id** - Follow specific pipeline execution from start to finish, even with concurrent runs
3. **Dashboard support** - Build Grafana dashboards showing:
   - Success/failure rates by stage
   - Performance metrics (durations, bottlenecks)
   - Volume tracking (pages/PDFs processed)
   - Error analysis (grouped by type, stage, subdomain)

## Design

### 1. Core Architecture

#### Run ID Generation & Propagation

**Format:** `{subdomain}_{timestamp}_{random}` (e.g., `alameda_20260116_abc123`)
- Human-readable and sortable
- Unique per pipeline execution
- Generated in `enqueue_job()` at pipeline entry

**Propagation Flow:**
```
enqueue_job() [generates run_id]
  ↓
fetch_site_job(subdomain, run_id)
  ↓
├─ ocr_page_job(subdomain, pdf_path, backend, run_id) [×N]
├─ ocr_page_job(subdomain, pdf_path, backend, run_id) [×N]
└─ ocr_page_job(subdomain, pdf_path, backend, run_id) [×N]
  ↓
ocr_complete_coordinator(subdomain, run_id)
  ↓
├─ db_compilation_job(subdomain, run_id)
└─ extraction_job(subdomain, run_id)
  ↓
deploy_job(subdomain, run_id)
```

All child jobs receive `run_id` as parameter, ensuring complete traceability.

#### Structured Logging Enhancement

Extend `output.log()` signature:

```python
def log(message: str, subdomain: str | None = None, level: str = "info",
        run_id: str | None = None, stage: str | None = None,
        job_id: str | None = None, parent_job_id: str | None = None, **kwargs)
```

**Standard Fields (on all logs):**
- `subdomain` - Site identifier (existing)
- `run_id` - Pipeline execution identifier (NEW)
- `stage` - Current pipeline stage: fetch/ocr/compilation/extraction/deploy (NEW)
- `job_id` - Current RQ job ID (NEW)
- `parent_job_id` - Parent RQ job ID for spawned jobs (NEW)
- `level` - Log level: info/warning/error (existing)

These fields flow automatically to Loki as structured data via existing `JsonFormatter`.

### 2. Stage Milestone Logging

#### Explicit Stage Boundaries

Each stage logs start/end milestones with standardized naming:

```python
# Stage started
output_log("fetch_started", subdomain=subdomain, run_id=run_id, stage="fetch")

# Stage completed
output_log("fetch_completed", subdomain=subdomain, run_id=run_id, stage="fetch",
           duration_seconds=120.5, total_pdfs=47)

# Stage failed
output_log("fetch_failed", subdomain=subdomain, run_id=run_id, stage="fetch",
           level="error", error_type="NetworkError", duration_seconds=15.2)
```

**Event Naming Pattern:** `{stage}_{started|completed|failed}`

**Stages:**
- `fetch` - Downloading PDFs
- `ocr` - OCR processing (individual page jobs + coordinator)
- `compilation` - Database compilation
- `extraction` - Entity/vote extraction
- `deploy` - Deploying to target

#### Stage Field on All Logs

Every log entry automatically includes its stage context:
- `fetch_site_job` → `stage="fetch"`
- `ocr_page_job` → `stage="ocr"`
- `ocr_complete_coordinator` → `stage="ocr"`
- `db_compilation_job` → `stage="compilation"`
- `extraction_job` → `stage="extraction"`
- `deploy_job` → `stage="deploy"`

This enables powerful Grafana queries:
- Show all logs for `run_id=X` (complete pipeline view)
- Show logs where `stage=ocr AND level=error` (OCR failures only)
- Show `*_started` and `*_completed` events (stage transition timeline)

#### Helper Function

Reduce boilerplate with stage context helper:

```python
def log_with_context(message, subdomain, run_id, stage, **kwargs):
    """Log with automatic run_id, stage, job_id context."""
    from rq import get_current_job

    job = get_current_job()
    job_id = job.id if job else None
    parent_job_id = getattr(job, 'dependency_id', None) if job else None

    output_log(message, subdomain=subdomain, run_id=run_id, stage=stage,
               job_id=job_id, parent_job_id=parent_job_id, **kwargs)
```

### 3. Rich Error Context

#### Error Logging Standard

Capture comprehensive context in single log entry:

```python
try:
    # Work happens here
except Exception as e:
    log_with_context(
        f"OCR failed: {e}",
        subdomain=subdomain,
        run_id=run_id,
        stage="ocr",
        level="error",
        # File context
        pdf_path=str(pdf_path),
        pdf_name=pdf_path.name,
        page_number=page_num,
        backend=ocr_backend,
        # Error details
        error_type=type(e).__name__,
        error_message=str(e),
        traceback=traceback.format_exc()
    )
    raise  # Re-raise so RQ marks job as failed
```

#### Context Fields by Stage

**Fetch stage:**
- Config: `scraper_type`, `all_years`, `all_agendas`
- Success: `total_pdfs`, `duration_seconds`
- Error: `url`, `http_status`, `error_type`, `traceback`

**OCR stage:**
- Config: `backend` (tesseract/vision)
- Success: `pdf_name`, `page_count`, `duration_seconds`
- Error: `pdf_path`, `pdf_name`, `page_number`, `backend`, `error_type`, `traceback`

**Compilation stage:**
- Config: `table_name` (minutes/agendas), `extract_entities`, `ignore_cache`
- Success: `total_pages`, `cache_hits`, `cache_misses`, `duration_seconds`
- Error: `txt_dir`, `table_name`, `page_count`, `error_type`, `traceback`

**Extraction stage:**
- Config: `extract_entities`, `ignore_cache`
- Success: `total_pages`, `entities_extracted`, `votes_extracted`, `duration_seconds`
- Error: `page_file`, `extraction_type` (entities/votes), `error_type`, `traceback`

**Deploy stage:**
- Config: `deploy_target`, `database_path`
- Success: `plugin_count`, `duration_seconds`
- Error: `plugin_name`, `deploy_target`, `error_type`, `traceback`

### 4. Metrics & Dashboard Support

#### Structured Fields for Queries

**Success/Failure Tracking:**
- `status` field: "started", "completed", "failed"
- Milestone logs include status automatically from event name
- Error logs have `level="error"` + inferred `status="failed"`

**Performance Metrics:**
- `duration_seconds` - Total duration for completed stages
- `start_time`, `end_time` - ISO timestamps for stage boundaries
- Per-operation timing: `ocr_duration_per_page`, `fetch_duration_per_pdf`

**Volume Tracking:**
- Counts on milestone logs: `total_pdfs`, `total_pages`, `job_count`
- Cache metrics: `cache_hits`, `cache_misses`
- Extraction counts: `entities_extracted`, `votes_extracted`
- `files_processed` - Generic count field

**Error Analysis:**
- `error_type` - Exception class name (ValueError, NetworkError, etc.)
- `error_category` - High-level category (network, ocr_failed, compilation_error)
- `retry_count` - Number of retries (if retry logic added)

#### Example Grafana Queries

**Success rate by stage (last 24h):**
```
count(status="completed" AND stage="ocr") / count(stage="ocr")
```

**Average OCR duration per page:**
```
avg(duration_seconds) WHERE stage="ocr" AND message="Completed ocr_page_job"
```

**Total pages processed today:**
```
sum(total_pages) WHERE message="fetch_completed"
```

**Most common errors by stage:**
```
count(*) WHERE level="error" GROUP BY stage, error_type
```

**Active runs right now:**
```
count(DISTINCT run_id) WHERE message LIKE "%_started"
  AND timestamp > now() - 1h
  AND NOT EXISTS(message LIKE "%_completed" OR message LIKE "%_failed")
```

**Subdomain performance ranking:**
```
avg(duration_seconds) WHERE message="fetch_completed"
  GROUP BY subdomain ORDER BY duration_seconds DESC
```

#### Standardized Field Naming

All logs use consistent naming conventions:
- **Time:** `duration_seconds`, `start_time`, `end_time`
- **Counts:** `total_*`, `*_count` (total_pdfs, job_count, error_count)
- **Status:** `status`, `level` (completed/failed, info/error)
- **Identity:** `run_id`, `subdomain`, `stage`, `job_id`, `parent_job_id`
- **Files:** `*_path`, `*_name` (pdf_path, pdf_name)

## Implementation Plan

### Changes Required

#### 1. Modify `enqueue_job()` in queue.py

- Generate `run_id` using format: `{subdomain}_{timestamp}_{random_suffix}`
- Add to signature: `enqueue_job(job_type, site_id, priority="normal", run_id=None, **kwargs)`
- Auto-generate if not provided (supports testing with explicit run_ids)
- Pass `run_id` as parameter to all job functions

```python
import time
import random
import string

def enqueue_job(job_type, site_id, priority="normal", run_id=None, **kwargs):
    """Enqueue a job to the appropriate queue.

    Args:
        job_type: Type of job (fetch-site, ocr-page, etc.)
        site_id: Site subdomain
        priority: 'high', 'normal', or 'low'
        run_id: Optional run ID (auto-generated if not provided)
        **kwargs: Additional job parameters
    """
    # Generate run_id if not provided
    if run_id is None:
        timestamp = int(time.time())
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        run_id = f"{site_id}_{timestamp}_{random_suffix}"

    # Pass run_id to job function
    kwargs['run_id'] = run_id

    # ... rest of existing enqueue logic
```

#### 2. Update `output.log()` in output.py

- Add parameters: `run_id`, `stage`, `job_id`, `parent_job_id`
- Include in extra dict for structured logging
- All fields flow to Loki automatically via existing JsonFormatter

```python
def log(message: str, subdomain: str | None = None, level: str = "info",
        run_id: str | None = None, stage: str | None = None,
        job_id: str | None = None, parent_job_id: str | None = None, **kwargs):
    """Unified logging + click output.

    Args:
        message: The message to log/display
        subdomain: Optional subdomain prefix (uses default if not provided)
        level: Log level - "debug", "info", "warning", "error"
        run_id: Pipeline run identifier
        stage: Pipeline stage (fetch/ocr/compilation/extraction/deploy)
        job_id: Current RQ job ID
        parent_job_id: Parent RQ job ID (for spawned jobs)
        **kwargs: Additional structured fields for logging
    """
    sub = subdomain or _default_subdomain

    # Build extra dict for structured logging fields
    extra: dict = {}
    if sub:
        extra["subdomain"] = sub
    if run_id:
        extra["run_id"] = run_id
    if stage:
        extra["stage"] = stage
    if job_id:
        extra["job_id"] = job_id
    if parent_job_id:
        extra["parent_job_id"] = parent_job_id
    if kwargs:
        extra.update(kwargs)

    # Log to Python logging with extra fields
    log_func = getattr(logger, level, logger.info)
    log_func(message, extra=extra)

    # Click output (unless quiet)
    if not _quiet:
        prefix = click.style(f"{sub}: ", fg="cyan") if sub else ""
        click.echo(prefix + message)
```

#### 3. Update all worker functions in workers.py

**Add helper function:**

```python
import traceback
from rq import get_current_job

def log_with_context(message, subdomain, run_id, stage, **kwargs):
    """Log with automatic run_id, stage, job_id context."""
    job = get_current_job()
    job_id = job.id if job else None

    # Get parent_job_id if this job has a dependency
    parent_job_id = None
    if job and hasattr(job, 'dependency_id'):
        parent_job_id = job.dependency_id

    output_log(
        message,
        subdomain=subdomain,
        run_id=run_id,
        stage=stage,
        job_id=job_id,
        parent_job_id=parent_job_id,
        **kwargs
    )
```

**Update each worker function:**

1. Add `run_id` parameter to signature
2. Add milestone logs at entry/exit
3. Add rich error context in exception handlers
4. Pass `run_id` to all spawned child jobs
5. Replace `output_log()` calls with `log_with_context()`

**Example for fetch_site_job:**

```python
def fetch_site_job(subdomain, run_id, all_years=False, all_agendas=False):
    """RQ job: Fetch PDFs for a site then spawn OCR jobs."""
    stage = "fetch"
    start_time = time.time()

    # Milestone: started
    log_with_context(
        "fetch_started",
        subdomain=subdomain,
        run_id=run_id,
        stage=stage,
        all_years=all_years,
        all_agendas=all_agendas
    )

    try:
        # ... existing fetch logic ...

        # Spawn OCR jobs with run_id
        for pdf_path in pdf_files:
            job = ocr_queue.enqueue(
                ocr_page_job,
                subdomain=subdomain,
                pdf_path=str(pdf_path),
                backend=ocr_backend,
                run_id=run_id,  # NEW: pass run_id
                job_timeout="10m",
                description=f"OCR ({ocr_backend}): {pdf_path.name}",
            )
            # ... track job ...

        # Milestone: completed
        duration = time.time() - start_time
        log_with_context(
            "fetch_completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            duration_seconds=round(duration, 2),
            total_pdfs=len(pdf_files)
        )

    except Exception as e:
        duration = time.time() - start_time
        log_with_context(
            f"fetch_failed: {e}",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            level="error",
            duration_seconds=round(duration, 2),
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc()
        )
        raise
```

**Apply similar pattern to:**
- `ocr_page_job(subdomain, pdf_path, backend, run_id)`
- `ocr_complete_coordinator(subdomain, run_id)`
- `db_compilation_job(subdomain, run_id, ...)`
- `extraction_job(subdomain, run_id, ...)`
- `deploy_job(subdomain, run_id, ...)`

#### 4. Update CLI commands in cli.py

No changes needed to auto-enqueue logic - `enqueue_job()` handles run_id generation.

For manual testing/debugging, could optionally add `--run-id` flag:

```python
@cli.command()
@click.option("--subdomain", required=True)
@click.option("--run-id", help="Optional run ID for tracking (auto-generated if not provided)")
def update(subdomain, run_id):
    """Enqueue a fetch job."""
    enqueue_job("fetch-site", subdomain, priority="high", run_id=run_id)
```

#### 5. Update queue_db.py tracking (Optional)

Add `run_id` column to jobs table for PostgreSQL tracking:

```python
def track_job(conn, job_id, subdomain, job_type, stage, run_id=None):
    """Track a job in PostgreSQL."""
    # ... existing logic ...
    # Add run_id to insert if provided
```

This enables querying job history by run_id in PostgreSQL (complementary to Loki logs).

### Backward Compatibility

- Make `run_id` optional in all signatures (defaults to None, auto-generated)
- Existing logs without run_id still work (just missing that field)
- Gradual rollout: deploy and start logging run_ids without breaking existing jobs
- Old jobs in queue without run_id will auto-generate when they run

### Testing Strategy

**Unit Tests:**
- Mock `output_log`, verify run_id flows through all worker functions
- Test run_id generation format and uniqueness
- Verify log_with_context includes job_id and parent_job_id

**Integration Tests:**
- Enqueue job, verify all logs have same run_id
- Verify parent_job_id links child jobs to parent
- Test error scenarios include full context

**Grafana Validation:**
- Query by run_id, verify complete pipeline visible
- Test all example queries from Section 4
- Build sample dashboards to verify metrics fields work

## Success Metrics

After implementation, you should be able to:

1. **Single Query View:** Filter Loki by `subdomain=alameda` and see:
   - All pipeline runs with start/end times
   - Stage transitions (fetch → OCR → compilation → deploy)
   - Errors with full context (which file, which page, which stage)

2. **Run Tracing:** Filter by `run_id=alameda_1737072000_abc123` and see:
   - Complete timeline from fetch_started to deploy_completed
   - All child jobs (50 OCR jobs) linked via parent_job_id
   - Any failures with exact file/page context

3. **Dashboards Working:**
   - Success rate by stage graph shows real-time health
   - Performance panel shows p50/p95 durations per stage
   - Volume panel shows pages/PDFs processed per day
   - Error panel shows top error types grouped by stage

4. **Debug Workflow:** When error appears in Grafana:
   - Click error log → see run_id, stage, file context
   - Query by run_id → see what happened before error
   - Query by parent_job_id → see which fetch spawned the failed OCR job
   - All information needed to reproduce and fix
