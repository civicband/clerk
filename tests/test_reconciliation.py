"""Tests for pipeline reconciliation job."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from clerk.db import civic_db_connection, upsert_site
from clerk.models import sites_table
from clerk.pipeline_state import initialize_stage


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
            update(sites_table)
            .where(sites_table.c.subdomain == subdomain)
            .values(updated_at=datetime.now(UTC) - timedelta(hours=3))
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
    from unittest.mock import MagicMock, patch

    from scripts.reconcile_pipeline import recover_stuck_site

    # Mock queue.enqueue to verify coordinator gets enqueued
    mock_queue = MagicMock()

    with patch("scripts.reconcile_pipeline.get_compilation_queue", return_value=mock_queue):
        recover_stuck_site(stuck_site)

    # Verify coordinator was enqueued
    assert mock_queue.enqueue.called

    # Verify database updated
    with civic_db_connection() as conn:
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == stuck_site)
        ).fetchone()

    assert site.ocr_completed == 2  # 2 txt files found
    assert site.coordinator_enqueued is True


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
            update(sites_table)
            .where(sites_table.c.subdomain == subdomain)
            .values(updated_at=datetime.now(UTC) - timedelta(minutes=30))
        )

    stuck = find_stuck_sites()
    subdomains = [s.subdomain for s in stuck]

    assert subdomain not in subdomains  # Should not be detected as stuck

    # Cleanup
    with civic_db_connection() as conn:
        from sqlalchemy import delete

        conn.execute(delete(sites_table).where(sites_table.c.subdomain == subdomain))
