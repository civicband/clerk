# Comprehensive Pipeline Logging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable complete pipeline visibility in Grafana/Loki with run_id tracing, stage milestones, rich error context, and dashboard metrics support.

**Architecture:** Generate unique run_id per pipeline execution in `enqueue_job()`, propagate through all worker jobs, enhance `output.log()` with structured fields (run_id, stage, job_id, parent_job_id), add explicit stage milestone logging (started/completed/failed), and include rich error context with file/page details.

**Tech Stack:** Python 3.12, RQ (Redis Queue), Python logging, Loki (for log aggregation), existing output.log() infrastructure

---

## Task 1: Enhance output.log() with Structured Fields

**Files:**
- Modify: `src/clerk/output.py:30-59`
- Test: `tests/test_output.py` (create if doesn't exist)

**Step 1: Write the failing test**

Create `tests/test_output.py`:

```python
import pytest
from clerk.output import log, configure


def test_log_includes_run_id_in_extra(mocker):
    """Test that run_id is passed to logger.info as extra field."""
    mock_logger = mocker.patch('clerk.output.logger')

    log("test message", subdomain="test", run_id="test_123_abc")

    mock_logger.info.assert_called_once()
    args, kwargs = mock_logger.info.call_args
    assert kwargs['extra']['run_id'] == "test_123_abc"


def test_log_includes_stage_in_extra(mocker):
    """Test that stage is passed to logger.info as extra field."""
    mock_logger = mocker.patch('clerk.output.logger')

    log("test message", subdomain="test", stage="fetch")

    mock_logger.info.assert_called_once()
    args, kwargs = mock_logger.info.call_args
    assert kwargs['extra']['stage'] == "fetch"


def test_log_includes_job_ids_in_extra(mocker):
    """Test that job_id and parent_job_id are passed as extra fields."""
    mock_logger = mocker.patch('clerk.output.logger')

    log("test message", subdomain="test", job_id="job-123", parent_job_id="job-456")

    mock_logger.info.assert_called_once()
    args, kwargs = mock_logger.info.call_args
    assert kwargs['extra']['job_id'] == "job-123"
    assert kwargs['extra']['parent_job_id'] == "job-456"


def test_log_excludes_none_values(mocker):
    """Test that None values are not included in extra dict."""
    mock_logger = mocker.patch('clerk.output.logger')

    log("test message", subdomain="test", run_id=None, stage=None)

    mock_logger.info.assert_called_once()
    args, kwargs = mock_logger.info.call_args
    extra = kwargs['extra']
    assert 'run_id' not in extra
    assert 'stage' not in extra
```

**Step 2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_output.py -v`

Expected: FAIL with "TypeError: log() got an unexpected keyword argument 'run_id'"

**Step 3: Write minimal implementation**

Modify `src/clerk/output.py`:

```python
def log(message: str, subdomain: str | None = None, level: str = "info",
        run_id: str | None = None, stage: str | None = None,
        job_id: str | None = None, parent_job_id: str | None = None, **kwargs):
    """Unified logging + click output.

    - Always logs to Python logging (-> Loki if configured)
    - click.echo with colored output unless --quiet flag is set

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

**Step 4: Run test to verify it passes**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_output.py -v`

Expected: PASS (4 tests passing)

**Step 5: Commit**

```bash
git add src/clerk/output.py tests/test_output.py
git commit -m "feat: add structured logging fields to output.log

Add run_id, stage, job_id, and parent_job_id parameters to log() function.
These fields are passed as extra data to Python logger for structured logging.

- run_id: Pipeline execution identifier
- stage: Current pipeline stage (fetch/ocr/compilation/extraction/deploy)
- job_id: Current RQ job ID
- parent_job_id: Parent RQ job ID for spawned jobs

All fields are optional and only included in logs if provided."
```

---

## Task 2: Add run_id Generation to enqueue_job()

**Files:**
- Modify: `src/clerk/queue.py:80-124`
- Test: `tests/test_queue.py`

**Step 1: Write the failing test**

Add to `tests/test_queue.py`:

```python
def test_enqueue_job_generates_run_id(mocker):
    """Test that enqueue_job generates run_id if not provided."""
    mock_queue = mocker.MagicMock()
    mock_queue.enqueue.return_value = mocker.MagicMock(id="job-123")
    mocker.patch('clerk.queue.get_fetch_queue', return_value=mock_queue)

    from clerk.queue import enqueue_job

    job_id = enqueue_job("fetch-site", "test.civic.band", priority="normal")

    # Verify enqueue was called with run_id in kwargs
    call_kwargs = mock_queue.enqueue.call_args[1]
    assert 'run_id' in call_kwargs

    # Verify format: subdomain_timestamp_random
    run_id = call_kwargs['run_id']
    parts = run_id.split('_')
    assert parts[0] == "test.civic.band"
    assert parts[1].isdigit()  # timestamp
    assert len(parts[2]) == 6  # random suffix


def test_enqueue_job_uses_provided_run_id(mocker):
    """Test that enqueue_job uses run_id if provided."""
    mock_queue = mocker.MagicMock()
    mock_queue.enqueue.return_value = mocker.MagicMock(id="job-123")
    mocker.patch('clerk.queue.get_fetch_queue', return_value=mock_queue)

    from clerk.queue import enqueue_job

    custom_run_id = "custom_12345_xyz123"
    job_id = enqueue_job("fetch-site", "test.civic.band", priority="normal", run_id=custom_run_id)

    # Verify enqueue was called with custom run_id
    call_kwargs = mock_queue.enqueue.call_args[1]
    assert call_kwargs['run_id'] == custom_run_id


def test_run_id_format_is_unique(mocker):
    """Test that generated run_ids are unique."""
    mock_queue = mocker.MagicMock()
    mock_queue.enqueue.return_value = mocker.MagicMock(id="job-123")
    mocker.patch('clerk.queue.get_fetch_queue', return_value=mock_queue)

    from clerk.queue import enqueue_job

    # Generate two run_ids
    enqueue_job("fetch-site", "test.civic.band", priority="normal")
    run_id_1 = mock_queue.enqueue.call_args[1]['run_id']

    enqueue_job("fetch-site", "test.civic.band", priority="normal")
    run_id_2 = mock_queue.enqueue.call_args[1]['run_id']

    # Should be different
    assert run_id_1 != run_id_2
```

**Step 2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_queue.py::test_enqueue_job_generates_run_id -v`

Expected: FAIL with "KeyError: 'run_id'" or similar

**Step 3: Write minimal implementation**

Modify `src/clerk/queue.py`:

```python
import os
import sys
import threading
import time
import random
import string

import redis
from rq import Queue

# ... existing code ...

def enqueue_job(job_type, site_id, priority="normal", run_id=None, **kwargs):
    """Enqueue a job to the appropriate queue.

    Args:
        job_type: Type of job (fetch-site, ocr-page, etc.)
        site_id: Site subdomain
        priority: 'high', 'normal', or 'low'
        run_id: Optional run ID (auto-generated if not provided)
        **kwargs: Additional job parameters

    Returns:
        RQ job ID
    """
    # Generate run_id if not provided
    if run_id is None:
        timestamp = int(time.time())
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        run_id = f"{site_id}_{timestamp}_{random_suffix}"

    # Pass run_id to job function
    kwargs['run_id'] = run_id

    # Determine which queue to use
    if priority == "high":
        queue = get_high_queue()
    else:
        # Route to stage-specific queue based on job type
        stage = job_type.split("-")[0]  # fetch-site → fetch
        queue_map = {
            "fetch": get_fetch_queue(),
            "ocr": get_ocr_queue(),
            "compilation": get_compilation_queue(),
            "extraction": get_extraction_queue(),
            "deploy": get_deploy_queue(),
        }
        queue = queue_map.get(stage, get_fetch_queue())

    # Import worker function based on job type
    from . import workers

    job_function_map = {
        "fetch-site": workers.fetch_site_job,
        "ocr-page": workers.ocr_page_job,
        "extract-site": workers.extraction_job,
        "deploy-site": workers.deploy_job,
    }

    job_function = job_function_map.get(job_type)
    if not job_function:
        raise ValueError(f"Unknown job type: {job_type}")

    # Enqueue the job
    job = queue.enqueue(job_function, site_id, **kwargs)
    return job.id
```

**Step 4: Run test to verify it passes**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_queue.py::test_enqueue_job_generates_run_id tests/test_queue.py::test_enqueue_job_uses_provided_run_id tests/test_queue.py::test_run_id_format_is_unique -v`

Expected: PASS (3 new tests passing)

**Step 5: Commit**

```bash
git add src/clerk/queue.py tests/test_queue.py
git commit -m "feat: add run_id generation to enqueue_job

Generate unique run_id for each pipeline execution using format:
{subdomain}_{timestamp}_{random}

- Auto-generates if not provided
- Accepts optional run_id parameter for testing/debugging
- Passes run_id to all enqueued job functions via kwargs
- Format is human-readable and sortable by timestamp"
```

---

## Task 3: Add log_with_context Helper to workers.py

**Files:**
- Modify: `src/clerk/workers.py:1-18`
- Test: `tests/test_workers.py`

**Step 1: Write the failing test**

Add to `tests/test_workers.py`:

```python
def test_log_with_context_includes_job_context(mocker):
    """Test that log_with_context extracts job_id and parent_job_id from RQ context."""
    from clerk.workers import log_with_context

    # Mock get_current_job to return a job with ID and dependency
    mock_job = mocker.MagicMock()
    mock_job.id = "job-123"
    mock_job.dependency_id = "job-456"
    mocker.patch('clerk.workers.get_current_job', return_value=mock_job)

    # Mock output_log
    mock_output_log = mocker.patch('clerk.workers.output_log')

    log_with_context(
        "test message",
        subdomain="test.civic.band",
        run_id="test_123_abc",
        stage="fetch"
    )

    # Verify output_log was called with job context
    mock_output_log.assert_called_once_with(
        "test message",
        subdomain="test.civic.band",
        run_id="test_123_abc",
        stage="fetch",
        job_id="job-123",
        parent_job_id="job-456"
    )


def test_log_with_context_handles_no_job(mocker):
    """Test that log_with_context works when no RQ job context exists."""
    from clerk.workers import log_with_context

    # Mock get_current_job to return None (no job context)
    mocker.patch('clerk.workers.get_current_job', return_value=None)

    # Mock output_log
    mock_output_log = mocker.patch('clerk.workers.output_log')

    log_with_context(
        "test message",
        subdomain="test.civic.band",
        run_id="test_123_abc",
        stage="fetch"
    )

    # Verify output_log was called with None for job fields
    mock_output_log.assert_called_once_with(
        "test message",
        subdomain="test.civic.band",
        run_id="test_123_abc",
        stage="fetch",
        job_id=None,
        parent_job_id=None
    )


def test_log_with_context_passes_extra_kwargs(mocker):
    """Test that log_with_context passes through additional kwargs."""
    from clerk.workers import log_with_context

    mocker.patch('clerk.workers.get_current_job', return_value=None)
    mock_output_log = mocker.patch('clerk.workers.output_log')

    log_with_context(
        "test message",
        subdomain="test.civic.band",
        run_id="test_123_abc",
        stage="fetch",
        total_pdfs=47,
        duration_seconds=120.5
    )

    # Verify extra kwargs were passed through
    call_kwargs = mock_output_log.call_args[1]
    assert call_kwargs['total_pdfs'] == 47
    assert call_kwargs['duration_seconds'] == 120.5
```

**Step 2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_workers.py::test_log_with_context_includes_job_context -v`

Expected: FAIL with "ImportError: cannot import name 'log_with_context'" or "AttributeError"

**Step 3: Write minimal implementation**

Add to top of `src/clerk/workers.py` (after imports):

```python
"""RQ worker job functions."""

import logging
import os
import time
import traceback
from pathlib import Path

from rq import get_current_job

from .db import civic_db_connection, get_site_by_subdomain
from .output import log as output_log
from .queue_db import (
    create_site_progress,
    increment_stage_progress,
    track_job,
    update_site_progress,
)

logger = logging.getLogger(__name__)


def log_with_context(message, subdomain, run_id, stage, **kwargs):
    """Log with automatic run_id, stage, job_id context.

    Extracts job_id and parent_job_id from RQ job context automatically.

    Args:
        message: Log message
        subdomain: Site subdomain
        run_id: Pipeline run identifier
        stage: Pipeline stage (fetch/ocr/compilation/extraction/deploy)
        **kwargs: Additional structured fields
    """
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

**Step 4: Run test to verify it passes**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_workers.py::test_log_with_context_includes_job_context tests/test_workers.py::test_log_with_context_handles_no_job tests/test_workers.py::test_log_with_context_passes_extra_kwargs -v`

Expected: PASS (3 tests passing)

**Step 5: Commit**

```bash
git add src/clerk/workers.py tests/test_workers.py
git commit -m "feat: add log_with_context helper for workers

Add helper function that automatically extracts job_id and parent_job_id
from RQ job context and passes to output_log().

Benefits:
- Reduces boilerplate in worker functions
- Consistent job context across all logs
- Handles missing job context gracefully (CLI/test execution)"
```

---

## Task 4: Update fetch_site_job with run_id and Milestones

**Files:**
- Modify: `src/clerk/workers.py:20-180`
- Test: `tests/test_workers.py`

**Step 1: Write the failing test**

Add to `tests/test_workers.py`:

```python
def test_fetch_site_job_accepts_run_id_parameter(mocker):
    """Test that fetch_site_job accepts run_id parameter."""
    from clerk.workers import fetch_site_job

    # Mock all dependencies
    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.workers.get_site_by_subdomain', return_value={'subdomain': 'test', 'scraper': 'test'})
    mocker.patch('clerk.workers.create_site_progress')
    mocker.patch('clerk.workers.get_fetcher')
    mocker.patch('clerk.workers.fetch_internal')
    mocker.patch('clerk.workers.get_ocr_queue')
    mocker.patch('clerk.workers.get_compilation_queue')
    mock_log = mocker.patch('clerk.workers.log_with_context')

    # Should not raise TypeError
    fetch_site_job("test.civic.band", run_id="test_123_abc")

    # Verify log_with_context was called with run_id
    assert any(
        call[1]['run_id'] == "test_123_abc"
        for call in mock_log.call_args_list
    )


def test_fetch_site_job_logs_fetch_started_milestone(mocker):
    """Test that fetch_site_job logs fetch_started milestone."""
    from clerk.workers import fetch_site_job

    # Mock dependencies
    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.workers.get_site_by_subdomain', return_value={'subdomain': 'test', 'scraper': 'test'})
    mocker.patch('clerk.workers.create_site_progress')
    mocker.patch('clerk.workers.get_fetcher')
    mocker.patch('clerk.workers.fetch_internal')
    mocker.patch('clerk.workers.get_ocr_queue')
    mocker.patch('clerk.workers.get_compilation_queue')
    mock_log = mocker.patch('clerk.workers.log_with_context')

    fetch_site_job("test.civic.band", run_id="test_123_abc")

    # Verify fetch_started was logged
    started_calls = [
        call for call in mock_log.call_args_list
        if call[0][0] == "fetch_started"
    ]
    assert len(started_calls) == 1

    # Verify it has stage="fetch"
    assert started_calls[0][1]['stage'] == "fetch"


def test_fetch_site_job_logs_fetch_completed_with_metrics(mocker):
    """Test that fetch_site_job logs fetch_completed with duration and count."""
    from clerk.workers import fetch_site_job

    # Mock dependencies
    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.workers.get_site_by_subdomain', return_value={'subdomain': 'test', 'scraper': 'test'})
    mocker.patch('clerk.workers.create_site_progress')
    mocker.patch('clerk.workers.get_fetcher')
    mocker.patch('clerk.workers.fetch_internal')
    mocker.patch('clerk.workers.Path')  # Mock Path to return no PDFs
    mocker.patch('clerk.workers.get_ocr_queue')
    mocker.patch('clerk.workers.get_compilation_queue')
    mock_log = mocker.patch('clerk.workers.log_with_context')

    fetch_site_job("test.civic.band", run_id="test_123_abc")

    # Verify fetch_completed was logged
    completed_calls = [
        call for call in mock_log.call_args_list
        if call[0][0] == "fetch_completed"
    ]
    assert len(completed_calls) == 1

    # Verify it has duration_seconds and total_pdfs
    call_kwargs = completed_calls[0][1]
    assert 'duration_seconds' in call_kwargs
    assert 'total_pdfs' in call_kwargs


def test_fetch_site_job_passes_run_id_to_ocr_jobs(mocker):
    """Test that fetch_site_job passes run_id to spawned OCR jobs."""
    from clerk.workers import fetch_site_job

    # Mock dependencies
    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.workers.get_site_by_subdomain', return_value={'subdomain': 'test', 'scraper': 'test'})
    mocker.patch('clerk.workers.create_site_progress')
    mocker.patch('clerk.workers.update_site_progress')
    mocker.patch('clerk.workers.track_job')
    mocker.patch('clerk.workers.get_fetcher')
    mocker.patch('clerk.workers.fetch_internal')
    mocker.patch('clerk.workers.log_with_context')

    # Mock Path to return some PDFs
    mock_pdf = mocker.MagicMock()
    mock_pdf.name = "test.pdf"
    mock_path = mocker.patch('clerk.workers.Path')
    mock_path.return_value.exists.return_value = True
    mock_path.return_value.glob.return_value = [mock_pdf]

    # Mock OCR queue
    mock_ocr_queue = mocker.MagicMock()
    mock_job = mocker.MagicMock(id="ocr-job-123")
    mock_ocr_queue.enqueue.return_value = mock_job
    mocker.patch('clerk.workers.get_ocr_queue', return_value=mock_ocr_queue)
    mocker.patch('clerk.workers.get_compilation_queue')

    fetch_site_job("test.civic.band", run_id="test_123_abc")

    # Verify OCR job was enqueued with run_id
    mock_ocr_queue.enqueue.assert_called()
    call_kwargs = mock_ocr_queue.enqueue.call_args[1]
    assert call_kwargs['run_id'] == "test_123_abc"
```

**Step 2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_workers.py::test_fetch_site_job_accepts_run_id_parameter -v`

Expected: FAIL with "TypeError: fetch_site_job() got an unexpected keyword argument 'run_id'"

**Step 3: Write minimal implementation**

Modify `src/clerk/workers.py` fetch_site_job:

```python
def fetch_site_job(subdomain, run_id, all_years=False, all_agendas=False):
    """RQ job: Fetch PDFs for a site then spawn OCR jobs.

    Args:
        subdomain: Site subdomain
        run_id: Pipeline run identifier
        all_years: Fetch all years (default: False)
        all_agendas: Fetch all agendas (default: False)
    """
    from .cli import fetch_internal, get_fetcher
    from .queue import get_ocr_queue

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
        # Get site data
        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, subdomain)

        if not site:
            log_with_context(
                "Site not found",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
                level="error"
            )
            raise ValueError(f"Site not found: {subdomain}")

        log_with_context("Found site", subdomain=subdomain, run_id=run_id, stage=stage, scraper=site.get("scraper"))

        # Update progress to fetch stage
        with civic_db_connection() as conn:
            create_site_progress(conn, subdomain, "fetch")
        log_with_context("Created fetch progress", subdomain=subdomain, run_id=run_id, stage=stage)

        # Perform fetch using existing logic
        fetcher = get_fetcher(site, all_years=all_years, all_agendas=all_agendas)
        log_with_context("Starting PDF fetch", subdomain=subdomain, run_id=run_id, stage=stage)
        fetch_internal(subdomain, fetcher)
        log_with_context("Completed PDF fetch", subdomain=subdomain, run_id=run_id, stage=stage)

        # Count PDFs that need OCR from both minutes and agendas directories
        storage_dir = os.getenv("STORAGE_DIR", "../sites")
        minutes_pdf_dir = Path(f"{storage_dir}/{subdomain}/pdfs")
        agendas_pdf_dir = Path(f"{storage_dir}/{subdomain}/_agendas/pdfs")

        pdf_files = []

        # Collect minutes PDFs
        if minutes_pdf_dir.exists():
            minutes_pdfs = list(minutes_pdf_dir.glob("**/*.pdf"))
            log_with_context(
                "Found minutes PDFs",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
                count=len(minutes_pdfs),
                directory=str(minutes_pdf_dir),
            )
            pdf_files.extend(minutes_pdfs)
        else:
            logger.info("Minutes PDF directory does not exist: %s", minutes_pdf_dir)

        # Collect agenda PDFs
        if agendas_pdf_dir.exists():
            agendas_pdfs = list(agendas_pdf_dir.glob("**/*.pdf"))
            log_with_context(
                "Found agenda PDFs",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
                count=len(agendas_pdfs),
                directory=str(agendas_pdf_dir),
            )
            pdf_files.extend(agendas_pdfs)
        else:
            logger.info("Agendas PDF directory does not exist: %s", agendas_pdf_dir)

        log_with_context(
            "Total PDFs found for OCR",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            total_pdfs=len(pdf_files),
        )

        # Update progress: moving to OCR stage
        with civic_db_connection() as conn:
            update_site_progress(conn, subdomain, stage="ocr", stage_total=len(pdf_files))
        log_with_context(
            "Updated progress to OCR stage",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            stage_total=len(pdf_files),
        )

        # Spawn OCR jobs (fan-out)
        ocr_queue = get_ocr_queue()
        ocr_job_ids = []

        ocr_backend = os.getenv("DEFAULT_OCR_BACKEND", "tesseract")
        log_with_context("Using OCR backend", subdomain=subdomain, run_id=run_id, stage=stage, backend=ocr_backend)

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
            ocr_job_ids.append(job.id)
            logger.debug(
                "Enqueued OCR job %s for PDF %s (subdomain=%s)",
                job.id,
                pdf_path.name,
                subdomain,
            )

            # Track in PostgreSQL
            with civic_db_connection() as conn:
                track_job(conn, job.id, subdomain, "ocr-page", "ocr")

        log_with_context(
            "Enqueued OCR jobs",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            job_count=len(ocr_job_ids),
        )

        # Spawn coordinator job that waits for ALL OCR jobs (fan-in)
        if ocr_job_ids:
            from .queue import get_compilation_queue

            compilation_queue = get_compilation_queue()
            coord_job = compilation_queue.enqueue(
                ocr_complete_coordinator,
                subdomain=subdomain,
                run_id=run_id,  # NEW: pass run_id
                depends_on=ocr_job_ids,  # RQ waits for ALL
                job_timeout="5m",
                description=f"OCR coordinator: {subdomain}",
            )

            # Track coordinator job
            with civic_db_connection() as conn:
                track_job(conn, coord_job.id, subdomain, "ocr-coordinator", "ocr")

            log_with_context(
                "Enqueued OCR coordinator job",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
                coordinator_job_id=coord_job.id,
                depends_on_count=len(ocr_job_ids),
            )
        else:
            logger.warning(
                "No OCR jobs to spawn for subdomain=%s - no PDFs found",
                subdomain,
            )

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
        # Milestone: failed
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

**Step 4: Run test to verify it passes**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_workers.py -k fetch_site_job -v`

Expected: PASS (all fetch_site_job tests passing)

**Step 5: Commit**

```bash
git add src/clerk/workers.py tests/test_workers.py
git commit -m "feat: add run_id and milestones to fetch_site_job

Update fetch_site_job to accept run_id parameter and log stage milestones:
- fetch_started: logged at job entry with config
- fetch_completed: logged at job exit with duration and metrics
- fetch_failed: logged on exception with error context

Changes:
- Add run_id parameter to signature
- Replace output_log calls with log_with_context
- Add try/except with rich error logging
- Pass run_id to spawned OCR jobs and coordinator"
```

---

## Task 5: Update ocr_page_job with run_id and Milestones

**Files:**
- Modify: `src/clerk/workers.py:182-260`
- Test: `tests/test_workers.py`

**Step 1: Write the failing test**

Add to `tests/test_workers.py`:

```python
def test_ocr_page_job_accepts_run_id_parameter(mocker):
    """Test that ocr_page_job accepts run_id parameter."""
    from clerk.workers import ocr_page_job

    # Mock dependencies
    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.workers.get_site_by_subdomain', return_value={'subdomain': 'test'})
    mocker.patch('clerk.workers.get_fetcher')
    mock_fetcher = mocker.MagicMock()
    mocker.patch('clerk.workers.get_fetcher', return_value=mock_fetcher)
    mocker.patch('clerk.workers.increment_stage_progress')
    mock_log = mocker.patch('clerk.workers.log_with_context')

    # Should not raise TypeError
    ocr_page_job("test.civic.band", "/path/to/test.pdf", "tesseract", run_id="test_123_abc")

    # Verify log_with_context was called with run_id
    assert any(
        call[1]['run_id'] == "test_123_abc"
        for call in mock_log.call_args_list
    )


def test_ocr_page_job_logs_ocr_started_milestone(mocker):
    """Test that ocr_page_job logs milestone with OCR context."""
    from clerk.workers import ocr_page_job

    # Mock dependencies
    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.workers.get_site_by_subdomain', return_value={'subdomain': 'test'})
    mock_fetcher = mocker.MagicMock()
    mocker.patch('clerk.workers.get_fetcher', return_value=mock_fetcher)
    mocker.patch('clerk.workers.increment_stage_progress')
    mock_log = mocker.patch('clerk.workers.log_with_context')

    ocr_page_job("test.civic.band", "/path/to/test.pdf", "tesseract", run_id="test_123_abc")

    # Verify milestone was logged with stage="ocr"
    started_calls = [
        call for call in mock_log.call_args_list
        if "Starting ocr_page_job" in call[0][0] or "ocr_page_job" in call[0][0]
    ]
    assert len(started_calls) >= 1

    # Check stage is "ocr"
    assert any(call[1].get('stage') == 'ocr' for call in mock_log.call_args_list)
```

**Step 2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_workers.py::test_ocr_page_job_accepts_run_id_parameter -v`

Expected: FAIL with "TypeError: ocr_page_job() got an unexpected keyword argument 'run_id'"

**Step 3: Write minimal implementation**

Modify `src/clerk/workers.py` ocr_page_job function signature and add milestones:

```python
def ocr_page_job(subdomain, pdf_path, backend, run_id):
    """RQ job: OCR a single PDF page.

    Args:
        subdomain: Site subdomain
        pdf_path: Path to PDF file
        backend: OCR backend (tesseract or vision)
        run_id: Pipeline run identifier
    """
    from .cli import get_fetcher

    stage = "ocr"
    start_time = time.time()
    path_obj = Path(pdf_path)

    log_with_context(
        "Starting ocr_page_job",
        subdomain=subdomain,
        run_id=run_id,
        stage=stage,
        pdf_name=path_obj.name,
        backend=backend,
    )

    try:
        # Get site and fetcher for OCR logic
        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, subdomain)

        if not site:
            log_with_context(
                "Site not found for OCR",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
                level="error",
                pdf_path=pdf_path
            )
            raise ValueError(f"Site not found: {subdomain}")

        fetcher = get_fetcher(site)

        # Perform OCR
        log_with_context(
            f"Starting OCR with {backend}",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            pdf_path=pdf_path,
            backend=backend
        )

        fetcher.ocr(pdf_path, backend=backend)

        log_with_context(
            "OCR completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            pdf_name=path_obj.name,
            backend=backend
        )

        # Update progress in database
        with civic_db_connection() as conn:
            increment_stage_progress(conn, subdomain)

        duration = time.time() - start_time
        log_with_context(
            "Completed ocr_page_job",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            duration_seconds=round(duration, 2),
            pdf_name=path_obj.name,
            backend=backend
        )

    except Exception as e:
        duration = time.time() - start_time
        log_with_context(
            f"OCR failed: {e}",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            level="error",
            duration_seconds=round(duration, 2),
            pdf_path=pdf_path,
            pdf_name=path_obj.name,
            backend=backend,
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc()
        )
        raise
```

**Step 4: Run test to verify it passes**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_workers.py -k ocr_page_job -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/workers.py tests/test_workers.py
git commit -m "feat: add run_id and milestones to ocr_page_job

Update ocr_page_job to accept run_id parameter and log with stage context.

Changes:
- Add run_id parameter to signature
- Replace output_log calls with log_with_context
- Add try/except with rich error logging including pdf_path and backend
- Log OCR start and completion with timing"
```

---

## Task 6: Update ocr_complete_coordinator with run_id and Milestones

**Files:**
- Modify: `src/clerk/workers.py:262-323`
- Test: `tests/test_workers.py`

**Step 1: Write the failing test**

Add to `tests/test_workers.py`:

```python
def test_ocr_complete_coordinator_accepts_run_id(mocker):
    """Test that ocr_complete_coordinator accepts run_id parameter."""
    from clerk.workers import ocr_complete_coordinator

    # Mock dependencies
    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.workers.update_site_progress')
    mocker.patch('clerk.workers.track_job')
    mocker.patch('clerk.workers.get_compilation_queue')
    mocker.patch('clerk.workers.get_extraction_queue')
    mock_log = mocker.patch('clerk.workers.log_with_context')

    # Should not raise TypeError
    ocr_complete_coordinator("test.civic.band", run_id="test_123_abc")

    # Verify log_with_context was called with run_id and stage="ocr"
    assert any(
        call[1]['run_id'] == "test_123_abc" and call[1]['stage'] == 'ocr'
        for call in mock_log.call_args_list
    )


def test_ocr_complete_coordinator_passes_run_id_to_child_jobs(mocker):
    """Test that coordinator passes run_id to compilation and extraction jobs."""
    from clerk.workers import ocr_complete_coordinator

    # Mock dependencies
    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.workers.update_site_progress')
    mocker.patch('clerk.workers.track_job')
    mocker.patch('clerk.workers.log_with_context')

    # Mock queues
    mock_compilation_queue = mocker.MagicMock()
    mock_compilation_job = mocker.MagicMock(id="comp-job-123")
    mock_compilation_queue.enqueue.return_value = mock_compilation_job
    mocker.patch('clerk.workers.get_compilation_queue', return_value=mock_compilation_queue)

    mock_extraction_queue = mocker.MagicMock()
    mock_extraction_job = mocker.MagicMock(id="ext-job-123")
    mock_extraction_queue.enqueue.return_value = mock_extraction_job
    mocker.patch('clerk.workers.get_extraction_queue', return_value=mock_extraction_queue)

    ocr_complete_coordinator("test.civic.band", run_id="test_123_abc")

    # Verify both jobs were enqueued with run_id
    comp_call_kwargs = mock_compilation_queue.enqueue.call_args[1]
    assert comp_call_kwargs['run_id'] == "test_123_abc"

    ext_call_kwargs = mock_extraction_queue.enqueue.call_args[1]
    assert ext_call_kwargs['run_id'] == "test_123_abc"
```

**Step 2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_workers.py::test_ocr_complete_coordinator_accepts_run_id -v`

Expected: FAIL with "TypeError: ocr_complete_coordinator() missing 1 required positional argument: 'run_id'"

**Step 3: Write minimal implementation**

Modify `src/clerk/workers.py` ocr_complete_coordinator:

```python
def ocr_complete_coordinator(subdomain, run_id):
    """RQ job: Coordinate after all OCR jobs complete.

    Spawns parallel compilation and extraction jobs.

    Args:
        subdomain: Site subdomain
        run_id: Pipeline run identifier
    """
    stage = "ocr"
    start_time = time.time()

    log_with_context(
        "OCR coordinator started",
        subdomain=subdomain,
        run_id=run_id,
        stage=stage
    )

    try:
        # Update progress to compilation stage
        with civic_db_connection() as conn:
            update_site_progress(conn, subdomain, stage="compilation")

        log_with_context(
            "All OCR jobs completed, spawning compilation and extraction",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage
        )

        # Spawn compilation job
        from .queue import get_compilation_queue
        compilation_queue = get_compilation_queue()
        comp_job = compilation_queue.enqueue(
            db_compilation_job,
            subdomain=subdomain,
            run_id=run_id,  # NEW: pass run_id
            job_timeout="30m",
            description=f"DB compilation: {subdomain}",
        )

        with civic_db_connection() as conn:
            track_job(conn, comp_job.id, subdomain, "db-compilation", "compilation")

        log_with_context(
            "Enqueued compilation job",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            job_id=comp_job.id
        )

        # Spawn extraction job (runs in parallel with compilation)
        from .queue import get_extraction_queue
        extraction_queue = get_extraction_queue()
        ext_job = extraction_queue.enqueue(
            extraction_job,
            subdomain=subdomain,
            run_id=run_id,  # NEW: pass run_id
            job_timeout="30m",
            description=f"Extraction: {subdomain}",
        )

        with civic_db_connection() as conn:
            track_job(conn, ext_job.id, subdomain, "extraction", "extraction")

        log_with_context(
            "Enqueued extraction job",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            job_id=ext_job.id
        )

        duration = time.time() - start_time
        log_with_context(
            "OCR coordinator completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            duration_seconds=round(duration, 2),
            spawned_jobs=2
        )

    except Exception as e:
        duration = time.time() - start_time
        log_with_context(
            f"OCR coordinator failed: {e}",
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

**Step 4: Run test to verify it passes**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_workers.py -k ocr_complete_coordinator -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/workers.py tests/test_workers.py
git commit -m "feat: add run_id and milestones to ocr_complete_coordinator

Update coordinator to accept run_id and pass to spawned jobs.

Changes:
- Add run_id parameter to signature
- Replace output_log calls with log_with_context
- Pass run_id to compilation and extraction jobs
- Add error logging with full context"
```

---

## Task 7: Update db_compilation_job with run_id and Milestones

**Files:**
- Modify: `src/clerk/workers.py:325-401`
- Test: `tests/test_workers.py`

**Step 1: Write the failing test**

Add to `tests/test_workers.py`:

```python
def test_db_compilation_job_accepts_run_id(mocker):
    """Test that db_compilation_job accepts run_id parameter."""
    from clerk.workers import db_compilation_job

    # Mock dependencies
    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.workers.build_db_from_text_internal')
    mocker.patch('clerk.workers.get_deploy_queue')
    mocker.patch('clerk.workers.track_job')
    mock_log = mocker.patch('clerk.workers.log_with_context')

    # Should not raise TypeError
    db_compilation_job("test.civic.band", run_id="test_123_abc")

    # Verify stage="compilation"
    assert any(
        call[1]['stage'] == 'compilation'
        for call in mock_log.call_args_list
    )


def test_db_compilation_job_logs_compilation_started(mocker):
    """Test that db_compilation_job logs compilation_started milestone."""
    from clerk.workers import db_compilation_job

    # Mock dependencies
    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.workers.build_db_from_text_internal')
    mocker.patch('clerk.workers.get_deploy_queue')
    mocker.patch('clerk.workers.track_job')
    mock_log = mocker.patch('clerk.workers.log_with_context')

    db_compilation_job("test.civic.band", run_id="test_123_abc")

    # Verify compilation_started was logged
    started_calls = [
        call for call in mock_log.call_args_list
        if "compilation" in call[0][0].lower() and "start" in call[0][0].lower()
    ]
    assert len(started_calls) >= 1


def test_db_compilation_job_passes_run_id_to_deploy(mocker):
    """Test that db_compilation_job passes run_id to deploy job."""
    from clerk.workers import db_compilation_job

    # Mock dependencies
    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.workers.build_db_from_text_internal')
    mocker.patch('clerk.workers.track_job')
    mocker.patch('clerk.workers.log_with_context')

    # Mock deploy queue
    mock_deploy_queue = mocker.MagicMock()
    mock_deploy_job = mocker.MagicMock(id="deploy-job-123")
    mock_deploy_queue.enqueue.return_value = mock_deploy_job
    mocker.patch('clerk.workers.get_deploy_queue', return_value=mock_deploy_queue)

    db_compilation_job("test.civic.band", run_id="test_123_abc")

    # Verify deploy job was enqueued with run_id
    call_kwargs = mock_deploy_queue.enqueue.call_args[1]
    assert call_kwargs['run_id'] == "test_123_abc"
```

**Step 2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_workers.py::test_db_compilation_job_accepts_run_id -v`

Expected: FAIL with TypeError

**Step 3: Write minimal implementation**

Modify `src/clerk/workers.py` db_compilation_job:

```python
def db_compilation_job(subdomain, run_id, extract_entities=False, ignore_cache=False):
    """RQ job: Compile database from OCR text files.

    Args:
        subdomain: Site subdomain
        run_id: Pipeline run identifier
        extract_entities: Whether to extract entities (default: False)
        ignore_cache: Whether to ignore extraction cache (default: False)
    """
    stage = "compilation"
    start_time = time.time()

    log_with_context(
        "compilation_started",
        subdomain=subdomain,
        run_id=run_id,
        stage=stage,
        extract_entities=extract_entities,
        ignore_cache=ignore_cache
    )

    try:
        from .utils import build_db_from_text_internal

        log_with_context(
            "Starting database compilation",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            extract_entities=extract_entities,
            ignore_cache=ignore_cache
        )

        build_db_from_text_internal(
            subdomain,
            extract_entities=extract_entities,
            ignore_cache=ignore_cache
        )

        log_with_context(
            "Database compilation completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage
        )

        # Update progress to deploy stage
        with civic_db_connection() as conn:
            update_site_progress(conn, subdomain, stage="deploy")

        # Spawn deploy job
        from .queue import get_deploy_queue
        deploy_queue = get_deploy_queue()
        deploy_job = deploy_queue.enqueue(
            deploy_job_func,
            subdomain=subdomain,
            run_id=run_id,  # NEW: pass run_id
            job_timeout="10m",
            description=f"Deploy: {subdomain}",
        )

        with civic_db_connection() as conn:
            track_job(conn, deploy_job.id, subdomain, "deploy", "deploy")

        log_with_context(
            "Enqueued deploy job",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            deploy_job_id=deploy_job.id
        )

        duration = time.time() - start_time
        log_with_context(
            "compilation_completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            duration_seconds=round(duration, 2)
        )

    except Exception as e:
        duration = time.time() - start_time
        log_with_context(
            f"compilation_failed: {e}",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            level="error",
            duration_seconds=round(duration, 2),
            extract_entities=extract_entities,
            ignore_cache=ignore_cache,
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc()
        )
        raise
```

**Step 4: Run test to verify it passes**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_workers.py -k db_compilation_job -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/workers.py tests/test_workers.py
git commit -m "feat: add run_id and milestones to db_compilation_job

Update db_compilation_job with run_id parameter and stage milestones.

Changes:
- Add run_id parameter to signature
- Log compilation_started and compilation_completed milestones
- Pass run_id to deploy job
- Add error logging with compilation context"
```

---

## Task 8: Update extraction_job with run_id and Milestones

**Files:**
- Modify: `src/clerk/workers.py:403-471`
- Test: `tests/test_workers.py`

**Step 1: Write the failing test**

Add to `tests/test_workers.py`:

```python
def test_extraction_job_accepts_run_id(mocker):
    """Test that extraction_job accepts run_id parameter."""
    from clerk.workers import extraction_job

    # Mock dependencies
    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.workers.build_db_from_text_internal')
    mock_log = mocker.patch('clerk.workers.log_with_context')

    # Should not raise TypeError
    extraction_job("test.civic.band", run_id="test_123_abc")

    # Verify stage="extraction"
    assert any(
        call[1]['stage'] == 'extraction'
        for call in mock_log.call_args_list
    )


def test_extraction_job_logs_extraction_started(mocker):
    """Test that extraction_job logs extraction_started milestone."""
    from clerk.workers import extraction_job

    # Mock dependencies
    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.workers.build_db_from_text_internal')
    mock_log = mocker.patch('clerk.workers.log_with_context')

    extraction_job("test.civic.band", run_id="test_123_abc")

    # Verify extraction_started was logged
    started_calls = [
        call for call in mock_log.call_args_list
        if "extraction" in call[0][0].lower() and "start" in call[0][0].lower()
    ]
    assert len(started_calls) >= 1
```

**Step 2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_workers.py::test_extraction_job_accepts_run_id -v`

Expected: FAIL

**Step 3: Write minimal implementation**

Modify `src/clerk/workers.py` extraction_job:

```python
def extraction_job(subdomain, run_id, extract_entities=True, ignore_cache=False):
    """RQ job: Extract entities and votes from OCR text (runs in parallel with compilation).

    Args:
        subdomain: Site subdomain
        run_id: Pipeline run identifier
        extract_entities: Whether to extract entities (default: True)
        ignore_cache: Whether to ignore extraction cache (default: False)
    """
    stage = "extraction"
    start_time = time.time()

    log_with_context(
        "extraction_started",
        subdomain=subdomain,
        run_id=run_id,
        stage=stage,
        extract_entities=extract_entities,
        ignore_cache=ignore_cache
    )

    try:
        from .utils import build_db_from_text_internal

        log_with_context(
            "Starting entity extraction",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            extract_entities=extract_entities,
            ignore_cache=ignore_cache
        )

        # Build database with entity extraction enabled
        build_db_from_text_internal(
            subdomain,
            extract_entities=extract_entities,
            ignore_cache=ignore_cache
        )

        log_with_context(
            "Entity extraction completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage
        )

        duration = time.time() - start_time
        log_with_context(
            "extraction_completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            duration_seconds=round(duration, 2)
        )

    except Exception as e:
        duration = time.time() - start_time
        log_with_context(
            f"extraction_failed: {e}",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            level="error",
            duration_seconds=round(duration, 2),
            extract_entities=extract_entities,
            ignore_cache=ignore_cache,
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc()
        )
        raise
```

**Step 4: Run test to verify it passes**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_workers.py -k extraction_job -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/workers.py tests/test_workers.py
git commit -m "feat: add run_id and milestones to extraction_job

Update extraction_job with run_id parameter and stage milestones.

Changes:
- Add run_id parameter to signature
- Log extraction_started and extraction_completed milestones
- Add error logging with extraction context
- Include extract_entities and ignore_cache in logs"
```

---

## Task 9: Update deploy_job with run_id and Milestones

**Files:**
- Modify: `src/clerk/workers.py:473-501`
- Test: `tests/test_workers.py`

**Step 1: Write the failing test**

Add to `tests/test_workers.py`:

```python
def test_deploy_job_accepts_run_id(mocker):
    """Test that deploy_job accepts run_id parameter."""
    from clerk.workers import deploy_job as deploy_job_func

    # Mock dependencies
    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.workers.pm.hook.deploy_site')
    mock_log = mocker.patch('clerk.workers.log_with_context')

    # Should not raise TypeError
    deploy_job_func("test.civic.band", run_id="test_123_abc")

    # Verify stage="deploy"
    assert any(
        call[1]['stage'] == 'deploy'
        for call in mock_log.call_args_list
    )


def test_deploy_job_logs_deploy_completed(mocker):
    """Test that deploy_job logs deploy_completed milestone."""
    from clerk.workers import deploy_job as deploy_job_func

    # Mock dependencies
    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.workers.pm.hook.deploy_site')
    mock_log = mocker.patch('clerk.workers.log_with_context')

    deploy_job_func("test.civic.band", run_id="test_123_abc")

    # Verify deploy_completed was logged
    completed_calls = [
        call for call in mock_log.call_args_list
        if "deploy_completed" in call[0][0]
    ]
    assert len(completed_calls) == 1
```

**Step 2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_workers.py::test_deploy_job_accepts_run_id -v`

Expected: FAIL

**Step 3: Write minimal implementation**

Modify `src/clerk/workers.py` deploy_job:

```python
def deploy_job(subdomain, run_id):
    """RQ job: Deploy compiled database via plugins.

    Args:
        subdomain: Site subdomain
        run_id: Pipeline run identifier
    """
    from .utils import pm

    stage = "deploy"
    start_time = time.time()

    log_with_context(
        "deploy_started",
        subdomain=subdomain,
        run_id=run_id,
        stage=stage
    )

    try:
        log_with_context(
            "Running deploy plugins",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage
        )

        # Call plugin hook to deploy
        pm.hook.deploy_site(subdomain=subdomain)

        log_with_context(
            "Deploy plugins completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage
        )

        # Mark progress as complete
        with civic_db_connection() as conn:
            update_site_progress(conn, subdomain, stage="complete")

        duration = time.time() - start_time
        log_with_context(
            "deploy_completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            duration_seconds=round(duration, 2)
        )

    except Exception as e:
        duration = time.time() - start_time
        log_with_context(
            f"deploy_failed: {e}",
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

**Step 4: Run test to verify it passes**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest tests/test_workers.py -k deploy_job -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/workers.py tests/test_workers.py
git commit -m "feat: add run_id and milestones to deploy_job

Update deploy_job with run_id parameter and stage milestones.

Changes:
- Add run_id parameter to signature
- Log deploy_started and deploy_completed milestones
- Add error logging with deploy context
- Mark stage as complete in progress tracking"
```

---

## Task 10: Run Full Test Suite and Verify Integration

**Files:**
- All modified files

**Step 1: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest -v`

Expected: All tests passing (260+ tests)

**Step 2: Verify no regressions**

Check test output for:
- No new failures
- All existing tests still pass
- New tests for logging features pass

**Step 3: Check test coverage**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib uv run pytest --cov=src/clerk --cov-report=term-missing`

Expected: Coverage for modified files (output.py, queue.py, workers.py) should be high

**Step 4: Document environment variable requirement**

Create or update `.env.example` to include:

```bash
# Required for running tests on macOS with arm64
# export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
```

**Step 5: Final commit**

```bash
git add .env.example
git commit -m "docs: add note about DYLD_FALLBACK_LIBRARY_PATH for tests

Document environment variable needed to run tests on macOS arm64
due to WeasyPrint requiring Homebrew libraries."
```

---

## Implementation Complete

All tasks completed! The comprehensive pipeline logging system is now implemented with:

✅ **run_id generation and propagation** - Unique identifier per pipeline execution
✅ **Enhanced output.log()** - Structured fields (run_id, stage, job_id, parent_job_id)
✅ **log_with_context helper** - Automatic job context extraction
✅ **Stage milestones** - started/completed/failed events for all stages
✅ **Rich error context** - Full error details with file/page context
✅ **Backward compatibility** - All parameters optional, auto-generated
✅ **Test coverage** - Comprehensive unit tests for all changes

**Next Steps:**
1. Manual testing with a real pipeline run
2. Verify logs appear correctly in Loki
3. Test Grafana queries from design document
4. Build sample dashboards for monitoring

**Testing Checklist:**
- [ ] Enqueue a job and verify run_id is generated
- [ ] Check Loki logs filtered by run_id show complete pipeline
- [ ] Verify stage transitions are visible
- [ ] Test error scenario and verify rich context
- [ ] Validate parent_job_id links child jobs correctly
- [ ] Test all example Grafana queries from design
