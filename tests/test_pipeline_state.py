"""Tests for pipeline state management helpers."""


import pytest

from clerk.db import civic_db_connection
from clerk.models import sites_table
from clerk.pipeline_state import (
    claim_coordinator_enqueue,
    increment_completed,
    increment_failed,
    initialize_stage,
    should_trigger_coordinator,
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
    assert site.coordinator_enqueued is False
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

    assert result is False


def test_should_trigger_coordinator_ready(test_site):
    """Test coordinator should trigger when all jobs done."""
    initialize_stage(test_site, "ocr", total_jobs=3)
    increment_completed(test_site, "ocr")
    increment_completed(test_site, "ocr")
    increment_failed(test_site, "ocr", "PDF error", "PdfError")

    result = should_trigger_coordinator(test_site, "ocr")

    assert result is True  # 2 + 1 == 3


def test_claim_coordinator_enqueue_success(test_site):
    """Test claiming coordinator enqueue succeeds."""
    initialize_stage(test_site, "ocr", total_jobs=1)
    increment_completed(test_site, "ocr")

    claimed = claim_coordinator_enqueue(test_site)

    assert claimed is True

    with civic_db_connection() as conn:
        from sqlalchemy import select
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == test_site)
        ).fetchone()

    assert site.coordinator_enqueued is True


def test_claim_coordinator_enqueue_race_condition(test_site):
    """Test only one job can claim coordinator enqueue."""
    initialize_stage(test_site, "ocr", total_jobs=2)
    increment_completed(test_site, "ocr")
    increment_completed(test_site, "ocr")

    # First claim succeeds
    claimed1 = claim_coordinator_enqueue(test_site)
    assert claimed1 is True

    # Second claim fails (already claimed)
    claimed2 = claim_coordinator_enqueue(test_site)
    assert claimed2 is False
