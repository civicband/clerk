"""RQ worker job functions."""

import os
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

from rq.utils import parse_timeout
from sqlalchemy import select, update

from .db import civic_db_connection, get_site_by_subdomain, update_site
from .fetcher import Fetcher, get_fetcher
from .models import sites_table
from .output import ClerkLogger
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
    track_jobs_bulk,
    update_site_progress,
)
from .settings import get_env


def fetch_site_job(
    subdomain,
    run_id,
    all_years=False,
    all_agendas=False,
    ocr_backend=None,
    proceed=True,
    skip_fetch=False,
):
    """RQ job: Fetch PDFs for a site then spawn OCR jobs.

    Args:
        subdomain: Site subdomain
        run_id: Pipeline run identifier
        all_years: Fetch all years (default: False)
        all_agendas: Fetch all agendas (default: False)
        ocr_backend: OCR backend to use (tesseract or vision). Defaults to DEFAULT_OCR_BACKEND env var.
    """
    from .cli import fetch_internal

    stage = "fetch"
    start_time = time.time()

    logger = ClerkLogger(subdomain=subdomain, run_id=run_id, backend=ocr_backend, stage=stage)

    logger.log(
        "fetch_started",
        all_years=all_years,
        all_agendas=all_agendas,
    )

    try:
        # Get site data
        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, subdomain)

        if not site:
            logger.log("Site not found", stage=stage, level="error")
            raise ValueError(f"Site not found: {subdomain}")

        logger.log(
            "Found site",
            scraper=site.get("scraper"),
        )

        fetcher: Fetcher = get_fetcher(site, all_years=all_years, all_agendas=all_agendas)

        if not skip_fetch:
            # Update progress to fetch stage
            with civic_db_connection() as conn:
                create_site_progress(conn, subdomain, "fetch")
            logger.log("Created fetch progress", stage=stage)

            # Perform fetch using existing logic
            logger.log("Starting PDF fetch", stage=stage)
            fetch_internal(subdomain, fetcher)
            logger.log("Completed PDF fetch", stage=stage)

        pdf_file_count = 0
        if proceed:
            pdf_file_count = queue_ocr(fetcher, run_id, stage, ocr_backend, proceed)

        duration = time.time() - start_time
        logger.log(
            "fetch_completed",
            duration_seconds=round(duration, 2),
            total_pdfs=pdf_file_count,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.log(
            f"fetch_failed: {e}",
            level="error",
            duration_seconds=round(duration, 2),
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc(),
        )
        raise


def queue_ocr(fetcher, run_id, stage, ocr_backend, proceed=True) -> int:
    from .queue import get_ocr_queue

    pdf_files = []

    minutes_dir: Path = Path(fetcher.minutes_output_dir)
    agendas_dir: Path = Path(fetcher.agendas_output_dir)

    logger = ClerkLogger(
        subdomain=fetcher.subdomain, run_id=run_id, backend=ocr_backend, stage=stage
    )

    # Collect minutes PDFs
    if minutes_dir.exists():
        minutes_pdfs = list(minutes_dir.glob("**/*.pdf"))
        logger.log(
            "Found minutes PDFs",
            count=len(minutes_pdfs),
            directory=str(fetcher.minutes_output_dir),
        )
        pdf_files.extend(minutes_pdfs)
    else:
        logger.log("Minutes PDF directory does not exist: %s", fetcher.minutes_output_dir)

    # Collect agenda PDFs
    if agendas_dir.exists():
        agendas_pdfs = list(agendas_dir.glob("**/*.pdf"))
        logger.log(
            "Found agenda PDFs",
            count=len(agendas_pdfs),
            directory=str(fetcher.agendas_output_dir),
        )
        pdf_files.extend(agendas_pdfs)
    else:
        logger.log("Agendas PDF directory does not exist: %s", fetcher.agendas_output_dir)

    logger.log(
        "Total PDFs found for OCR",
        total_pdfs=len(pdf_files),
    )

    # Verify fetch produced PDFs
    if len(pdf_files) == 0:
        logger.log(
            "WARNING: No PDFs found after fetch - site may have no documents or fetch failed",
            level="warning",
            minutes_dir_exists=minutes_dir.exists(),
            agendas_dir_exists=agendas_dir.exists(),
        )

    # Update progress: moving to OCR stage
    with civic_db_connection() as conn:
        update_site_progress(conn, fetcher.subdomain, stage="ocr", stage_total=len(pdf_files))
        # Update legacy status field for backward compatibility
        update_site(
            conn,
            fetcher.subdomain,
            {
                "status": "needs_ocr",
                "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
    logger.stage = "ocr"
    logger.log("Updated progress to OCR stage", ocr_stage_total=len(pdf_files))

    # Spawn OCR jobs (fan-out)
    ocr_queue = get_ocr_queue()

    # Use parameter if provided, otherwise fall back to environment variable
    if ocr_backend is None:
        ocr_backend = get_env("DEFAULT_OCR_BACKEND", "tesseract")
    logger.log("Using OCR backend")

    # Allow timeout to be configured via env var, default to 20m
    # Previous default was 10m, which was too short for large/complex PDFs
    ocr_timeout_str = get_env("OCR_JOB_TIMEOUT", "20m")
    ocr_timeout_seconds = parse_timeout(ocr_timeout_str)

    # Phase 1: Prepare all job data (no I/O, just data structure creation)
    job_datas = []
    for pdf_path in pdf_files:
        params = {
            "subdomain": fetcher.subdomain,
            "pdf_path": str(pdf_path),
            "backend": ocr_backend,
            "run_id": run_id,
            "proceed": proceed,
        }
        job_data = ocr_queue.prepare_data(
            ocr_document_job,
            kwargs=params,
            timeout=ocr_timeout_seconds,
            description=f"OCR ({ocr_backend}): {pdf_path}",
        )
        job_datas.append(job_data)

    # Phase 2: Batch enqueue all jobs to RQ in a single Redis pipeline
    # This is much faster than individual enqueue() calls for large batches
    ocr_jobs = ocr_queue.enqueue_many(job_datas) if job_datas else []

    logger.log("Batch enqueued OCR jobs to RQ", job_count=len(ocr_jobs))

    # Phase 3: Atomically update database in a single transaction
    # This prevents partial state if DB connection fails mid-operation
    with civic_db_connection() as conn:
        # Update site progress
        update_site_progress(conn, fetcher.subdomain, stage="ocr", stage_total=len(ocr_jobs))

        # Bulk insert all job tracking rows
        track_jobs_bulk(conn, ocr_jobs, fetcher.subdomain, "ocr-page", "ocr")

        # Initialize atomic counters for OCR stage (even if 0 jobs)
        # This ensures the coordinator can trigger immediately for empty stages
        initialize_stage(fetcher.subdomain, stage="ocr", total_jobs=len(ocr_jobs))
    logger.log(
        "Initialized OCR stage with atomic counters",
        total_jobs=len(ocr_jobs),
        has_jobs=len(ocr_jobs) > 0,
    )

    if len(ocr_jobs) == 0:
        logger.log(
            "No PDFs found after fetch - OCR stage initialized with total=0",
            subdomain=fetcher.subdomain,
            run_id=run_id,
            level="warning",
        )
        # Immediately try to enqueue coordinator since (0 completed + 0 failed) == 0 total
        if proceed:
            _attempt_coordinator_enqueue(fetcher.subdomain, "ocr", run_id)

    return len(pdf_files)


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
    logger = ClerkLogger(subdomain=subdomain, stage=stage, run_id=run_id)
    # Check if this is the last job and we should trigger coordinator
    if should_trigger_coordinator(subdomain, stage):
        logger.log("All stage jobs complete, attempting to claim coordinator enqueue")

        # Atomically claim the right to enqueue coordinator (only one job wins)
        if claim_coordinator_enqueue(subdomain):
            logger.log("Successfully claimed coordinator enqueue")

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

            logger.log("Enqueued OCR coordinator job", coordinator_job_id=coord_job.id)
        else:
            logger.log("Coordinator already enqueued by another job")


def ocr_document_job(subdomain, pdf_path, backend="tesseract", run_id=None, proceed=True):
    """RQ job: OCR a single PDF page using atomic counters.

    Args:
        subdomain: Site subdomain
        pdf_path: Path to PDF file
        backend: OCR backend (tesseract or vision)
        run_id: Pipeline run identifier
    """
    import sys
    import traceback

    # Log IMMEDIATELY before any imports that might crash
    try:
        print(f"[EARLY] ocr_document_job starting: {subdomain}, {pdf_path}", file=sys.stderr)
        sys.stderr.flush()
    except Exception:
        pass

    try:
        from rq import get_current_job

        print("[EARLY] imports successful", file=sys.stderr)
        sys.stderr.flush()
    except Exception as e:
        # Crash during import - log with minimal dependencies
        print(f"[EARLY] Import failed: {type(e).__name__}: {e}", file=sys.stderr)
        print(f"[EARLY] Traceback: {traceback.format_exc()}", file=sys.stderr)
        sys.stderr.flush()
        raise

    stage = "ocr"
    start_time = time.time()
    path_obj = Path(pdf_path)

    # Get RQ job ID for correlation with worker logs
    current_job = get_current_job()
    rq_job_id = current_job.id if current_job else "unknown"

    logger = ClerkLogger(subdomain=subdomain, stage=stage, job_id=rq_job_id, backend=backend)

    logger.log("ocr_started", pdf_name=path_obj.name)
    sys.stderr.flush()  # Ensure early log reaches disk

    try:
        # Get site to create a fetcher instance
        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, subdomain)

        if not site:
            logger.log("Site not found in ocr_document_job", level="error", pdf_path=pdf_path)
            raise ValueError(f"Site not found: {subdomain}")

        # Create fetcher instance to use its OCR methods
        fetcher: Fetcher | None = get_fetcher(site)
        logger.log("Created fetcher for subdomain")

        # Parse PDF path to extract meeting and date
        # Expected path format: {storage_dir}/{subdomain}/pdfs/{meeting}/{date}.pdf
        date = path_obj.stem  # filename without .pdf
        meeting = path_obj.parent.name

        # Determine prefix based on path
        prefix = ""
        if "/_agendas/" in str(pdf_path):
            prefix = "/_agendas"

        # Create job tuple for do_ocr_job
        job = (prefix, meeting, date)

        # Run OCR job without manifest (RQ tracks job failures)
        logger.log("Running OCR", pdf_name=path_obj.name)

        # Wrap do_ocr_job in try/except to handle failures gracefully
        try:
            fetcher.do_ocr_job(job, None, rq_job_id, backend=backend, run_id=run_id)  # type: ignore

            duration = time.time() - start_time
            logger.log(
                "ocr_completed",
                pdf_name=path_obj.name,
                duration_seconds=round(duration, 2),
            )

            # Increment completed counter (atomic)
            increment_completed(subdomain, stage)
            logger.log("Incremented completed counter for subdomain")

        except Exception as ocr_error:
            duration = time.time() - start_time
            logger.log(
                f"ocr_failed: {ocr_error}",
                level="error",
                duration_seconds=round(duration, 2),
                pdf_path=pdf_path,
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

        if proceed:
            # Attempt to enqueue coordinator (if all jobs done)
            _attempt_coordinator_enqueue(subdomain, stage, run_id)

    except Exception as e:
        duration = time.time() - start_time
        logger.log(
            f"ocr_job_error: {e}",
            level="error",
            duration_seconds=round(duration, 2),
            pdf_path=pdf_path,
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

        if proceed:
            # Attempt to enqueue coordinator (if all jobs done)
            _attempt_coordinator_enqueue(subdomain, stage, run_id)

        # Don't re-raise - we've already tracked the failure
        # This prevents RQ from marking the job as failed


def ocr_complete_coordinator(subdomain, run_id):
    """RQ job: Runs after ALL OCR jobs complete, spawns database compilation.

    Args:
        subdomain: Site subdomain
        run_id: Pipeline run identifier
    """
    from .queue import get_compilation_queue

    stage = "ocr"
    start_time = time.time()

    logger = ClerkLogger(subdomain=subdomain, run_id=run_id, stage=stage)

    logger.log("ocr_coordinator_started")

    try:
        # Verify OCR completed by checking for txt files
        storage_dir = get_env("STORAGE_DIR", "../sites")
        minutes_txt_dir = Path(f"{storage_dir}/{subdomain}/txt")
        agendas_txt_dir = Path(f"{storage_dir}/{subdomain}/_agendas/txt")

        # Check if this is a "no documents" case (fetch found 0 PDFs)
        with civic_db_connection() as conn:
            site = conn.execute(
                select(sites_table).where(sites_table.c.subdomain == subdomain)
            ).fetchone()

        if site and site.ocr_total == 0:
            # No PDFs were fetched - mark site as completed with error
            logger.log("No documents to process - fetch found 0 PDFs", level="warning")

            with civic_db_connection() as conn:
                conn.execute(
                    update(sites_table)
                    .where(sites_table.c.subdomain == subdomain)
                    .values(
                        current_stage="completed",
                        last_error_stage="fetch",
                        last_error_message="No PDFs found during fetch - site may have no documents or fetch failed",
                        last_error_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
                # Update legacy status
                update_site(
                    conn,
                    subdomain,
                    {
                        "status": "no_documents",
                        "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                    },
                )

            logger.log("Marked site as completed with no_documents status")
            return  # Exit coordinator successfully

        if not minutes_txt_dir.exists() and not agendas_txt_dir.exists():
            raise FileNotFoundError(
                f"Text directoryies not found at {minutes_txt_dir}/{agendas_txt_dir} - OCR may not have completed"
            )

        txt_files = []
        txt_files += list(minutes_txt_dir.glob("**/*.txt"))
        txt_files += list(agendas_txt_dir.glob("**/*.txt"))
        if len(txt_files) == 0:
            raise ValueError(
                f"No text files found in {minutes_txt_dir}/{agendas_txt_dir} - OCR may have failed for all PDFs"
            )

        logger.log("Verified OCR completion", txt_file_count=len(txt_files))

        # Update progress: transition to next stage
        with civic_db_connection() as conn:
            conn.execute(
                update(sites_table)
                .where(sites_table.c.subdomain == subdomain)
                .values(
                    current_stage="compilation",
                    compilation_total=1,
                    coordinator_enqueued=False,  # Reset flag for next stage
                    updated_at=datetime.now(UTC),
                )
            )

            # Update legacy status field for backward compatibility
            update_site(
                conn,
                subdomain,
                {
                    "status": "needs_compilation",
                    "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )
        logger.log("Updated progress to compilation stage", next_stage="compilation")

        compilation_queue = get_compilation_queue()

        db_job = compilation_queue.enqueue(
            db_compilation_job,
            subdomain=subdomain,
            run_id=run_id,
            job_timeout="30m",
            description=f"DB compilation: {subdomain}",
        )

        logger.stage = "compilation"

        # Track in PostgreSQL
        with civic_db_connection() as conn:
            track_job(conn, db_job.id, subdomain, "db-compilation", "compilation")
        logger.log("Enqueued DB compilation job")

        duration = time.time() - start_time
        logger.log("ocr_coordinator_completed", duration_seconds=round(duration, 2))

    except Exception as e:
        duration = time.time() - start_time
        logger.log(
            f"ocr_coordinator_failed: {e}",
            level="error",
            duration_seconds=round(duration, 2),
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc(),
        )
        raise


def db_compilation_job(subdomain, run_id=None):
    """RQ job: Compile database from text files.

    Args:
        subdomain: Site subdomain
        run_id: Pipeline run identifier (optional for backward compatibility)
    """
    from .queue import get_deploy_queue
    from .utils import build_db_from_text_internal

    stage = "compilation"
    start_time = time.time()

    logger = ClerkLogger(subdomain=subdomain, run_id=run_id, stage=stage)

    # Milestone: started
    logger.log("compilation_started")

    try:
        # Count text files to process
        storage_dir = get_env("STORAGE_DIR", "../sites")
        txt_dir = Path(f"{storage_dir}/{subdomain}/txt")

        if txt_dir.exists():
            txt_files = list(txt_dir.glob("**/*.txt"))
            logger.log(
                "Found text files for compilation", count=len(txt_files), directory=str(txt_dir)
            )
        else:
            txt_files = []
            logger.log("Text directory does not exist: %s", str(txt_dir))

        # Update progress counter
        with civic_db_connection() as conn:
            update_site_progress(conn, subdomain, stage="compilation", stage_total=len(txt_files))
        logger.log(f"Updated compilation progress with {len(txt_files)} total files")

        # Build database
        logger.log("Building database", text_file_count=len(txt_files))
        build_db_from_text_internal(subdomain)

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

        logger.log(
            "Completed database build",
            tables_created=table_count,
            db_size_bytes=os.path.getsize(meetings_db_path),
        )

        # Update page count in civic.db from meetings.db
        from .cli import rebuild_site_fts_internal, update_page_count

        logger.log("Updating page count")
        update_page_count(subdomain)

        # Verify page count was updated
        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, subdomain)
            if not site:
                raise ValueError(f"Site {subdomain} not found in civic.db after page count update")

            pages = site.get("pages", 0)
            if pages == 0:
                logger.log("WARNING: Page count is 0 after update", level="warning")

        logger.log("Page count updated", pages=pages)

        # Rebuild full-text search indexes
        logger.log("Rebuilding FTS indexes")
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
        logger.stage = "deploy"
        logger.log("Updated progress to deploy stage")

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
        logger.log("Enqueued deploy job", job_id=job.id)

        # Milestone: completed
        duration = time.time() - start_time
        logger.log(
            "compilation_completed",
            duration_seconds=round(duration, 2),
            text_file_count=len(txt_files),
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.log(
            f"compilation_failed: {e}",
            level="error",
            duration_seconds=round(duration, 2),
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc(),
        )
        raise


def coordinator_job(subdomain, run_id=None):
    """RQ job: Coordinate pipeline stages for a site.

    Args:
        subdomain: Site subdomain
        run_id: Pipeline run identifier
    """
    logger = ClerkLogger(subdomain=subdomain, run_id=run_id)
    logger.log(
        "Running coordinator job",
        subdomain=subdomain,
        run_id=run_id,
    )
    # Placeholder for coordinator logic
    # This would typically orchestrate the pipeline stages
    return {"status": "completed", "subdomain": subdomain, "run_id": run_id}


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

    logger = ClerkLogger(subdomain=subdomain, run_id=run_id, stage=stage)

    logger.log("deploy_started")

    try:
        # Get site data for post_deploy hook
        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, subdomain)

        if not site:
            raise ValueError(f"Site not found: {subdomain}")

        # Use existing deploy logic
        logger.log("Running deploy hook")
        pm.hook.deploy_municipality(subdomain=subdomain)
        logger.log("Completed deploy hook")

        # Mark complete
        with civic_db_connection() as conn:
            update_site_progress(conn, subdomain, stage="completed", stage_total=1)
            increment_stage_progress(conn, subdomain)
            # Update sites.current_stage to completed
            conn.execute(
                update(sites_table)
                .where(sites_table.c.subdomain == subdomain)
                .values(
                    current_stage="completed",
                    updated_at=datetime.now(UTC),
                )
            )
            # Update legacy status field for backward compatibility
            update_site(
                conn,
                subdomain,
                {
                    "status": "deployed",
                    "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )
        logger.log("Marked site as completed")

        # Run post-deploy hook (creates sites.db, uploads to production, updates civic.observer)
        logger.log("Running post_deploy hook")
        pm.hook.post_deploy(site=site)
        logger.log("Completed post_deploy hook")

        # Verify post_deploy created sites.db
        from .utils import STORAGE_DIR

        sites_db_path = f"{STORAGE_DIR}/sites.db"
        if not os.path.exists(sites_db_path):
            logger.log(
                "WARNING: sites.db not found after post_deploy",
                level="warning",
                expected_path=sites_db_path,
            )
        else:
            sites_db_size = os.path.getsize(sites_db_path)
            logger.log("Verified sites.db creation", sites_db_size_bytes=sites_db_size)

        # Verify site is marked as deployed
        with civic_db_connection() as conn:
            deployed_site = get_site_by_subdomain(conn, subdomain)
            if deployed_site and deployed_site.get("status") == "deployed":
                logger.log("Verified deployment status", status=deployed_site.get("status"))
            else:
                logger.log(
                    "WARNING: Site status not 'deployed' after deploy_job",
                    level="warning",
                    actual_status=deployed_site.get("status")
                    if deployed_site
                    else "site_not_found",
                )

        duration = time.time() - start_time
        logger.log("deploy_completed", duration_seconds=round(duration, 2))

    except Exception as e:
        duration = time.time() - start_time
        logger.log(
            f"deploy_failed: {e}",
            level="error",
            duration_seconds=round(duration, 2),
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc(),
        )
        raise


# Backwards compatibility: alias old function name to new name
# This allows RQ workers to process jobs that were enqueued with the old function name
ocr_page_job = ocr_document_job
