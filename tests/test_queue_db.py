from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy import create_engine

from clerk.models import metadata


@pytest.fixture
def conn():
    """In-memory SQLite database with full schema for queue_db tests."""
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.connect() as c:
        yield c


def test_track_job_inserts_record():
    """Test that track_job inserts a job tracking record."""
    mock_conn = Mock()

    from clerk.queue_db import track_job

    track_job(mock_conn, "rq-job-123", "site.civic.band", "fetch-site", "fetch")

    mock_conn.execute.assert_called_once()


def test_get_jobs_for_site_returns_jobs():
    """Test that get_jobs_for_site returns all jobs for a site."""
    mock_conn = Mock()
    mock_result = Mock()

    # Create mock rows with _mapping attribute
    mock_row1 = MagicMock()
    mock_row1._mapping = {
        "rq_job_id": "job-1",
        "subdomain": "site.civic.band",
        "job_type": "fetch-site",
        "stage": "fetch",
    }
    mock_row2 = MagicMock()
    mock_row2._mapping = {
        "rq_job_id": "job-2",
        "subdomain": "site.civic.band",
        "job_type": "ocr-page",
        "stage": "ocr",
    }

    mock_result.fetchall.return_value = [mock_row1, mock_row2]
    mock_conn.execute.return_value = mock_result

    from clerk.queue_db import get_jobs_for_site

    jobs = get_jobs_for_site(mock_conn, "site.civic.band")

    assert len(jobs) == 2
    assert jobs[0]["rq_job_id"] == "job-1"
    assert jobs[1]["rq_job_id"] == "job-2"
    mock_conn.execute.assert_called_once()


def test_get_jobs_for_site_empty():
    """Test that get_jobs_for_site returns empty list when no jobs found."""
    mock_conn = Mock()
    mock_result = Mock()
    mock_result.fetchall.return_value = []
    mock_conn.execute.return_value = mock_result

    from clerk.queue_db import get_jobs_for_site

    jobs = get_jobs_for_site(mock_conn, "nonexistent.civic.band")

    assert jobs == []
    mock_conn.execute.assert_called_once()


def test_delete_jobs_for_site():
    """Test that delete_jobs_for_site deletes all job records for a site."""
    mock_conn = Mock()

    from clerk.queue_db import delete_jobs_for_site

    delete_jobs_for_site(mock_conn, "site.civic.band")

    mock_conn.execute.assert_called_once()


def test_track_job_stores_run_id(conn):
    """Test that track_job persists run_id in the job_tracking table."""
    from clerk.queue_db import get_jobs_for_site, track_job

    track_job(conn, "rq-123", "springfield", "fetch-site", "fetch", run_id="springfield_1_abc")
    conn.commit()

    rows = get_jobs_for_site(conn, "springfield")
    assert len(rows) == 1
    assert rows[0]["run_id"] == "springfield_1_abc"


def test_track_jobs_bulk_stores_run_id(conn):
    """Test that track_jobs_bulk persists run_id for all bulk-inserted jobs."""
    from clerk.queue_db import get_jobs_for_site, track_jobs_bulk

    job1 = SimpleNamespace(id="job-1")
    job2 = SimpleNamespace(id="job-2")

    track_jobs_bulk(
        conn, [job1, job2], "springfield", "ocr-page", "ocr", run_id="springfield_1_abc"
    )
    conn.commit()

    rows = get_jobs_for_site(conn, "springfield")
    assert len(rows) == 2
    assert all(r["run_id"] == "springfield_1_abc" for r in rows)


def test_track_job_run_id_defaults_to_none(conn):
    """Test that run_id is NULL when not passed to track_job."""
    from clerk.queue_db import get_jobs_for_site, track_job

    track_job(conn, "rq-456", "springfield", "fetch-site", "fetch")
    conn.commit()

    rows = get_jobs_for_site(conn, "springfield")
    assert rows[0]["run_id"] is None


def test_delete_site_progress():
    """Test that delete_site_progress deletes site progress record."""
    mock_conn = Mock()

    from clerk.queue_db import delete_site_progress

    delete_site_progress(mock_conn, "site.civic.band")

    mock_conn.execute.assert_called_once()
