"""RQ worker job functions."""

import logging
import os
import time
from pathlib import Path

from .db import civic_db_connection, get_site_by_subdomain
from .queue_db import (
    create_site_progress,
    increment_stage_progress,
    track_job,
    update_site_progress,
)

logger = logging.getLogger(__name__)


def fetch_site_job(subdomain, all_years=False, all_agendas=False):
    """RQ job: Fetch PDFs for a site then spawn OCR jobs.

    Args:
        subdomain: Site subdomain
        all_years: Fetch all years (default: False)
        all_agendas: Fetch all agendas (default: False)
    """
    from .cli import fetch_internal, get_fetcher
    from .queue import get_extraction_queue, get_ocr_queue

    logger.info(
        "Starting fetch_site_job subdomain=%s all_years=%s all_agendas=%s",
        subdomain,
        all_years,
        all_agendas,
    )

    # Get site data
    with civic_db_connection() as conn:
        site = get_site_by_subdomain(conn, subdomain)

    if not site:
        logger.error("Site not found: %s", subdomain)
        raise ValueError(f"Site not found: {subdomain}")

    logger.info("Found site: %s (scraper=%s)", subdomain, site.get("scraper"))

    # Update progress to fetch stage
    with civic_db_connection() as conn:
        create_site_progress(conn, subdomain, "fetch")
    logger.info("Created fetch progress for subdomain=%s", subdomain)

    # Perform fetch using existing logic
    fetcher = get_fetcher(site, all_years=all_years, all_agendas=all_agendas)
    logger.info("Starting PDF fetch for subdomain=%s", subdomain)
    fetch_internal(subdomain, fetcher)
    logger.info("Completed PDF fetch for subdomain=%s", subdomain)

    # Count PDFs that need OCR from both minutes and agendas directories
    storage_dir = os.getenv("STORAGE_DIR", "../sites")
    minutes_pdf_dir = Path(f"{storage_dir}/{subdomain}/pdfs")
    agendas_pdf_dir = Path(f"{storage_dir}/{subdomain}/_agendas/pdfs")

    pdf_files = []

    # Collect minutes PDFs
    if minutes_pdf_dir.exists():
        minutes_pdfs = list(minutes_pdf_dir.glob("**/*.pdf"))
        logger.info(
            "Found %d minutes PDFs in %s for subdomain=%s",
            len(minutes_pdfs),
            minutes_pdf_dir,
            subdomain,
        )
        pdf_files.extend(minutes_pdfs)
    else:
        logger.info("Minutes PDF directory does not exist: %s", minutes_pdf_dir)

    # Collect agenda PDFs
    if agendas_pdf_dir.exists():
        agendas_pdfs = list(agendas_pdf_dir.glob("**/*.pdf"))
        logger.info(
            "Found %d agenda PDFs in %s for subdomain=%s",
            len(agendas_pdfs),
            agendas_pdf_dir,
            subdomain,
        )
        pdf_files.extend(agendas_pdfs)
    else:
        logger.info("Agendas PDF directory does not exist: %s", agendas_pdf_dir)

    logger.info(
        "Total PDFs found for OCR: %d (subdomain=%s)",
        len(pdf_files),
        subdomain,
    )

    # Update progress: moving to OCR stage
    with civic_db_connection() as conn:
        update_site_progress(conn, subdomain, stage="ocr", stage_total=len(pdf_files))
    logger.info(
        "Updated progress to OCR stage with %d total PDFs for subdomain=%s",
        len(pdf_files),
        subdomain,
    )

    # Spawn OCR jobs (fan-out)
    ocr_queue = get_ocr_queue()
    ocr_job_ids = []

    ocr_backend = os.getenv("DEFAULT_OCR_BACKEND", "tesseract")
    logger.info("Using OCR backend: %s for subdomain=%s", ocr_backend, subdomain)

    for pdf_path in pdf_files:
        job = ocr_queue.enqueue(
            ocr_page_job,
            subdomain=subdomain,
            pdf_path=str(pdf_path),
            backend=ocr_backend,
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

    logger.info(
        "Enqueued %d OCR jobs for subdomain=%s",
        len(ocr_job_ids),
        subdomain,
    )

    # Spawn coordinator job that waits for ALL OCR jobs (fan-in)
    if ocr_job_ids:
        extraction_queue = get_extraction_queue()
        coord_job = extraction_queue.enqueue(
            ocr_complete_coordinator,
            subdomain=subdomain,
            depends_on=ocr_job_ids,  # RQ waits for ALL
            job_timeout="5m",
            description=f"OCR coordinator: {subdomain}",
        )

        # Track coordinator job
        with civic_db_connection() as conn:
            track_job(conn, coord_job.id, subdomain, "ocr-coordinator", "ocr")

        logger.info(
            "Enqueued OCR coordinator job %s for subdomain=%s (depends_on=%d OCR jobs)",
            coord_job.id,
            subdomain,
            len(ocr_job_ids),
        )
    else:
        logger.warning(
            "No OCR jobs to spawn for subdomain=%s - no PDFs found",
            subdomain,
        )

    logger.info("Completed fetch_site_job for subdomain=%s", subdomain)


def ocr_page_job(subdomain, pdf_path, backend="tesseract"):
    """RQ job: OCR a single PDF page.

    Args:
        subdomain: Site subdomain
        pdf_path: Path to PDF file
        backend: OCR backend (tesseract or vision)
    """
    from .cli import get_fetcher

    logger.info(
        "Starting ocr_page_job subdomain=%s pdf=%s backend=%s",
        subdomain,
        pdf_path,
        backend,
    )

    # Get site to create a fetcher instance
    with civic_db_connection() as conn:
        site = get_site_by_subdomain(conn, subdomain)

    if not site:
        logger.error("Site not found: %s (in ocr_page_job)", subdomain)
        raise ValueError(f"Site not found: {subdomain}")

    # Create fetcher instance to use its OCR methods
    fetcher = get_fetcher(site)
    logger.debug("Created fetcher for subdomain=%s", subdomain)

    # Parse PDF path to extract meeting and date
    # Expected path format: {storage_dir}/{subdomain}/pdfs/{meeting}/{date}.pdf
    path_obj = Path(pdf_path)
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
    logger.info(
        "Running OCR job_id=%s for subdomain=%s pdf=%s",
        job_id,
        subdomain,
        path_obj.name,
    )
    fetcher.do_ocr_job(job, None, job_id, backend=backend)
    logger.info(
        "Completed OCR job_id=%s for subdomain=%s pdf=%s",
        job_id,
        subdomain,
        path_obj.name,
    )

    # Increment progress counter
    with civic_db_connection() as conn:
        increment_stage_progress(conn, subdomain)
    logger.debug("Incremented OCR progress for subdomain=%s", subdomain)


def ocr_complete_coordinator(subdomain):
    """RQ job: Runs after ALL OCR jobs complete, spawns two parallel paths.

    This coordinator spawns:
    1. Database compilation WITHOUT entity extraction (fast path)
    2. Entity extraction job (which spawns db compilation WITH entities after)

    Args:
        subdomain: Site subdomain
    """
    from .queue import get_extraction_queue

    logger.info("Starting ocr_complete_coordinator for subdomain=%s", subdomain)

    # Update progress: moving to extraction stage
    with civic_db_connection() as conn:
        update_site_progress(conn, subdomain, stage="extraction")
    logger.info("Updated progress to extraction stage for subdomain=%s", subdomain)

    extraction_queue = get_extraction_queue()

    # Path 1: Database compilation WITHOUT entity extraction (fast path)
    db_job = extraction_queue.enqueue(
        db_compilation_job,
        subdomain=subdomain,
        extract_entities=False,
        job_timeout="30m",
        description=f"DB compilation (no entities): {subdomain}",
    )

    # Track in PostgreSQL
    with civic_db_connection() as conn:
        track_job(conn, db_job.id, subdomain, "db-compilation-no-entities", "extraction")
    logger.info(
        "Enqueued DB compilation job (no entities) %s for subdomain=%s",
        db_job.id,
        subdomain,
    )

    # Path 2: Entity extraction job (which will spawn db compilation WITH entities)
    extract_job = extraction_queue.enqueue(
        extraction_job,
        subdomain=subdomain,
        job_timeout="2h",
        description=f"Extract entities: {subdomain}",
    )

    # Track in PostgreSQL
    with civic_db_connection() as conn:
        track_job(conn, extract_job.id, subdomain, "extract-site", "extraction")
    logger.info(
        "Enqueued entity extraction job %s for subdomain=%s",
        extract_job.id,
        subdomain,
    )

    logger.info("Completed ocr_complete_coordinator for subdomain=%s", subdomain)


def db_compilation_job(subdomain, extract_entities):
    """RQ job: Compile database from text files.

    Args:
        subdomain: Site subdomain
        extract_entities: Whether to include entity extraction
    """
    from .queue import get_deploy_queue
    from .utils import build_db_from_text_internal

    logger.info(
        "Starting db_compilation_job subdomain=%s extract_entities=%s",
        subdomain,
        extract_entities,
    )

    # Count text files to process
    storage_dir = os.getenv("STORAGE_DIR", "../sites")
    txt_dir = Path(f"{storage_dir}/{subdomain}/txt")

    if txt_dir.exists():
        txt_files = list(txt_dir.glob("**/*.txt"))
        logger.info(
            "Found %d text files in %s for subdomain=%s",
            len(txt_files),
            txt_dir,
            subdomain,
        )
    else:
        txt_files = []
        logger.warning("Text directory does not exist: %s for subdomain=%s", txt_dir, subdomain)

    # Update progress counter
    with civic_db_connection() as conn:
        update_site_progress(conn, subdomain, stage="extraction", stage_total=len(txt_files))
    logger.debug("Updated extraction progress with %d total files", len(txt_files))

    # Build database
    logger.info(
        "Building database for subdomain=%s (extract_entities=%s)",
        subdomain,
        extract_entities,
    )
    build_db_from_text_internal(subdomain, extract_entities=extract_entities, ignore_cache=False)
    logger.info(
        "Completed database build for subdomain=%s (extract_entities=%s)",
        subdomain,
        extract_entities,
    )

    # Both paths complete → spawn deploy
    # Note: In the actual implementation, we would need coordination to ensure
    # both db compilation jobs complete before deploying. For now, the WITH entities
    # path will be the one that triggers deploy since it runs last.
    if extract_entities:
        # Update progress: moving to deploy stage
        with civic_db_connection() as conn:
            update_site_progress(conn, subdomain, stage="deploy", stage_total=1)
        logger.info("Updated progress to deploy stage for subdomain=%s", subdomain)

        # Spawn deploy job
        deploy_queue = get_deploy_queue()
        job = deploy_queue.enqueue(
            deploy_job, subdomain=subdomain, job_timeout="10m", description=f"Deploy: {subdomain}"
        )

        # Track in PostgreSQL
        with civic_db_connection() as conn:
            track_job(conn, job.id, subdomain, "deploy-site", "deploy")
        logger.info("Enqueued deploy job %s for subdomain=%s", job.id, subdomain)

    logger.info(
        "Completed db_compilation_job for subdomain=%s (extract_entities=%s)",
        subdomain,
        extract_entities,
    )


def extraction_job(subdomain):
    """RQ job: Extract entities from text files.

    Args:
        subdomain: Site subdomain
    """
    from .extraction import extract_entities_from_text
    from .queue import get_extraction_queue

    logger.info("Starting extraction_job for subdomain=%s", subdomain)

    # Count text files to process
    storage_dir = os.getenv("STORAGE_DIR", "../sites")
    txt_dir = Path(f"{storage_dir}/{subdomain}/txt")

    if txt_dir.exists():
        txt_files = list(txt_dir.glob("**/*.txt"))
        logger.info(
            "Found %d text files in %s for extraction (subdomain=%s)",
            len(txt_files),
            txt_dir,
            subdomain,
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
    logger.info("Extracting entities for subdomain=%s", subdomain)
    extract_entities_from_text(subdomain)
    logger.info("Completed entity extraction for subdomain=%s", subdomain)

    # Spawn database compilation WITH entities
    extraction_queue = get_extraction_queue()
    job = extraction_queue.enqueue(
        db_compilation_job,
        subdomain=subdomain,
        extract_entities=True,
        job_timeout="30m",
        description=f"DB compilation (with entities): {subdomain}",
    )

    # Track in PostgreSQL
    with civic_db_connection() as conn:
        track_job(conn, job.id, subdomain, "db-compilation-with-entities", "extraction")
    logger.info(
        "Enqueued DB compilation job (with entities) %s for subdomain=%s",
        job.id,
        subdomain,
    )

    logger.info("Completed extraction_job for subdomain=%s", subdomain)


def deploy_job(subdomain):
    """RQ job: Deploy site.

    Args:
        subdomain: Site subdomain
    """
    from .utils import pm

    logger.info("Starting deploy_job for subdomain=%s", subdomain)

    # Use existing deploy logic
    logger.info("Running deploy hook for subdomain=%s", subdomain)
    pm.hook.deploy_municipality(subdomain=subdomain)
    logger.info("Completed deploy hook for subdomain=%s", subdomain)

    # Mark complete
    with civic_db_connection() as conn:
        update_site_progress(conn, subdomain, stage="completed", stage_total=1)
        increment_stage_progress(conn, subdomain)
    logger.info("Marked site as completed for subdomain=%s", subdomain)

    logger.info("Completed deploy_job for subdomain=%s", subdomain)
