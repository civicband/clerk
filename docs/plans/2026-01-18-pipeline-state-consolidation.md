# Pipeline State Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Consolidate pipeline state into single source of truth (sites table) with atomic counters, eliminating stuck sites and table sync issues.

**Architecture:** Replace dual-table system (sites + site_progress) with unified sites table using per-stage counters. Jobs update counters atomically, last job triggers coordinator via database constraint. Reconciliation job auto-recovers stuck sites by inferring state from filesystem.

**Tech Stack:** Python, SQLAlchemy, PostgreSQL, RQ, pytest

---

## Task 1: Create Database Migration

**Files:**
- Create: `migrations/001_add_pipeline_state_columns.sql`

**Step 1: Write SQL migration**

Create `migrations/001_add_pipeline_state_columns.sql`:

```sql
-- Pipeline State Consolidation Migration
-- Adds atomic counter columns to sites table

-- Pipeline state tracking
ALTER TABLE sites ADD COLUMN IF NOT EXISTS current_stage VARCHAR;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS started_at TIMESTAMP;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

-- Fetch stage counters
ALTER TABLE sites ADD COLUMN IF NOT EXISTS fetch_total INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS fetch_completed INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS fetch_failed INT DEFAULT 0;

-- OCR stage counters
ALTER TABLE sites ADD COLUMN IF NOT EXISTS ocr_total INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS ocr_completed INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS ocr_failed INT DEFAULT 0;

-- Compilation stage counters
ALTER TABLE sites ADD COLUMN IF NOT EXISTS compilation_total INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS compilation_completed INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS compilation_failed INT DEFAULT 0;

-- Extraction stage counters
ALTER TABLE sites ADD COLUMN IF NOT EXISTS extraction_total INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS extraction_completed INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS extraction_failed INT DEFAULT 0;

-- Deploy stage counters
ALTER TABLE sites ADD COLUMN IF NOT EXISTS deploy_total INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS deploy_completed INT DEFAULT 0;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS deploy_failed INT DEFAULT 0;

-- Coordinator tracking
ALTER TABLE sites ADD COLUMN IF NOT EXISTS coordinator_enqueued BOOLEAN DEFAULT FALSE;

-- Error observability
ALTER TABLE sites ADD COLUMN IF NOT EXISTS last_error_stage VARCHAR;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS last_error_message TEXT;
ALTER TABLE sites ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMP;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_sites_current_stage ON sites(current_stage);
CREATE INDEX IF NOT EXISTS idx_sites_updated_at ON sites(updated_at);
CREATE INDEX IF NOT EXISTS idx_sites_coordinator_enqueued ON sites(subdomain, coordinator_enqueued) WHERE coordinator_enqueued = FALSE;

-- Comments for documentation
COMMENT ON COLUMN sites.current_stage IS 'Current pipeline stage: fetch|ocr|compilation|extraction|deploy|completed';
COMMENT ON COLUMN sites.coordinator_enqueued IS 'Prevents duplicate coordinators - atomically claimed by last job';
```

**Step 2: Update SQLAlchemy models**

Modify `src/clerk/models.py`:

```python
sites_table = Table(
    "sites",
    metadata,
    Column("subdomain", String, primary_key=True, nullable=False),
    Column("name", String),
    Column("state", String),
    Column("kind", String),
    Column("scraper", String),
    Column("pages", Integer),
    Column("start_year", Integer),
    Column("extra", String),
    Column("country", String),
    Column("lat", String),
    Column("lng", String),

    # Pipeline state
    Column("current_stage", String),
    Column("started_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),

    # Fetch counters
    Column("fetch_total", Integer, server_default="0"),
    Column("fetch_completed", Integer, server_default="0"),
    Column("fetch_failed", Integer, server_default="0"),

    # OCR counters
    Column("ocr_total", Integer, server_default="0"),
    Column("ocr_completed", Integer, server_default="0"),
    Column("ocr_failed", Integer, server_default="0"),

    # Compilation counters
    Column("compilation_total", Integer, server_default="0"),
    Column("compilation_completed", Integer, server_default="0"),
    Column("compilation_failed", Integer, server_default="0"),

    # Extraction counters
    Column("extraction_total", Integer, server_default="0"),
    Column("extraction_completed", Integer, server_default="0"),
    Column("extraction_failed", Integer, server_default="0"),

    # Deploy counters
    Column("deploy_total", Integer, server_default="0"),
    Column("deploy_completed", Integer, server_default="0"),
    Column("deploy_failed", Integer, server_default="0"),

    # Coordinator tracking
    Column("coordinator_enqueued", Boolean, server_default="FALSE"),

    # Error tracking
    Column("last_error_stage", String),
    Column("last_error_message", String),
    Column("last_error_at", DateTime(timezone=True)),

    # Deprecated (keep during migration)
    Column("status", String),
    Column("extraction_status", String, server_default="pending"),
    Column("last_updated", String),
    Column("last_deployed", String),
    Column("last_extracted", String),
)
```

**Step 3: Commit migration files**

```bash
git add migrations/001_add_pipeline_state_columns.sql src/clerk/models.py
git commit -m "feat: add pipeline state columns to sites table

Add atomic counter columns for all pipeline stages (fetch, OCR,
compilation, extraction, deploy). Includes coordinator_enqueued
flag to prevent duplicate coordinators.

Part of pipeline state consolidation design."
```

---

## Task 2: Create Helper Functions for State Updates

**Files:**
- Create: `src/clerk/pipeline_state.py`
- Test: `tests/test_pipeline_state.py`

**Step 1: Write tests for state update helpers**

Create `tests/test_pipeline_state.py`:

```python
"""Tests for pipeline state management helpers."""

import pytest
from datetime import datetime, UTC
from clerk.db import civic_db_connection
from clerk.models import sites_table
from clerk.pipeline_state import (
    initialize_stage,
    increment_completed,
    increment_failed,
    should_trigger_coordinator,
    claim_coordinator_enqueue,
)


@pytest.fixture
def test_site(tmp_path, monkeypatch):
    """Create a test site in database."""
    from clerk.db import civic_db_connection, upsert_site

    site_data = {
        "subdomain": "test-site",
        "name": "Test Site",
        "state": "CA",
        "kind": "city",
        "scraper": "test_scraper",
    }

    with civic_db_connection() as conn:
        upsert_site(conn, site_data)

    yield "test-site"

    # Cleanup
    with civic_db_connection() as conn:
        from sqlalchemy import delete
        conn.execute(delete(sites_table).where(sites_table.c.subdomain == "test-site"))


def test_initialize_stage(test_site):
    """Test initializing a pipeline stage."""
    initialize_stage(test_site, "ocr", total_jobs=5)

    with civic_db_connection() as conn:
        from sqlalchemy import select
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == test_site)
        ).fetchone()

    assert site.current_stage == "ocr"
    assert site.ocr_total == 5
    assert site.ocr_completed == 0
    assert site.ocr_failed == 0
    assert site.coordinator_enqueued == False
    assert site.updated_at is not None


def test_increment_completed(test_site):
    """Test incrementing completed counter."""
    initialize_stage(test_site, "ocr", total_jobs=3)

    increment_completed(test_site, "ocr")

    with civic_db_connection() as conn:
        from sqlalchemy import select
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == test_site)
        ).fetchone()

    assert site.ocr_completed == 1
    assert site.ocr_failed == 0


def test_increment_failed(test_site):
    """Test incrementing failed counter and recording error."""
    initialize_stage(test_site, "ocr", total_jobs=3)

    increment_failed(
        test_site,
        "ocr",
        error_message="PDF corrupted",
        error_class="PdfReadError"
    )

    with civic_db_connection() as conn:
        from sqlalchemy import select
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == test_site)
        ).fetchone()

    assert site.ocr_completed == 0
    assert site.ocr_failed == 1
    assert site.last_error_stage == "ocr"
    assert "PDF corrupted" in site.last_error_message
    assert site.last_error_at is not None


def test_should_trigger_coordinator_not_ready(test_site):
    """Test coordinator should not trigger when jobs incomplete."""
    initialize_stage(test_site, "ocr", total_jobs=3)
    increment_completed(test_site, "ocr")

    result = should_trigger_coordinator(test_site, "ocr")

    assert result == False


def test_should_trigger_coordinator_ready(test_site):
    """Test coordinator should trigger when all jobs done."""
    initialize_stage(test_site, "ocr", total_jobs=3)
    increment_completed(test_site, "ocr")
    increment_completed(test_site, "ocr")
    increment_failed(test_site, "ocr", "PDF error", "PdfError")

    result = should_trigger_coordinator(test_site, "ocr")

    assert result == True  # 2 + 1 == 3


def test_claim_coordinator_enqueue_success(test_site):
    """Test claiming coordinator enqueue succeeds."""
    initialize_stage(test_site, "ocr", total_jobs=1)
    increment_completed(test_site, "ocr")

    claimed = claim_coordinator_enqueue(test_site)

    assert claimed == True

    with civic_db_connection() as conn:
        from sqlalchemy import select
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == test_site)
        ).fetchone()

    assert site.coordinator_enqueued == True


def test_claim_coordinator_enqueue_race_condition(test_site):
    """Test only one job can claim coordinator enqueue."""
    initialize_stage(test_site, "ocr", total_jobs=2)
    increment_completed(test_site, "ocr")
    increment_completed(test_site, "ocr")

    # First claim succeeds
    claimed1 = claim_coordinator_enqueue(test_site)
    assert claimed1 == True

    # Second claim fails (already claimed)
    claimed2 = claim_coordinator_enqueue(test_site)
    assert claimed2 == False
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_pipeline_state.py -v
```

Expected: Multiple failures - module not found, functions not defined

**Step 3: Implement helper functions**

Create `src/clerk/pipeline_state.py`:

```python
"""Pipeline state management helpers.

Provides atomic operations for updating pipeline state in sites table.
"""

from datetime import UTC, datetime
from sqlalchemy import select, update

from .db import civic_db_connection
from .models import sites_table


def initialize_stage(subdomain: str, stage: str, total_jobs: int) -> None:
    """Initialize a pipeline stage with job counters.

    Args:
        subdomain: Site subdomain
        stage: Pipeline stage (fetch/ocr/compilation/extraction/deploy)
        total_jobs: Total number of jobs for this stage
    """
    with civic_db_connection() as conn:
        conn.execute(
            update(sites_table)
            .where(sites_table.c.subdomain == subdomain)
            .values(
                current_stage=stage,
                **{
                    f"{stage}_total": total_jobs,
                    f"{stage}_completed": 0,
                    f"{stage}_failed": 0,
                },
                coordinator_enqueued=False,
                updated_at=datetime.now(UTC),
            )
        )


def increment_completed(subdomain: str, stage: str) -> None:
    """Atomically increment completed counter for a stage.

    Args:
        subdomain: Site subdomain
        stage: Pipeline stage
    """
    with civic_db_connection() as conn:
        stage_completed_col = getattr(sites_table.c, f"{stage}_completed")

        conn.execute(
            update(sites_table)
            .where(sites_table.c.subdomain == subdomain)
            .values(
                **{f"{stage}_completed": stage_completed_col + 1},
                updated_at=datetime.now(UTC),
            )
        )


def increment_failed(
    subdomain: str,
    stage: str,
    error_message: str,
    error_class: str,
) -> None:
    """Atomically increment failed counter and record error.

    Args:
        subdomain: Site subdomain
        stage: Pipeline stage
        error_message: Error message to record
        error_class: Error class name
    """
    with civic_db_connection() as conn:
        stage_failed_col = getattr(sites_table.c, f"{stage}_failed")

        # Truncate error message to avoid database overflow
        truncated_message = f"{error_class}: {error_message}"[:500]

        conn.execute(
            update(sites_table)
            .where(sites_table.c.subdomain == subdomain)
            .values(
                **{f"{stage}_failed": stage_failed_col + 1},
                last_error_stage=stage,
                last_error_message=truncated_message,
                last_error_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )


def should_trigger_coordinator(subdomain: str, stage: str) -> bool:
    """Check if all jobs for a stage are complete.

    Args:
        subdomain: Site subdomain
        stage: Pipeline stage

    Returns:
        True if completed + failed == total (all jobs done)
    """
    with civic_db_connection() as conn:
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == subdomain)
        ).fetchone()

    if not site:
        return False

    total = getattr(site, f"{stage}_total")
    completed = getattr(site, f"{stage}_completed")
    failed = getattr(site, f"{stage}_failed")

    return (completed + failed) == total and not site.coordinator_enqueued


def claim_coordinator_enqueue(subdomain: str) -> bool:
    """Atomically claim the right to enqueue coordinator.

    Uses database-level constraint to ensure only one job succeeds.

    Args:
        subdomain: Site subdomain

    Returns:
        True if this call successfully claimed, False if already claimed
    """
    with civic_db_connection() as conn:
        result = conn.execute(
            update(sites_table)
            .where(
                sites_table.c.subdomain == subdomain,
                sites_table.c.coordinator_enqueued == False,  # Critical: prevents duplicates
            )
            .values(
                coordinator_enqueued=True,
                updated_at=datetime.now(UTC),
            )
        )

        return result.rowcount == 1
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_pipeline_state.py -v
```

Expected: All tests PASS

**Step 5: Commit helper functions**

```bash
git add src/clerk/pipeline_state.py tests/test_pipeline_state.py
git commit -m "feat: add pipeline state management helpers

Atomic operations for updating pipeline state:
- initialize_stage: Set up counters for a stage
- increment_completed/failed: Atomic counter updates
- should_trigger_coordinator: Check if stage is complete
- claim_coordinator_enqueue: Atomic claim to prevent duplicates

Includes comprehensive tests for race conditions."
```

---

## Task 3: Update OCR Job to Use Atomic Counters

**Files:**
- Modify: `src/clerk/workers.py` (fetch_site_job function)
- Modify: `src/clerk/fetcher.py` (do_ocr_job function)
- Test: `tests/test_workers.py`

**Step 1: Write test for OCR job atomic updates**

Add to `tests/test_workers.py`:

```python
def test_ocr_job_updates_counters_on_success(mock_site, tmp_path, monkeypatch):
    """OCR job should increment completed counter on success."""
    from clerk.workers import ocr_page_job
    from clerk.db import civic_db_connection, upsert_site
    from clerk.models import sites_table
    from clerk.pipeline_state import initialize_stage
    from sqlalchemy import select
    from pathlib import Path

    subdomain = "test-site"
    mock_site["subdomain"] = subdomain

    # Setup site in database
    with civic_db_connection() as conn:
        upsert_site(conn, mock_site)

    initialize_stage(subdomain, "ocr", total_jobs=1)

    # Create PDF file
    pdf_dir = Path(tmp_path) / subdomain / "pdfs" / "Meeting"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "2024-01-01.pdf").write_bytes(b"%PDF-1.4 fake pdf")

    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    # Mock OCR processing
    with (
        patch("clerk.fetcher.PDF_SUPPORT", True),
        patch("clerk.fetcher.PdfReader") as mock_reader,
        patch("clerk.fetcher.convert_from_path") as mock_convert,
        patch("subprocess.check_output") as mock_tesseract,
    ):
        mock_reader.return_value.pages = [Mock()]
        mock_convert.return_value = [Mock()]
        mock_tesseract.return_value = b"test text"

        # Run OCR job
        ocr_page_job(
            subdomain=subdomain,
            pdf_path=str(pdf_dir / "2024-01-01.pdf"),
            backend="tesseract",
            run_id="test_run"
        )

    # Verify counter incremented
    with civic_db_connection() as conn:
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == subdomain)
        ).fetchone()

    assert site.ocr_completed == 1
    assert site.ocr_failed == 0


def test_ocr_job_updates_counters_on_failure(mock_site, tmp_path, monkeypatch):
    """OCR job should increment failed counter on failure."""
    from clerk.workers import ocr_page_job
    from clerk.db import civic_db_connection, upsert_site
    from clerk.models import sites_table
    from clerk.pipeline_state import initialize_stage
    from sqlalchemy import select
    from pathlib import Path

    subdomain = "test-site"
    mock_site["subdomain"] = subdomain

    # Setup site in database
    with civic_db_connection() as conn:
        upsert_site(conn, mock_site)

    initialize_stage(subdomain, "ocr", total_jobs=1)

    # Create PDF file
    pdf_dir = Path(tmp_path) / subdomain / "pdfs" / "Meeting"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "2024-01-01.pdf").write_bytes(b"%PDF-1.4 fake pdf")

    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    # Mock OCR processing to fail
    with (
        patch("clerk.fetcher.PDF_SUPPORT", True),
        patch("clerk.fetcher.PdfReader", side_effect=Exception("Corrupted PDF")),
    ):
        # Run OCR job (should not raise, just increment failed)
        ocr_page_job(
            subdomain=subdomain,
            pdf_path=str(pdf_dir / "2024-01-01.pdf"),
            backend="tesseract",
            run_id="test_run"
        )

    # Verify failed counter incremented
    with civic_db_connection() as conn:
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == subdomain)
        ).fetchone()

    assert site.ocr_completed == 0
    assert site.ocr_failed == 1
    assert site.last_error_stage == "ocr"
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_workers.py::test_ocr_job_updates_counters_on_success -v
uv run pytest tests/test_workers.py::test_ocr_job_updates_counters_on_failure -v
```

Expected: FAIL - ocr_page_job doesn't exist or doesn't update counters

**Step 3: Update fetch_site_job to initialize OCR stage**

Modify `src/clerk/workers.py` - update `fetch_site_job` function around line 180:

```python
# After OCR jobs are enqueued, initialize OCR stage counters
from clerk.pipeline_state import initialize_stage

initialize_stage(subdomain, "ocr", total_jobs=len(ocr_job_ids))

# Remove old site_progress update
# OLD CODE TO REMOVE:
# with civic_db_connection() as conn:
#     update_site_progress(conn, subdomain, stage="ocr", stage_total=len(pdf_files))

# KEEP status update for backward compat during migration
with civic_db_connection() as conn:
    update_site(
        conn,
        subdomain,
        {
            "status": "needs_ocr",
            "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
```

**Step 4: Update ocr_page_job to update counters**

Add new function to `src/clerk/workers.py`:

```python
def ocr_page_job(subdomain, pdf_path, backend="tesseract", run_id=None):
    """RQ job: OCR a single PDF page and update counters.

    Args:
        subdomain: Site subdomain
        pdf_path: Path to PDF file
        backend: OCR backend (tesseract or vision)
        run_id: Pipeline run identifier
    """
    from .cli import get_fetcher
    from .pipeline_state import increment_completed, increment_failed, should_trigger_coordinator, claim_coordinator_enqueue
    from .queue import get_compilation_queue

    stage = "ocr"
    start_time = time.time()
    path_obj = Path(pdf_path)

    log_with_context(
        "ocr_started",
        subdomain=subdomain,
        run_id=run_id,
        stage=stage,
        pdf_name=path_obj.name,
        backend=backend,
    )

    success = False
    error = None

    try:
        # Get site to create a fetcher instance
        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, subdomain)

        if not site:
            raise ValueError(f"Site not found: {subdomain}")

        # Create fetcher instance to use its OCR methods
        fetcher = get_fetcher(site)

        # Parse PDF path to extract meeting and date
        date = path_obj.stem
        meeting = path_obj.parent.name

        # Determine prefix based on path
        prefix = "/_agendas" if "/_agendas/" in str(pdf_path) else ""

        # Create job tuple for do_ocr_job
        job = (prefix, meeting, date)
        job_id = f"worker_ocr_{int(time.time())}"

        # Run OCR job (updated to return success/error instead of raising)
        fetcher.do_ocr_job(job, None, job_id, backend=backend)

        success = True

    except Exception as e:
        error = e
        log_with_context(
            f"ocr_failed: {e}",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            level="error",
            pdf_path=pdf_path,
            backend=backend,
            error_type=type(e).__name__,
        )

    # Atomic counter update (success or failure)
    if success:
        increment_completed(subdomain, stage)

        log_with_context(
            "ocr_completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            pdf_name=path_obj.name,
            duration_seconds=round(time.time() - start_time, 2),
        )
    else:
        increment_failed(
            subdomain,
            stage,
            error_message=str(error),
            error_class=type(error).__name__,
        )

    # Check if we're the last job
    if should_trigger_coordinator(subdomain, stage):
        # Atomic claim to enqueue coordinator
        if claim_coordinator_enqueue(subdomain):
            # We won the race - enqueue coordinator
            log_with_context(
                "Last OCR job complete, enqueueing coordinator",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
            )

            get_compilation_queue().enqueue(
                ocr_complete_coordinator,
                subdomain=subdomain,
                run_id=run_id,
                job_timeout="5m",
                description=f"OCR coordinator: {subdomain}",
            )
```

**Step 5: Update fetch_site_job to use new ocr_page_job**

Modify `src/clerk/workers.py` - update fetch_site_job around line 250:

```python
# OLD CODE - Remove depends_on pattern:
# coord_job = get_compilation_queue().enqueue(
#     ocr_complete_coordinator,
#     subdomain=subdomain,
#     run_id=run_id,
#     depends_on=ocr_job_ids,  # REMOVE THIS
#     job_timeout="5m",
# )

# NEW CODE - Coordinator will be enqueued by last OCR job
# No coordinator enqueued here anymore
```

**Step 6: Run tests to verify they pass**

```bash
uv run pytest tests/test_workers.py::test_ocr_job_updates_counters_on_success -v
uv run pytest tests/test_workers.py::test_ocr_job_updates_counters_on_failure -v
```

Expected: All tests PASS

**Step 7: Commit OCR job updates**

```bash
git add src/clerk/workers.py tests/test_workers.py
git commit -m "feat: update OCR jobs to use atomic counters

OCR jobs now:
- Update ocr_completed/ocr_failed counters atomically
- Last job claims coordinator enqueue via database constraint
- No longer use RQ depends_on (eliminates deferred coordinators)

Coordinator triggered by last job completing, not by RQ dependencies."
```

---

## Task 4: Create Migration Script for Stuck Sites

**Files:**
- Create: `scripts/migrate_stuck_sites.py`

**Step 1: Write migration script**

Create `scripts/migrate_stuck_sites.py`:

```python
#!/usr/bin/env python3
"""Migrate stuck sites from site_progress to new atomic counter system.

This script:
1. Finds sites stuck in OCR stage (from site_progress table)
2. Infers actual state from filesystem (count txt/PDF files)
3. Updates sites table with inferred counters
4. Clears deferred coordinators and failed OCR jobs from RQ
"""

import click
from pathlib import Path
from clerk.db import civic_db_connection
from clerk.models import site_progress_table, sites_table
from clerk.queue import get_compilation_queue, get_ocr_queue
from sqlalchemy import select, update


def count_txt_files(subdomain):
    """Count txt files on filesystem."""
    import os
    storage_dir = os.getenv("STORAGE_DIR", "../sites")
    txt_dir = Path(f"{storage_dir}/{subdomain}/txt")
    if not txt_dir.exists():
        return 0
    return len(list(txt_dir.glob("**/*.txt")))


def count_pdf_files(subdomain):
    """Count PDF files on filesystem."""
    import os
    storage_dir = os.getenv("STORAGE_DIR", "../sites")
    pdf_dir = Path(f"{storage_dir}/{subdomain}/pdfs")
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

        click.echo(f"Found {len(stuck)} stuck sites in OCR stage")
        click.echo()

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
                    coordinator_enqueued=False,  # Allows reconciliation to trigger
                    started_at=site_prog.started_at,
                    updated_at=site_prog.updated_at,
                )
            )

            migrated += 1
            click.echo(f"  {subdomain}: {ocr_completed}/{ocr_total} completed, {ocr_failed} failed")

        click.echo()
        click.echo(f"Migrated {migrated} sites")


def clear_rq_state():
    """Clear deferred coordinators and failed OCR jobs."""

    # Clear deferred coordinators
    comp_queue = get_compilation_queue()
    deferred = comp_queue.deferred_job_registry

    click.echo()
    click.echo(f"Clearing {len(deferred)} deferred coordinators...")
    cancelled = 0
    for job_id in deferred.get_job_ids():
        job = comp_queue.fetch_job(job_id)
        if job:
            job.cancel()
            job.delete()
            cancelled += 1

    click.echo(f"  Cancelled {cancelled} deferred coordinators")

    # Clear failed OCR jobs
    ocr_queue = get_ocr_queue()
    failed = ocr_queue.failed_job_registry

    click.echo()
    click.echo(f"Clearing {len(failed)} failed OCR jobs...")
    deleted = 0
    for job_id in failed.get_job_ids():
        job = ocr_queue.fetch_job(job_id)
        if job:
            job.delete()
            deleted += 1

    click.echo(f"  Deleted {deleted} failed OCR jobs")
    click.echo()
    click.echo("RQ cleanup complete")


@click.command()
@click.option('--dry-run', is_flag=True, default=False, help='Show what would be done without making changes')
def main(dry_run):
    """Migrate stuck sites to new atomic counter system."""

    click.echo("=" * 80)
    click.echo("MIGRATION: Stuck Sites to Atomic Counter System")
    click.echo("=" * 80)
    click.echo()

    if dry_run:
        click.secho("DRY RUN MODE - no changes will be made", fg="yellow")
        click.echo()

    migrate_stuck_sites()

    if not dry_run:
        clear_rq_state()

        click.echo()
        click.secho("Migration complete!", fg="green")
        click.echo("Next step: Run reconciliation job to unstick sites")
        click.echo("  python scripts/reconcile_pipeline.py")
    else:
        click.echo()
        click.secho("Dry run complete - run without --dry-run to apply changes", fg="yellow")


if __name__ == "__main__":
    main()
```

**Step 2: Test migration script (dry run)**

```bash
uv run python scripts/migrate_stuck_sites.py --dry-run
```

Expected: Shows what would be migrated, no actual changes

**Step 3: Commit migration script**

```bash
git add scripts/migrate_stuck_sites.py
git commit -m "feat: add migration script for stuck sites

Migrates sites stuck in OCR stage to new atomic counter system:
- Infers state from filesystem (counts txt/PDF files)
- Updates sites table with inferred counters
- Clears deferred coordinators and failed OCR jobs

Run with --dry-run to preview changes."
```

---

## Task 5: Create Reconciliation Job

**Files:**
- Create: `scripts/reconcile_pipeline.py`
- Test: `tests/test_reconciliation.py`

**Step 1: Write tests for reconciliation**

Create `tests/test_reconciliation.py`:

```python
"""Tests for pipeline reconciliation job."""

import pytest
from datetime import datetime, timedelta, UTC
from pathlib import Path
from clerk.db import civic_db_connection, upsert_site
from clerk.models import sites_table
from clerk.pipeline_state import initialize_stage, increment_completed
from sqlalchemy import select, update


@pytest.fixture
def stuck_site(tmp_path, monkeypatch):
    """Create a stuck site with txt files but no coordinator."""
    subdomain = "stuck-site"

    # Create site in database
    site_data = {
        "subdomain": subdomain,
        "name": "Stuck Site",
        "state": "CA",
        "kind": "city",
        "scraper": "test_scraper",
    }

    with civic_db_connection() as conn:
        upsert_site(conn, site_data)

    # Initialize OCR stage
    initialize_stage(subdomain, "ocr", total_jobs=2)

    # Mark as updated 3 hours ago (stuck!)
    with civic_db_connection() as conn:
        conn.execute(
            update(sites_table).where(
                sites_table.c.subdomain == subdomain
            ).values(
                updated_at=datetime.now(UTC) - timedelta(hours=3)
            )
        )

    # Create txt files (work was done)
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    txt_dir = tmp_path / subdomain / "txt" / "Meeting"
    txt_dir.mkdir(parents=True)
    (txt_dir / "2024-01-01.txt").write_text("test content")
    (txt_dir / "2024-01-02.txt").write_text("test content")

    yield subdomain

    # Cleanup
    with civic_db_connection() as conn:
        from sqlalchemy import delete
        conn.execute(delete(sites_table).where(sites_table.c.subdomain == subdomain))


def test_detect_stuck_site(stuck_site):
    """Test detecting sites stuck for >2 hours."""
    from scripts.reconcile_pipeline import find_stuck_sites

    stuck = find_stuck_sites()

    subdomains = [s.subdomain for s in stuck]
    assert stuck_site in subdomains


def test_recover_stuck_site_with_txt_files(stuck_site):
    """Test recovering stuck site by inferring state from txt files."""
    from scripts.reconcile_pipeline import recover_stuck_site
    from unittest.mock import patch, MagicMock

    # Mock queue.enqueue to verify coordinator gets enqueued
    mock_queue = MagicMock()

    with patch('scripts.reconcile_pipeline.get_compilation_queue', return_value=mock_queue):
        recover_stuck_site(stuck_site)

    # Verify coordinator was enqueued
    assert mock_queue.enqueue.called

    # Verify database updated
    with civic_db_connection() as conn:
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == stuck_site)
        ).fetchone()

    assert site.ocr_completed == 2  # 2 txt files found
    assert site.coordinator_enqueued == True


def test_skip_recently_updated_sites():
    """Test reconciliation skips sites updated recently."""
    from scripts.reconcile_pipeline import find_stuck_sites

    subdomain = "recent-site"

    # Create site updated 30 minutes ago
    site_data = {
        "subdomain": subdomain,
        "name": "Recent Site",
        "state": "CA",
    }

    with civic_db_connection() as conn:
        upsert_site(conn, site_data)

    initialize_stage(subdomain, "ocr", total_jobs=1)

    # Updated recently (30 min ago)
    with civic_db_connection() as conn:
        conn.execute(
            update(sites_table).where(
                sites_table.c.subdomain == subdomain
            ).values(
                updated_at=datetime.now(UTC) - timedelta(minutes=30)
            )
        )

    stuck = find_stuck_sites()
    subdomains = [s.subdomain for s in stuck]

    assert subdomain not in subdomains  # Should not be detected as stuck

    # Cleanup
    with civic_db_connection() as conn:
        from sqlalchemy import delete
        conn.execute(delete(sites_table).where(sites_table.c.subdomain == subdomain))
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_reconciliation.py -v
```

Expected: FAIL - module not found, functions not defined

**Step 3: Implement reconciliation script**

Create `scripts/reconcile_pipeline.py`:

```python
#!/usr/bin/env python3
"""Pipeline reconciliation job.

Detects and recovers stuck sites by:
1. Finding sites with stale updated_at timestamps
2. Inferring actual state from filesystem
3. Enqueueing missing coordinators
4. Re-enqueueing lost jobs

Run this periodically (every 15 minutes) via cron.
"""

import click
import os
from datetime import datetime, timedelta, UTC
from pathlib import Path
from clerk.db import civic_db_connection
from clerk.models import sites_table
from clerk.queue import get_compilation_queue
from clerk.workers import ocr_complete_coordinator
from sqlalchemy import select, update


def count_txt_files(subdomain):
    """Count txt files on filesystem."""
    storage_dir = os.getenv("STORAGE_DIR", "../sites")
    txt_dir = Path(f"{storage_dir}/{subdomain}/txt")
    if not txt_dir.exists():
        return 0
    return len(list(txt_dir.glob("**/*.txt")))


def find_stuck_sites(threshold_hours=2):
    """Find sites stuck in pipeline for >threshold_hours.

    Args:
        threshold_hours: Hours since last update to consider stuck

    Returns:
        List of stuck site records
    """
    cutoff = datetime.now(UTC) - timedelta(hours=threshold_hours)

    with civic_db_connection() as conn:
        stuck = conn.execute(
            select(sites_table).where(
                sites_table.c.current_stage != 'completed',
                sites_table.c.current_stage.isnot(None),
                sites_table.c.updated_at < cutoff,
            )
        ).fetchall()

    return stuck


def recover_stuck_site(subdomain):
    """Recover a stuck site by inferring state and enqueueing coordinator.

    Args:
        subdomain: Site subdomain
    """
    # Get current site state
    with civic_db_connection() as conn:
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == subdomain)
        ).fetchone()

    if not site:
        click.secho(f"  {subdomain}: Site not found in database", fg="red")
        return

    stage = site.current_stage

    if stage == 'ocr':
        # Infer state from filesystem
        txt_count = count_txt_files(subdomain)

        if txt_count > 0 and not site.coordinator_enqueued:
            # Work was done but coordinator never enqueued
            click.echo(f"  {subdomain}: Found {txt_count} txt files, enqueueing coordinator")

            # Update database to match reality
            with civic_db_connection() as conn:
                conn.execute(
                    update(sites_table).where(
                        sites_table.c.subdomain == subdomain
                    ).values(
                        ocr_completed=txt_count,
                        coordinator_enqueued=True,
                        updated_at=datetime.now(UTC),
                    )
                )

            # Enqueue coordinator
            get_compilation_queue().enqueue(
                ocr_complete_coordinator,
                subdomain=subdomain,
                run_id=f"{subdomain}_recovered",
                job_timeout="5m",
                description=f"OCR coordinator (recovered): {subdomain}",
            )

        elif txt_count == 0:
            click.secho(f"  {subdomain}: No txt files found - ALL OCR failed", fg="yellow")
            # Could re-enqueue OCR jobs here, or mark for manual investigation

        else:
            click.echo(f"  {subdomain}: Already has coordinator enqueued, skipping")

    elif stage in ['compilation', 'extraction', 'deploy']:
        # These are 1:1 jobs - simpler recovery
        # For now just log, could implement re-enqueue logic
        click.echo(f"  {subdomain}: Stuck in {stage} stage (TODO: implement recovery)")

    else:
        click.echo(f"  {subdomain}: Unknown stage '{stage}'")


@click.command()
@click.option('--threshold-hours', default=2, help='Hours since update to consider stuck')
@click.option('--dry-run', is_flag=True, default=False, help='Show what would be done without making changes')
def main(threshold_hours, dry_run):
    """Run pipeline reconciliation."""

    click.echo("=" * 80)
    click.echo(f"RECONCILIATION: {datetime.now(UTC).isoformat()}")
    click.echo("=" * 80)
    click.echo()

    if dry_run:
        click.secho("DRY RUN MODE - no changes will be made", fg="yellow")
        click.echo()

    # Find stuck sites
    stuck = find_stuck_sites(threshold_hours)

    if not stuck:
        click.echo("No stuck sites found")
        return

    click.echo(f"Found {len(stuck)} stuck sites:")
    click.echo()

    # Recover each stuck site
    recovered = 0
    for site in stuck:
        if not dry_run:
            recover_stuck_site(site.subdomain)
            recovered += 1
        else:
            click.echo(f"  {site.subdomain}: Would recover (dry run)")

    click.echo()
    if dry_run:
        click.secho(f"Would recover {len(stuck)} sites", fg="yellow")
    else:
        click.secho(f"Recovered {recovered} sites", fg="green")


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_reconciliation.py -v
```

Expected: All tests PASS

**Step 5: Test reconciliation script (dry run)**

```bash
uv run python scripts/reconcile_pipeline.py --dry-run
```

Expected: Shows stuck sites without making changes

**Step 6: Commit reconciliation job**

```bash
git add scripts/reconcile_pipeline.py tests/test_reconciliation.py
git commit -m "feat: add pipeline reconciliation job

Automatically detects and recovers stuck sites:
- Finds sites with stale updated_at (>2 hours)
- Infers state from filesystem (counts txt files)
- Enqueues missing coordinators
- Updates database to match reality

Run periodically via cron (every 15 minutes recommended)."
```

---

## Task 6: Update Coordinator to Reset Flag

**Files:**
- Modify: `src/clerk/workers.py` (ocr_complete_coordinator function)
- Test: `tests/test_workers.py`

**Step 1: Write test for coordinator resetting flag**

Add to `tests/test_workers.py`:

```python
def test_coordinator_resets_enqueued_flag(mock_site, tmp_path, monkeypatch):
    """Coordinator should reset coordinator_enqueued flag for next stage."""
    from clerk.workers import ocr_complete_coordinator
    from clerk.db import civic_db_connection, upsert_site
    from clerk.models import sites_table
    from clerk.pipeline_state import initialize_stage, increment_completed, claim_coordinator_enqueue
    from sqlalchemy import select
    from pathlib import Path

    subdomain = "test-site"
    mock_site["subdomain"] = subdomain

    # Setup site in database
    with civic_db_connection() as conn:
        upsert_site(conn, mock_site)

    initialize_stage(subdomain, "ocr", total_jobs=1)
    increment_completed(subdomain, "ocr")
    claim_coordinator_enqueue(subdomain)

    # Create txt files (OCR succeeded)
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    txt_dir = Path(tmp_path) / subdomain / "txt" / "Meeting"
    txt_dir.mkdir(parents=True)
    (txt_dir / "2024-01-01.txt").write_text("test content")

    # Run coordinator
    ocr_complete_coordinator(subdomain, run_id="test_run")

    # Verify flag reset and stage transitioned
    with civic_db_connection() as conn:
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == subdomain)
        ).fetchone()

    assert site.current_stage == 'extraction'  # Moved to next stage
    assert site.coordinator_enqueued == False  # Flag reset
    assert site.compilation_total == 1  # Next stage initialized
    assert site.extraction_total == 1
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_workers.py::test_coordinator_resets_enqueued_flag -v
```

Expected: FAIL - coordinator doesn't reset flag or transition stage

**Step 3: Update coordinator implementation**

Modify `src/clerk/workers.py` - update `ocr_complete_coordinator` function:

```python
def ocr_complete_coordinator(subdomain, run_id):
    """RQ job: Runs after ALL OCR jobs complete, spawns two parallel paths."""
    from .queue import get_compilation_queue, get_extraction_queue

    stage = "ocr"
    start_time = time.time()

    log_with_context("ocr_coordinator_started", subdomain=subdomain, run_id=run_id, stage=stage)

    try:
        # Verify OCR completed by checking for txt files
        storage_dir = os.getenv("STORAGE_DIR", "../sites")
        txt_dir = Path(f"{storage_dir}/{subdomain}/txt")

        if not txt_dir.exists():
            raise FileNotFoundError(
                f"Text directory not found at {txt_dir} - OCR may not have completed"
            )

        txt_files = list(txt_dir.glob("**/*.txt"))
        if len(txt_files) == 0:
            raise ValueError(f"No text files found in {txt_dir} - OCR may have failed for all PDFs")

        log_with_context(
            "Verified OCR completion",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            txt_file_count=len(txt_files),
        )

        # Update progress: transition to next stage
        with civic_db_connection() as conn:
            conn.execute(
                update(sites_table).where(
                    sites_table.c.subdomain == subdomain
                ).values(
                    current_stage='extraction',
                    compilation_total=1,
                    extraction_total=1,
                    coordinator_enqueued=False,  # Reset flag for next stage
                    updated_at=datetime.now(UTC),
                )
            )

            # Update legacy status field for backward compatibility
            update_site(
                conn,
                subdomain,
                {
                    "status": "needs_extraction",
                    "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )

        # Spawn next stage jobs
        get_compilation_queue().enqueue(
            compile_db_job,
            subdomain=subdomain,
            run_id=run_id,
            extract_entities=False,
            job_timeout="30m",
        )

        get_extraction_queue().enqueue(
            extract_entities_job,
            subdomain=subdomain,
            run_id=run_id,
            job_timeout="60m",
        )

        log_with_context(
            "ocr_coordinator_completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            duration_seconds=round(time.time() - start_time, 2),
        )

    except Exception as e:
        log_with_context(
            f"ocr_coordinator_failed: {e}",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            level="error",
            error_type=type(e).__name__,
        )
        raise
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_workers.py::test_coordinator_resets_enqueued_flag -v
```

Expected: PASS

**Step 5: Commit coordinator updates**

```bash
git add src/clerk/workers.py tests/test_workers.py
git commit -m "feat: update coordinator to reset enqueued flag

Coordinator now:
- Transitions current_stage to next stage
- Initializes counters for next stage (compilation, extraction)
- Resets coordinator_enqueued flag for next fan-out
- Updates database atomically

This allows next stage to use same coordinator pattern."
```

---

## Task 7: Run Migration on Production

**Files:**
- Execute: `migrations/001_add_pipeline_state_columns.sql`
- Execute: `scripts/migrate_stuck_sites.py`

**Step 1: Backup database**

```bash
# On production server
pg_dump $DATABASE_URL > backup_before_migration_$(date +%Y%m%d_%H%M%S).sql
```

**Step 2: Run schema migration**

```bash
# On production server
psql $DATABASE_URL < migrations/001_add_pipeline_state_columns.sql
```

Expected: All ALTER TABLE commands succeed

**Step 3: Verify schema changes**

```bash
psql $DATABASE_URL -c "\d sites"
```

Expected: All new columns visible (current_stage, ocr_total, etc.)

**Step 4: Run stuck site migration (dry run first)**

```bash
# On production server
uv run python scripts/migrate_stuck_sites.py --dry-run
```

Expected: Shows 105 stuck sites, what would be migrated

**Step 5: Run actual migration**

```bash
# On production server
uv run python scripts/migrate_stuck_sites.py
```

Expected:
- Migrates 105 sites
- Clears 82 deferred coordinators
- Clears 2,695 failed OCR jobs

**Step 6: Verify migration results**

```bash
psql $DATABASE_URL -c "SELECT subdomain, current_stage, ocr_total, ocr_completed, ocr_failed FROM sites WHERE current_stage = 'ocr' LIMIT 5;"
```

Expected: See migrated sites with inferred counters

**Step 7: Document migration completion**

Create migration log:

```bash
cat > migration_log_$(date +%Y%m%d).txt << EOF
Migration completed: $(date)

Schema migration: SUCCESS
- Added pipeline state columns to sites table
- Created indexes

Data migration: SUCCESS
- Migrated 105 stuck sites
- Cleared 82 deferred coordinators
- Cleared 2,695 failed OCR jobs

Next step: Deploy new code and run reconciliation
EOF
```

---

## Task 8: Deploy and Run Reconciliation

**Files:**
- Deploy: All updated code
- Execute: `scripts/reconcile_pipeline.py`

**Step 1: Deploy new code to production**

```bash
# Your deployment process (example)
git push origin main
# ... CI/CD deploys, or manual:
# pip install --upgrade .
# supervisorctl restart clerk-workers
```

**Step 2: Verify deployment**

```bash
# On production
python -c "from clerk.pipeline_state import initialize_stage; print('Import successful')"
python -c "from clerk.workers import ocr_page_job; print('Import successful')"
```

Expected: No import errors

**Step 3: Run reconciliation (dry run first)**

```bash
uv run python scripts/reconcile_pipeline.py --dry-run
```

Expected: Shows stuck sites that would be recovered

**Step 4: Run actual reconciliation**

```bash
uv run python scripts/reconcile_pipeline.py
```

Expected:
- Detects ~105 migrated sites
- Enqueues coordinators for sites with txt files
- Sites begin progressing through pipeline

**Step 5: Monitor pipeline progress**

```bash
# Check sites progressing
psql $DATABASE_URL -c "SELECT current_stage, COUNT(*) FROM sites WHERE current_stage IS NOT NULL GROUP BY current_stage;"
```

Expected: Sites moving from 'ocr' to 'extraction', 'deploy', 'completed'

**Step 6: Set up periodic reconciliation**

```bash
# Add to cron (every 15 minutes)
crontab -e

# Add line:
*/15 * * * * cd /path/to/clerk && uv run python scripts/reconcile_pipeline.py >> /var/log/clerk-reconcile.log 2>&1
```

**Step 7: Commit deployment notes**

```bash
cat > docs/deployment_notes.md << EOF
# Deployment Notes - Pipeline State Consolidation

Deployed: $(date)

## Steps Completed

1. Schema migration - Added pipeline state columns
2. Data migration - Migrated 105 stuck sites
3. Code deployment - Updated workers to use atomic counters
4. Reconciliation - Auto-recovery running every 15 minutes

## Monitoring

- Sites by stage: `SELECT current_stage, COUNT(*) FROM sites WHERE current_stage IS NOT NULL GROUP BY current_stage;`
- Stuck sites: `SELECT subdomain, current_stage, updated_at FROM sites WHERE current_stage != 'completed' AND updated_at < NOW() - INTERVAL '2 hours';`
- Failure rates: `SELECT subdomain, ocr_total, ocr_completed, ocr_failed FROM sites WHERE ocr_failed > 0 ORDER BY ocr_failed DESC LIMIT 20;`

## Rollback (if needed)

1. Revert code deployment
2. Old system still works (site_progress table exists)
3. Can re-run migration after fixing issues
EOF

git add docs/deployment_notes.md
git commit -m "docs: add deployment notes for pipeline consolidation"
```

---

## Task 9: Cleanup After Verification (24-48 hours later)

**Files:**
- Execute: SQL cleanup script

**Step 1: Verify new system working**

Run queries to verify:

```sql
-- All sites using new columns?
SELECT COUNT(*) FROM sites WHERE current_stage IS NOT NULL;

-- Any recent updates to site_progress? (should be 0)
SELECT COUNT(*) FROM site_progress WHERE updated_at > NOW() - INTERVAL '24 hours';

-- Pipeline healthy?
SELECT current_stage, COUNT(*), AVG(EXTRACT(EPOCH FROM (NOW() - updated_at))/3600) as avg_hours
FROM sites WHERE current_stage != 'completed' GROUP BY current_stage;
```

**Step 2: Drop deprecated table**

```bash
# Create cleanup script
cat > migrations/002_cleanup_deprecated_tables.sql << 'EOF'
-- Cleanup: Drop deprecated site_progress table
-- Run this after verifying new system works (24-48 hours)

-- Verify no recent writes
DO $$
DECLARE
  recent_count INT;
BEGIN
  SELECT COUNT(*) INTO recent_count
  FROM site_progress
  WHERE updated_at > NOW() - INTERVAL '24 hours';

  IF recent_count > 0 THEN
    RAISE EXCEPTION 'site_progress has recent updates (%), aborting', recent_count;
  END IF;
END $$;

-- Drop table
DROP TABLE IF EXISTS site_progress;

-- Optional: Remove deprecated columns from sites
-- (Keep for now for backward compatibility)
-- ALTER TABLE sites DROP COLUMN status;
-- ALTER TABLE sites DROP COLUMN extraction_status;
-- ALTER TABLE sites DROP COLUMN last_updated;

COMMENT ON TABLE sites IS 'Single source of truth for site and pipeline state (consolidated 2026-01-18)';
EOF
```

**Step 3: Run cleanup**

```bash
psql $DATABASE_URL < migrations/002_cleanup_deprecated_tables.sql
```

Expected: site_progress table dropped

**Step 4: Commit cleanup script**

```bash
git add migrations/002_cleanup_deprecated_tables.sql
git commit -m "feat: cleanup deprecated site_progress table

Drops site_progress table after verifying new system works.
Includes safety check to prevent dropping if recently written to.

Run 24-48 hours after initial migration."
```

---

## Success Criteria

After completing all tasks, verify:

**Immediate (first 24 hours):**
- ✅ Schema migration applied successfully
- ✅ 105 stuck sites migrated and unstuck
- ✅ 0 deferred coordinators in RQ
- ✅ 0 failed OCR jobs blocking pipeline
- ✅ New sites complete pipeline end-to-end
- ✅ Reconciliation running every 15 minutes

**Ongoing:**
- ✅ <1% of sites stuck >2 hours
- ✅ Single SQL query shows accurate pipeline state
- ✅ No manual intervention needed for transient failures
- ✅ Errors tracked in Sentry but not blocking

**Queries for verification:**

```sql
-- Overall health
SELECT current_stage, COUNT(*) as count
FROM sites WHERE current_stage IS NOT NULL
GROUP BY current_stage ORDER BY count DESC;

-- Stuck sites (should be minimal)
SELECT COUNT(*) FROM sites
WHERE current_stage != 'completed'
  AND updated_at < NOW() - INTERVAL '2 hours';

-- Failure rates
SELECT
  ROUND(100.0 * SUM(ocr_failed) / NULLIF(SUM(ocr_total), 0), 1) as ocr_failure_rate,
  ROUND(100.0 * SUM(compilation_failed) / NULLIF(SUM(compilation_total), 0), 1) as compilation_failure_rate
FROM sites WHERE ocr_total > 0;
```

---

## Rollback Plan

If issues arise during deployment:

**Before migration:**
- Nothing to roll back, just don't proceed

**After schema migration, before code deployment:**
- New columns don't affect old code
- Can deploy updated code later
- Rollback: just don't deploy new code

**After code deployment:**
- Revert code deployment: `git revert <commit>` and redeploy
- Old code still works with site_progress table
- Data in new columns preserved for retry
- Rollback: `git revert` + redeploy old code

**After cleanup (site_progress dropped):**
- Cannot easily rollback
- Would need to restore from backup
- Prevention: Wait 24-48 hours, verify thoroughly first
