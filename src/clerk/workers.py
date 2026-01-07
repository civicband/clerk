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


def fetch_site_job(site_id, all_years=False, all_agendas=False):
    """RQ job: Fetch PDFs for a site.

    Args:
        site_id: Site subdomain
        all_years: Fetch all years (default: False)
        all_agendas: Fetch all agendas (default: False)
    """
    # TODO: Implement in Task 10
    pass


def ocr_page_job(site_id, pdf_path, backend='tesseract'):
    """RQ job: OCR a single PDF page.

    Args:
        site_id: Site subdomain
        pdf_path: Path to PDF file
        backend: OCR backend (tesseract or vision)
    """
    # TODO: Implement in Task 11
    pass


def ocr_complete_coordinator(site_id):
    """RQ job: Coordinator that runs after all OCR jobs complete.

    Args:
        site_id: Site subdomain
    """
    # TODO: Implement in Task 12
    pass


def extraction_job(site_id):
    """RQ job: Extract entities from text files.

    Args:
        site_id: Site subdomain
    """
    # TODO: Implement in Task 12
    pass


def deploy_job(site_id):
    """RQ job: Deploy site.

    Args:
        site_id: Site subdomain
    """
    # TODO: Implement in Task 12
    pass
