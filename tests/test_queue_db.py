import pytest
from unittest.mock import Mock


def test_track_job_inserts_record():
    """Test that track_job inserts a job tracking record."""
    mock_conn = Mock()

    from clerk.queue_db import track_job

    track_job(mock_conn, 'rq-job-123', 'site.civic.band', 'fetch-site', 'fetch')

    mock_conn.execute.assert_called_once()
    mock_conn.commit.assert_called_once()
