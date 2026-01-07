import pytest
from unittest.mock import Mock, MagicMock
from sqlalchemy import select


def test_track_job_inserts_record():
    """Test that track_job inserts a job tracking record."""
    mock_conn = Mock()

    from clerk.queue_db import track_job

    track_job(mock_conn, 'rq-job-123', 'site.civic.band', 'fetch-site', 'fetch')

    mock_conn.execute.assert_called_once()
    mock_conn.commit.assert_called_once()


def test_get_jobs_for_site_returns_jobs():
    """Test that get_jobs_for_site returns all jobs for a site."""
    mock_conn = Mock()
    mock_result = Mock()

    # Create mock rows with _mapping attribute
    mock_row1 = MagicMock()
    mock_row1._mapping = {
        'rq_job_id': 'job-1',
        'site_id': 'site.civic.band',
        'job_type': 'fetch-site',
        'stage': 'fetch'
    }
    mock_row2 = MagicMock()
    mock_row2._mapping = {
        'rq_job_id': 'job-2',
        'site_id': 'site.civic.band',
        'job_type': 'ocr-page',
        'stage': 'ocr'
    }

    mock_result.fetchall.return_value = [mock_row1, mock_row2]
    mock_conn.execute.return_value = mock_result

    from clerk.queue_db import get_jobs_for_site

    jobs = get_jobs_for_site(mock_conn, 'site.civic.band')

    assert len(jobs) == 2
    assert jobs[0]['rq_job_id'] == 'job-1'
    assert jobs[1]['rq_job_id'] == 'job-2'
    mock_conn.execute.assert_called_once()


def test_get_jobs_for_site_empty():
    """Test that get_jobs_for_site returns empty list when no jobs found."""
    mock_conn = Mock()
    mock_result = Mock()
    mock_result.fetchall.return_value = []
    mock_conn.execute.return_value = mock_result

    from clerk.queue_db import get_jobs_for_site

    jobs = get_jobs_for_site(mock_conn, 'nonexistent.civic.band')

    assert jobs == []
    mock_conn.execute.assert_called_once()


def test_delete_jobs_for_site():
    """Test that delete_jobs_for_site deletes all job records for a site."""
    mock_conn = Mock()

    from clerk.queue_db import delete_jobs_for_site

    delete_jobs_for_site(mock_conn, 'site.civic.band')

    mock_conn.execute.assert_called_once()
    mock_conn.commit.assert_called_once()


def test_delete_site_progress():
    """Test that delete_site_progress deletes site progress record."""
    mock_conn = Mock()

    from clerk.queue_db import delete_site_progress

    delete_site_progress(mock_conn, 'site.civic.band')

    mock_conn.execute.assert_called_once()
    mock_conn.commit.assert_called_once()
