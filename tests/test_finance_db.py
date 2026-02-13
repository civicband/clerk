"""Tests for finance_db module."""

from unittest.mock import MagicMock, patch

from clerk.finance_db import (
    get_all_sites,
    get_next_finance_site,
    get_sites_with_finance_data,
    update_site,
    update_site_finance_status,
)


class TestFinanceDb:
    """Tests for finance database operations."""

    @patch("clerk.finance_db.civic_db_connection")
    def test_update_site_finance_status(self, mock_connection):
        """Test updating site finance status."""
        mock_conn = MagicMock()
        mock_connection.return_value.__enter__.return_value = mock_conn

        update_site_finance_status("oakland", True)

        # Check that execute was called
        mock_conn.execute.assert_called_once()

        # Check that execute was called with a SQLAlchemy statement
        call_args = mock_conn.execute.call_args[0][0]
        # It should be a SQLAlchemy statement object, not a string
        assert hasattr(call_args, "compile")  # It's a SQLAlchemy statement

    @patch("clerk.finance_db.civic_db_connection")
    def test_get_sites_with_finance_data(self, mock_connection):
        """Test getting sites with finance data."""
        mock_conn = MagicMock()
        mock_result = [
            MagicMock(_mapping={"subdomain": "oakland", "has_finance_data": True}),
            MagicMock(_mapping={"subdomain": "berkeley", "has_finance_data": True}),
        ]
        mock_conn.execute.return_value = mock_result
        mock_connection.return_value.__enter__.return_value = mock_conn

        sites = get_sites_with_finance_data()

        assert len(sites) == 2
        assert sites[0]["subdomain"] == "oakland"
        assert sites[1]["subdomain"] == "berkeley"

        # Check that the query filters for has_finance_data
        call_args = mock_conn.execute.call_args[0][0]
        query_str = str(call_args)
        assert "has_finance_data" in query_str

    @patch("clerk.finance_db.civic_db_connection")
    def test_get_sites_with_finance_data_empty(self, mock_connection):
        """Test getting sites with finance data when none exist."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value = []
        mock_connection.return_value.__enter__.return_value = mock_conn

        sites = get_sites_with_finance_data()

        assert sites == []

    @patch("clerk.finance_db.civic_db_connection")
    def test_get_next_finance_site(self, mock_connection):
        """Test getting next finance site."""
        mock_conn = MagicMock()
        mock_result = MagicMock(_mapping={"subdomain": "oakland", "state": "CA"})
        mock_conn.execute.return_value.fetchone.return_value = mock_result
        mock_connection.return_value.__enter__.return_value = mock_conn

        site = get_next_finance_site()

        assert site is not None
        assert site["subdomain"] == "oakland"
        assert site["state"] == "CA"

        # Check that the query is a SQLAlchemy statement
        call_args = mock_conn.execute.call_args[0][0]
        assert hasattr(call_args, "compile")  # It's a SQLAlchemy statement

    @patch("clerk.finance_db.civic_db_connection")
    def test_get_next_finance_site_none(self, mock_connection):
        """Test getting next finance site when none available."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_connection.return_value.__enter__.return_value = mock_conn

        site = get_next_finance_site()

        assert site is None

    @patch("clerk.finance_db.civic_db_connection")
    def test_get_all_sites(self, mock_connection):
        """Test getting all sites."""
        mock_conn = MagicMock()
        mock_result = [
            MagicMock(_mapping={"subdomain": "oakland"}),
            MagicMock(_mapping={"subdomain": "berkeley"}),
            MagicMock(_mapping={"subdomain": "san-francisco"}),
        ]
        mock_conn.execute.return_value = mock_result
        mock_connection.return_value.__enter__.return_value = mock_conn

        sites = get_all_sites()

        assert len(sites) == 3
        assert sites[0]["subdomain"] == "oakland"
        assert sites[1]["subdomain"] == "berkeley"
        assert sites[2]["subdomain"] == "san-francisco"

    @patch("clerk.finance_db.civic_db_connection")
    def test_update_site(self, mock_connection):
        """Test updating a site."""
        mock_conn = MagicMock()
        mock_connection.return_value.__enter__.return_value = mock_conn

        updates = {
            "has_finance_data": True,
            "state": "CA",
            "updated_at": "2024-01-01",
        }
        update_site("oakland", updates)

        # Check that execute was called
        mock_conn.execute.assert_called_once()

        # Check that the query is a SQLAlchemy statement
        call_args = mock_conn.execute.call_args[0][0]
        assert hasattr(call_args, "compile")  # It's a SQLAlchemy statement

    @patch("clerk.finance_db.civic_db_connection")
    def test_update_site_empty_updates(self, mock_connection):
        """Test updating a site with empty updates."""
        mock_conn = MagicMock()
        mock_connection.return_value.__enter__.return_value = mock_conn

        update_site("oakland", {})

        # Should still execute even with empty updates
        mock_conn.execute.assert_called_once()

    @patch("clerk.finance_db.civic_db_connection")
    def test_database_connection_context_manager(self, mock_connection):
        """Test that database connections are properly managed."""
        mock_conn = MagicMock()
        mock_connection.return_value.__enter__.return_value = mock_conn
        mock_connection.return_value.__exit__.return_value = None

        # Call any function to test context manager
        get_all_sites()

        # Check that context manager was used properly
        mock_connection.return_value.__enter__.assert_called_once()
        mock_connection.return_value.__exit__.assert_called_once()

    @patch("clerk.finance_db.civic_db_connection")
    def test_sql_injection_prevention(self, mock_connection):
        """Test that SQL injection is prevented through parameterized queries."""
        mock_conn = MagicMock()
        mock_connection.return_value.__enter__.return_value = mock_conn

        # Try to inject SQL through subdomain
        malicious_subdomain = "'; DROP TABLE sites; --"
        update_site_finance_status(malicious_subdomain, True)

        # The malicious subdomain should be treated as a literal string
        call_args = mock_conn.execute.call_args[0][0]
        # SQLAlchemy should properly escape the value
        # We're checking that it's using parameterized queries, not string formatting
        assert hasattr(call_args, "compile")  # It should be a SQLAlchemy statement object
