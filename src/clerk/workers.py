"""RQ worker job functions."""

import logging
import os
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

from rq import get_current_job
from sqlalchemy import update

from .db import civic_db_connection, get_site_by_subdomain, update_site
from .models import sites_table
from .fetcher import Fetcher
from .output import log as output_log
from .pipeline_state import (
    claim_coordinator_enqueue,
    increment_completed,
    increment_failed,
    initialize_stage,
    should_trigger_coordinator,
)
from .queue_db import (
    create_site_progress,
    increment_stage_progress,
    track_job,
    update_site_progress,
)

logger = logging.getLogger(__name__)


def log_with_context(message, subdomain, run_id=None, stage=None, **kwargs):
    """Log with automatic run_id, stage, job_id context.

    Extracts job_id and parent_job_id from RQ job context automatically.

    Args:
        message: Log message
        subdomain: Site subdomain
        run_id: Pipeline run identifier (optional)
        stage: Pipeline stage (fetch/ocr/compilation/extraction/deploy) (optional)
        **kwargs: Additional structured fields for logging (can override job_id/parent_job_id)
    """
    job = get_current_job()

    # Only extract job_id if not already provided in kwargs (allows logging spawned job IDs)
    if "job_id" not in kwargs:
        kwargs["job_id"] = job.id if job else None

    # Get parent_job_id if this job has a dependency (unless already in kwargs)
    if "parent_job_id" not in kwargs:
        if job and hasattr(job, "dependency_id"):
            kwargs["parent_job_id"] = job.dependency_id  # type: ignore
        else:
            kwargs["parent_job_id"] = None

    output_log(
        message,
        subdomain=subdomain,
        run_id=run_id,
        stage=stage,
        **kwargs,
    )


def fetch_site_job(
    subdomain,
    run_id,
    all_years=False,
    all_agendas=False,
    ocr_backend=None,
    backfill=False,
    skip_fetch=False,
):
    """RQ job: Fetch PDFs for a site then spawn OCR jobs.

    Args:
        subdomain: Site subdomain
        run_id: Pipeline run identifier
        all_years: Fetch all years (default: False)
        all_agendas: Fetch all agendas (default: False)
        ocr_backend: OCR backend to use (tesseract or vision). Defaults to DEFAULT_OCR_BACKEND env var.
        backfill: Whether this is a backfill operation (default: False)
        skip_fetch: Skip the fetch stage and go straight to OCR (default: False)
    """
    from .cli import fetch_internal, get_fetcher
    from .queue import get_ocr_queue

    stage = "fetch"
    start_time = time.time()

    log_with_context(
        "fetch_started",
        subdomain=subdomain,
        run_id=run_id,
        stage=stage,
        all_years=all_years,
        all_agendas=all_agendas,
    )

    try:
        # Get site data
        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, subdomain)

        if not site:
            log_with_context(
                "Site not found", subdomain=subdomain, run_id=run_id, stage=stage, level="error"
            )
            raise ValueError(f"Site not found: {subdomain}")

        log_with_context(
            "Found site",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            scraper=site.get("scraper"),
        )

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

        # Verify fetch produced PDFs
        if len(pdf_files) == 0:
            log_with_context(
                "WARNING: No PDFs found after fetch - site may have no documents or fetch failed",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
                level="warning",
                minutes_dir_exists=minutes_pdf_dir.exists(),
                agendas_dir_exists=agendas_pdf_dir.exists(),
            )

        # Update progress: moving to OCR stage
        with civic_db_connection() as conn:
            update_site_progress(conn, subdomain, stage="ocr", stage_total=len(pdf_files))
            # Update legacy status field for backward compatibility
            update_site(
                conn,
                subdomain,
                {
                    "status": "needs_ocr",
                    "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )
        log_with_context(
            "Updated progress to OCR stage",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            ocr_stage_total=len(pdf_files),
        )

        # Spawn OCR jobs (fan-out)
        ocr_queue = get_ocr_queue()
        ocr_job_ids = []

        # Use parameter if provided, otherwise fall back to environment variable
        if ocr_backend is None:
            ocr_backend = os.getenv("DEFAULT_OCR_BACKEND", "tesseract")
        log_with_context(
            "Using OCR backend",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            backend=ocr_backend,
        )

        for pdf_path in pdf_files:
            job = ocr_queue.enqueue(
                ocr_page_job,
                subdomain=subdomain,
                pdf_path=str(pdf_path),
                backend=ocr_backend,
                run_id=run_id,
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

        # Initialize atomic counters for OCR stage
        if ocr_job_ids:
            initialize_stage(subdomain, stage="ocr", total_jobs=len(ocr_job_ids))
            log_with_context(
                "Initialized OCR stage with atomic counters",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
                total_jobs=len(ocr_job_ids),
            )
        else:
            logger.warning(
                "No OCR jobs to spawn for subdomain=%s - no PDFs found",
                subdomain,
            )

        duration = time.time() - start_time
        log_with_context(
            "fetch_completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            duration_seconds=round(duration, 2),
            total_pdfs=len(pdf_files),
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
            traceback=traceback.format_exc(),
        )
        raise


def _attempt_coordinator_enqueue(subdomain, stage, run_id):
    """Helper to check and enqueue coordinator if all jobs complete.

    This function checks if all jobs in a stage are done (completed + failed == total)
    and atomically claims the right to enqueue the coordinator. Only one job will
    successfully claim and enqueue.

    Args:
        subdomain: Site subdomain
        stage: Pipeline stage (e.g., "ocr")
        run_id: Pipeline run identifier
    """
    # Check if this is the last job and we should trigger coordinator
    if should_trigger_coordinator(subdomain, stage):
        logger.debug("All %s jobs complete, attempting to claim coordinator enqueue", stage)

        # Atomically claim the right to enqueue coordinator (only one job wins)
        if claim_coordinator_enqueue(subdomain):
            log_with_context(
                "Successfully claimed coordinator enqueue",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
            )

            # Enqueue coordinator job
            from .queue import get_compilation_queue

            compilation_queue = get_compilation_queue()
            coord_job = compilation_queue.enqueue(
                ocr_complete_coordinator,
                subdomain=subdomain,
                run_id=run_id,
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
            )
        else:
            log_with_context(
                "Coordinator already enqueued by another job",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
            )


def ocr_page_job(subdomain, pdf_path, backend="tesseract", run_id=None):
    """RQ job: OCR a single PDF page using atomic counters.

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
        "ocr_started",
        subdomain=subdomain,
        run_id=run_id,
        stage=stage,
        pdf_name=path_obj.name,
        backend=backend,
    )

    try:
        # Get site to create a fetcher instance
        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, subdomain)

        if not site:
            log_with_context(
                "Site not found in ocr_page_job",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
                level="error",
                pdf_path=pdf_path,
            )
            raise ValueError(f"Site not found: {subdomain}")

        # Create fetcher instance to use its OCR methods
        fetcher: Fetcher | None = get_fetcher(site)
        logger.debug("Created fetcher for subdomain=%s", subdomain)

        # Parse PDF path to extract meeting and date
        # Expected path format: {storage_dir}/{subdomain}/pdfs/{meeting}/{date}.pdf
        date = path_obj.stem  # filename without .pdf
        meeting = path_obj.parent.name

        # Determine prefix based on path
        prefix = ""
        if "/_agendas/" in str(pdf_path):
            prefix = "/_agendas"
            logger.debug("PDF is an agenda: %s", pdf_path)
        else:
            logger.debug("PDF is a minute: %s", pdf_path)

        # Create job tuple for do_ocr_job
        job = (prefix, meeting, date)
        logger.debug(
            "OCR job tuple: prefix=%s meeting=%s date=%s (subdomain=%s)",
            prefix,
            meeting,
            date,
            subdomain,
        )

        # Run OCR job without manifest (RQ tracks job failures)
        job_id = f"worker_ocr_{int(time.time())}"
        log_with_context(
            "Running OCR",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            ocr_job_id=job_id,
            pdf_name=path_obj.name,
            backend=backend,
        )

        # Wrap do_ocr_job in try/except to handle failures gracefully
        try:
            fetcher.do_ocr_job(job, None, job_id, backend=backend)  # type: ignore

            duration = time.time() - start_time
            log_with_context(
                "ocr_completed",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
                ocr_job_id=job_id,
                pdf_name=path_obj.name,
                duration_seconds=round(duration, 2),
            )

            # Increment completed counter (atomic)
            increment_completed(subdomain, stage)
            logger.debug("Incremented completed counter for subdomain=%s", subdomain)

        except Exception as ocr_error:
            duration = time.time() - start_time
            log_with_context(
                f"ocr_failed: {ocr_error}",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
                level="error",
                duration_seconds=round(duration, 2),
                pdf_path=pdf_path,
                backend=backend,
                error_type=type(ocr_error).__name__,
                error_message=str(ocr_error),
                traceback=traceback.format_exc(),
            )

            # Increment failed counter with error details (atomic)
            increment_failed(
                subdomain,
                stage,
                error_message=str(ocr_error),
                error_class=type(ocr_error).__name__,
            )
            logger.debug("Incremented failed counter for subdomain=%s", subdomain)

        # Attempt to enqueue coordinator (if all jobs done)
        _attempt_coordinator_enqueue(subdomain, stage, run_id)

    except Exception as e:
        duration = time.time() - start_time
        log_with_context(
            f"ocr_job_error: {e}",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            level="error",
            duration_seconds=round(duration, 2),
            pdf_path=pdf_path,
            backend=backend,
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc(),
        )

        # Increment failed counter for setup/infrastructure errors (atomic)
        increment_failed(
            subdomain,
            stage,
            error_message=str(e),
            error_class=type(e).__name__,
        )
        logger.debug("Incremented failed counter for setup error, subdomain=%s", subdomain)

        # Attempt to enqueue coordinator (if all jobs done)
        _attempt_coordinator_enqueue(subdomain, stage, run_id)

        # Don't re-raise - we've already tracked the failure
        # This prevents RQ from marking the job as failed


def ocr_complete_coordinator(subdomain, run_id):
    """RQ job: Runs after ALL OCR jobs complete, spawns two parallel paths.

    This coordinator spawns:
    1. Database compilation WITHOUT entity extraction (fast path) - to compilation queue
    2. Entity extraction job (which spawns db compilation WITH entities after) - to extraction queue

    Args:
        subdomain: Site subdomain
        run_id: Pipeline run identifier
    """
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
        log_with_context(
            "Updated progress to extraction stage",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            next_stage="extraction",
        )

        compilation_queue = get_compilation_queue()
        extraction_queue = get_extraction_queue()

        # Path 1: Database compilation WITHOUT entity extraction (fast path) - core pipeline
        db_job = compilation_queue.enqueue(
            db_compilation_job,
            subdomain=subdomain,
            run_id=run_id,
            extract_entities=False,
            job_timeout="30m",
            description=f"DB compilation (no entities): {subdomain}",
        )

        # Track in PostgreSQL
        with civic_db_connection() as conn:
            track_job(conn, db_job.id, subdomain, "db-compilation-no-entities", "extraction")
        log_with_context(
            "Enqueued DB compilation job (no entities)",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            job_id=db_job.id,
            extract_entities=False,
        )

        # Path 2: Entity extraction job (which will spawn db compilation WITH entities)
        extract_job = extraction_queue.enqueue(
            extraction_job,
            subdomain=subdomain,
            run_id=run_id,
            job_timeout="2h",
            description=f"Extract entities: {subdomain}",
        )

        # Track in PostgreSQL
        with civic_db_connection() as conn:
            track_job(conn, extract_job.id, subdomain, "extract-site", "extraction")
        log_with_context(
            "Enqueued entity extraction job",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            job_id=extract_job.id,
        )

        duration = time.time() - start_time
        log_with_context(
            "ocr_coordinator_completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            duration_seconds=round(duration, 2),
        )

    except Exception as e:
        duration = time.time() - start_time
        log_with_context(
            f"ocr_coordinator_failed: {e}",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            level="error",
            duration_seconds=round(duration, 2),
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc(),
        )
        raise


def db_compilation_job(subdomain, run_id=None, extract_entities=False, ignore_cache=False):
    """RQ job: Compile database from text files.

    Args:
        subdomain: Site subdomain
        run_id: Pipeline run identifier (optional for backward compatibility)
        extract_entities: Whether to include entity extraction (default: False)
        ignore_cache: Whether to ignore cache (default: False)
    """
    from .queue import get_deploy_queue
    from .utils import build_db_from_text_internal

    stage = "compilation"
    start_time = time.time()

    # Milestone: started
    log_with_context(
        "compilation_started",
        subdomain=subdomain,
        run_id=run_id,
        stage=stage,
        extract_entities=extract_entities,
        ignore_cache=ignore_cache,
    )

    try:
        # Count text files to process
        storage_dir = os.getenv("STORAGE_DIR", "../sites")
        txt_dir = Path(f"{storage_dir}/{subdomain}/txt")

        if txt_dir.exists():
            txt_files = list(txt_dir.glob("**/*.txt"))
            log_with_context(
                "Found text files for compilation",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
                count=len(txt_files),
                directory=str(txt_dir),
            )
        else:
            txt_files = []
            logger.warning("Text directory does not exist: %s for subdomain=%s", txt_dir, subdomain)

        # Update progress counter
        with civic_db_connection() as conn:
            update_site_progress(conn, subdomain, stage="extraction", stage_total=len(txt_files))
        logger.debug("Updated extraction progress with %d total files", len(txt_files))

        # Build database
        log_with_context(
            "Building database",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            extract_entities=extract_entities,
            text_file_count=len(txt_files),
        )
        build_db_from_text_internal(
            subdomain, extract_entities=extract_entities, ignore_cache=ignore_cache
        )

        # Verify meetings.db was created
        import sqlite_utils

        from .utils import STORAGE_DIR

        meetings_db_path = f"{STORAGE_DIR}/{subdomain}/meetings.db"
        if not os.path.exists(meetings_db_path):
            raise FileNotFoundError(
                f"meetings.db not found at {meetings_db_path} after compilation"
            )

        # Verify it has data
        meetings_db = sqlite_utils.Database(meetings_db_path)
        table_count = len(meetings_db.table_names())
        if table_count == 0:
            raise ValueError(f"meetings.db created but contains no tables for {subdomain}")

        log_with_context(
            "Completed database build",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            extract_entities=extract_entities,
            tables_created=table_count,
            db_size_bytes=os.path.getsize(meetings_db_path),
        )

        # Update page count in civic.db from meetings.db
        from .cli import rebuild_site_fts_internal, update_page_count

        log_with_context(
            "Updating page count",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
        )
        update_page_count(subdomain)

        # Verify page count was updated
        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, subdomain)
            if not site:
                raise ValueError(f"Site {subdomain} not found in civic.db after page count update")

            pages = site.get("pages", 0)
            if pages == 0:
                log_with_context(
                    "WARNING: Page count is 0 after update",
                    subdomain=subdomain,
                    run_id=run_id,
                    stage=stage,
                    level="warning",
                )

        log_with_context(
            "Page count updated",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            pages=pages,
        )

        # Rebuild full-text search indexes
        log_with_context(
            "Rebuilding FTS indexes",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
        )
        rebuild_site_fts_internal(subdomain)

        # Both paths spawn deploy (may deploy twice - once for fast path, once for entities path)
        # Update progress: moving to deploy stage
        with civic_db_connection() as conn:
            update_site_progress(conn, subdomain, stage="deploy", stage_total=1)
            # Update legacy status field for backward compatibility
            update_site(
                conn,
                subdomain,
                {
                    "status": "needs_deploy",
                    "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )
        log_with_context(
            "Updated progress to deploy stage",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
        )

        # Spawn deploy job
        deploy_queue = get_deploy_queue()
        job = deploy_queue.enqueue(
            deploy_job,
            subdomain=subdomain,
            run_id=run_id,
            job_timeout="10m",
            description=f"Deploy: {subdomain}",
        )

        # Track in PostgreSQL
        with civic_db_connection() as conn:
            track_job(conn, job.id, subdomain, "deploy-site", "deploy")
        log_with_context(
            "Enqueued deploy job",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            deploy_job_id=job.id,
        )

        # Milestone: completed
        duration = time.time() - start_time
        log_with_context(
            "compilation_completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            extract_entities=extract_entities,
            duration_seconds=round(duration, 2),
            text_file_count=len(txt_files),
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
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc(),
        )
        raise


def extraction_job(subdomain, run_id, extract_entities=True, ignore_cache=False):
    """RQ job: Extract entities from text files.

    Args:
        subdomain: Site subdomain
        run_id: Pipeline run identifier
        extract_entities: Whether to extract entities (default: True)
        ignore_cache: Whether to ignore cached entities (default: False)
    """
    from .cli import extract_entities_internal
    from .queue import get_compilation_queue

    stage = "extraction"
    start_time = time.time()

    log_with_context(
        "extraction_started",
        subdomain=subdomain,
        run_id=run_id,
        stage=stage,
        extract_entities=extract_entities,
        ignore_cache=ignore_cache,
    )

    try:
        # Count text files to process
        storage_dir = os.getenv("STORAGE_DIR", "../sites")
        txt_dir = Path(f"{storage_dir}/{subdomain}/txt")

        if txt_dir.exists():
            txt_files = list(txt_dir.glob("**/*.txt"))
            log_with_context(
                "Found text files for extraction",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
                count=len(txt_files),
                directory=str(txt_dir),
            )
        else:
            txt_files = []
            logger.warning(
                "Text directory does not exist: %s for subdomain=%s",
                txt_dir,
                subdomain,
            )

        # Update progress
        with civic_db_connection() as conn:
            update_site_progress(conn, subdomain, stage="extraction", stage_total=len(txt_files))
        logger.debug("Updated extraction progress with %d total files", len(txt_files))

        # Extract entities (this caches them to disk)
        if extract_entities:
            log_with_context(
                "Extracting entities",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
                text_file_count=len(txt_files),
            )
            extract_entities_internal(subdomain)
            log_with_context(
                "Completed entity extraction", subdomain=subdomain, run_id=run_id, stage=stage
            )
        else:
            log_with_context(
                "Skipping entity extraction", subdomain=subdomain, run_id=run_id, stage=stage
            )

        # Spawn database compilation WITH entities (to compilation queue, may run on different machine)
        compilation_queue = get_compilation_queue()
        job = compilation_queue.enqueue(
            db_compilation_job,
            subdomain=subdomain,
            run_id=run_id,
            extract_entities=True,
            job_timeout="30m",
            description=f"DB compilation (with entities): {subdomain}",
        )

        # Track in PostgreSQL
        with civic_db_connection() as conn:
            track_job(conn, job.id, subdomain, "db-compilation-with-entities", "extraction")
        log_with_context(
            "Enqueued DB compilation job (with entities)",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            job_id=job.id,
        )

        duration = time.time() - start_time
        log_with_context(
            "extraction_completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            duration_seconds=round(duration, 2),
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
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc(),
        )
        raise


def deploy_job(subdomain, run_id=None):
    """RQ job: Deploy site.

    Args:
        subdomain: Site subdomain
        run_id: Pipeline run identifier (optional, for logging context)
    """
    from .utils import pm

    stage = "deploy"
    start_time = time.time()

    # Generate run_id if not provided (for backwards compatibility)
    if run_id is None:
        run_id = f"deploy_{subdomain}_{int(time.time())}"

    log_with_context("deploy_started", subdomain=subdomain, run_id=run_id, stage=stage)

    try:
        # Get site data for post_deploy hook
        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, subdomain)

        if not site:
            raise ValueError(f"Site not found: {subdomain}")

        # Use existing deploy logic
        log_with_context("Running deploy hook", subdomain=subdomain, run_id=run_id, stage=stage)
        pm.hook.deploy_municipality(subdomain=subdomain)
        log_with_context("Completed deploy hook", subdomain=subdomain, run_id=run_id, stage=stage)

        # Mark complete
        with civic_db_connection() as conn:
            update_site_progress(conn, subdomain, stage="completed", stage_total=1)
            increment_stage_progress(conn, subdomain)
            # Update legacy status field for backward compatibility
            update_site(
                conn,
                subdomain,
                {
                    "status": "deployed",
                    "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )
        log_with_context(
            "Marked site as completed", subdomain=subdomain, run_id=run_id, stage=stage
        )

        # Run post-deploy hook (creates sites.db, uploads to production, updates civic.observer)
        log_with_context(
            "Running post_deploy hook", subdomain=subdomain, run_id=run_id, stage=stage
        )
        pm.hook.post_deploy(site=site)
        log_with_context(
            "Completed post_deploy hook", subdomain=subdomain, run_id=run_id, stage=stage
        )

        # Verify post_deploy created sites.db
        from .utils import STORAGE_DIR

        sites_db_path = f"{STORAGE_DIR}/sites.db"
        if not os.path.exists(sites_db_path):
            log_with_context(
                "WARNING: sites.db not found after post_deploy",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
                level="warning",
                expected_path=sites_db_path,
            )
        else:
            sites_db_size = os.path.getsize(sites_db_path)
            log_with_context(
                "Verified sites.db creation",
                subdomain=subdomain,
                run_id=run_id,
                stage=stage,
                sites_db_size_bytes=sites_db_size,
            )

        # Verify site is marked as deployed
        with civic_db_connection() as conn:
            deployed_site = get_site_by_subdomain(conn, subdomain)
            if deployed_site and deployed_site.get("status") == "deployed":
                log_with_context(
                    "Verified deployment status",
                    subdomain=subdomain,
                    run_id=run_id,
                    stage=stage,
                    status=deployed_site.get("status"),
                )
            else:
                log_with_context(
                    "WARNING: Site status not 'deployed' after deploy_job",
                    subdomain=subdomain,
                    run_id=run_id,
                    stage=stage,
                    level="warning",
                    actual_status=deployed_site.get("status")
                    if deployed_site
                    else "site_not_found",
                )

        duration = time.time() - start_time
        log_with_context(
            "deploy_completed",
            subdomain=subdomain,
            run_id=run_id,
            stage=stage,
            duration_seconds=round(duration, 2),
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
            traceback=traceback.format_exc(),
        )
        raise
