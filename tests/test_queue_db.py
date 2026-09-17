from unittest.mock import Mock


def test_delete_site_progress():
    """Test that delete_site_progress deletes site progress record."""
    mock_conn = Mock()

    from clerk.queue_db import delete_site_progress

    delete_site_progress(mock_conn, "site.civic.band")

    mock_conn.execute.assert_called_once()
