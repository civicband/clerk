"""RQ worker job functions."""

import os
from pathlib import Path
from .db import civic_db_connection, get_site_by_subdomain
from .queue_db import (
    update_site_progress,
    increment_stage_progress,
    track_job,
    create_site_progress,
)


def fetch_site_job(subdomain, all_years=False, all_agendas=False):
    """RQ job: Fetch PDFs for a site then spawn OCR jobs.

    Args:
        subdomain: Site subdomain
        all_years: Fetch all years (default: False)
        all_agendas: Fetch all agendas (default: False)
    """
    from .cli import get_fetcher, fetch_internal
    from .queue import get_ocr_queue, get_extraction_queue

    # Get site data
    with civic_db_connection() as conn:
        site = get_site_by_subdomain(conn, subdomain)

    if not site:
        raise ValueError(f"Site not found: {subdomain}")

    # Update progress to fetch stage
    with civic_db_connection() as conn:
        create_site_progress(conn, subdomain, 'fetch')

    # Perform fetch using existing logic
    fetcher = get_fetcher(site, all_years=all_years, all_agendas=all_agendas)
    fetch_internal(subdomain, fetcher)

    # Count PDFs that need OCR
    storage_dir = os.getenv('STORAGE_DIR', '../sites')
    pdf_dir = Path(f"{storage_dir}/{subdomain}/pdfs")
    pdf_files = list(pdf_dir.glob("**/*.pdf")) if pdf_dir.exists() else []

    # Update progress: moving to OCR stage
    with civic_db_connection() as conn:
        update_site_progress(conn, subdomain, stage='ocr', stage_total=len(pdf_files))

    # Spawn OCR jobs (fan-out)
    ocr_queue = get_ocr_queue()
    ocr_job_ids = []

    ocr_backend = os.getenv('DEFAULT_OCR_BACKEND', 'tesseract')

    for pdf_path in pdf_files:
        job = ocr_queue.enqueue(
            ocr_page_job,
            subdomain=subdomain,
            pdf_path=str(pdf_path),
            backend=ocr_backend,
            job_timeout='10m',
            description=f'OCR ({ocr_backend}): {pdf_path.name}'
        )
        ocr_job_ids.append(job.id)

        # Track in PostgreSQL
        with civic_db_connection() as conn:
            track_job(conn, job.id, subdomain, 'ocr-page', 'ocr')

    # Spawn coordinator job that waits for ALL OCR jobs (fan-in)
    if ocr_job_ids:
        extraction_queue = get_extraction_queue()
        coord_job = extraction_queue.enqueue(
            ocr_complete_coordinator,
            subdomain=subdomain,
            depends_on=ocr_job_ids,  # RQ waits for ALL
            job_timeout='5m',
            description=f'OCR coordinator: {subdomain}'
        )

        # Track coordinator job
        with civic_db_connection() as conn:
            track_job(conn, coord_job.id, subdomain, 'ocr-coordinator', 'ocr')


def ocr_page_job(subdomain, pdf_path, backend='tesseract'):
    """RQ job: OCR a single PDF page.

    Args:
        subdomain: Site subdomain
        pdf_path: Path to PDF file
        backend: OCR backend (tesseract or vision)
    """
    from .cli import get_fetcher

    # Get site to create a fetcher instance
    with civic_db_connection() as conn:
        site = get_site_by_subdomain(conn, subdomain)

    if not site:
        raise ValueError(f"Site not found: {subdomain}")

    # Create fetcher instance to use its OCR methods
    fetcher = get_fetcher(site)

    # Parse PDF path to extract meeting and date
    # Expected path format: {storage_dir}/{subdomain}/pdfs/{meeting}/{date}.pdf
    path_obj = Path(pdf_path)
    date = path_obj.stem  # filename without .pdf
    meeting = path_obj.parent.name

    # Determine prefix based on path
    prefix = ""
    if "/_agendas/" in str(pdf_path):
        prefix = "/_agendas"

    # Create job tuple for do_ocr_job
    job = (prefix, meeting, date)

    # Create minimal manifest (we don't need it for individual jobs)
    from .ocr_utils import FailureManifest
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        manifest_path = f.name
    manifest = FailureManifest(manifest_path)

    try:
        # Run OCR job
        import time
        job_id = f"worker_ocr_{int(time.time())}"
        fetcher.do_ocr_job(job, manifest, job_id, backend=backend)
    finally:
        manifest.close()
        # Clean up temp manifest
        try:
            os.unlink(manifest_path)
        except OSError:
            pass

    # Increment progress counter
    with civic_db_connection() as conn:
        increment_stage_progress(conn, subdomain)


def ocr_complete_coordinator(subdomain):
    """RQ job: Runs after ALL OCR jobs complete, spawns extraction.

    This coordinator only runs when all OCR job dependencies succeed.

    Args:
        subdomain: Site subdomain
    """
    from .queue import get_extraction_queue

    # Update progress: moving to extraction stage
    with civic_db_connection() as conn:
        update_site_progress(conn, subdomain, stage='extraction')

    # Spawn extraction job
    extraction_queue = get_extraction_queue()
    job = extraction_queue.enqueue(
        extraction_job,
        subdomain=subdomain,
        job_timeout='2h',
        description=f'Extract entities: {subdomain}'
    )

    # Track in PostgreSQL
    with civic_db_connection() as conn:
        track_job(conn, job.id, subdomain, 'extract-site', 'extraction')


def extraction_job(subdomain):
    """RQ job: Extract entities from text files.

    Args:
        subdomain: Site subdomain
    """
    from .utils import build_db_from_text_internal
    from .queue import get_deploy_queue

    # Count text files to process
    storage_dir = os.getenv('STORAGE_DIR', '../sites')
    txt_dir = Path(f"{storage_dir}/{subdomain}/txt")
    txt_files = list(txt_dir.glob("**/*.txt")) if txt_dir.exists() else []

    # Update progress: processing extraction
    with civic_db_connection() as conn:
        update_site_progress(conn, subdomain, stage='extraction', stage_total=len(txt_files))

    # Use existing extraction logic
    build_db_from_text_internal(subdomain, extract_entities=True, ignore_cache=False)

    # Update progress: moving to deploy stage
    with civic_db_connection() as conn:
        update_site_progress(conn, subdomain, stage='deploy', stage_total=1)

    # Spawn deploy job
    deploy_queue = get_deploy_queue()
    job = deploy_queue.enqueue(
        deploy_job,
        subdomain=subdomain,
        job_timeout='10m',
        description=f'Deploy: {subdomain}'
    )

    # Track in PostgreSQL
    with civic_db_connection() as conn:
        track_job(conn, job.id, subdomain, 'deploy-site', 'deploy')


def deploy_job(subdomain):
    """RQ job: Deploy site.

    Args:
        subdomain: Site subdomain
    """
    from .utils import pm

    # Use existing deploy logic
    pm.hook.deploy_municipality(subdomain=subdomain)

    # Mark complete
    with civic_db_connection() as conn:
        update_site_progress(conn, subdomain, stage='completed', stage_total=1)
        increment_stage_progress(conn, subdomain)
