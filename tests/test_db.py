"""Tests for database abstraction layer (clerk/db.py)."""

import os

import pytest

from clerk.db import (
    civic_db_connection,
    get_all_sites,
    get_civic_db,
    get_site_by_subdomain,
    get_sites_where,
    insert_site,
    update_site,
    upsert_site,
)
from clerk.models import metadata


@pytest.fixture
def temp_sqlite_db(monkeypatch, tmp_path):
    """Create a temporary SQLite database for testing."""
    # Change to temp directory
    monkeypatch.chdir(tmp_path)
    # Ensure DATABASE_URL is not set (use SQLite)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # Create schema
    engine = get_civic_db()
    metadata.create_all(engine)

    yield engine

    # Cleanup
    if (tmp_path / "civic.db").exists():
        (tmp_path / "civic.db").unlink()


class TestSQLiteBackend:
    """Test database operations with SQLite backend."""

    def test_get_civic_db_returns_sqlite_engine(self, monkeypatch, tmp_path):
        """Test that get_civic_db returns SQLite engine when DATABASE_URL not set."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        engine = get_civic_db()
        assert "sqlite" in str(engine.url)

    def test_insert_and_get_site(self, temp_sqlite_db):
        """Test inserting and retrieving a site."""
        with civic_db_connection() as conn:
            # Insert site
            insert_site(
                conn,
                {
                    "subdomain": "test",
                    "name": "Test City",
                    "state": "CA",
                    "country": "US",
                },
            )

            # Retrieve site
            site = get_site_by_subdomain(conn, "test")
            assert site is not None
            assert site["subdomain"] == "test"
            assert site["name"] == "Test City"
            assert site["state"] == "CA"

    def test_update_site(self, temp_sqlite_db):
        """Test updating a site."""
        with civic_db_connection() as conn:
            # Insert site
            insert_site(conn, {"subdomain": "test", "name": "Test City"})

            # Update site
            update_site(conn, "test", {"status": "deployed", "pages": 100})

            # Verify update
            site = get_site_by_subdomain(conn, "test")
            assert site["status"] == "deployed"
            assert site["pages"] == 100

    def test_upsert_site_insert(self, temp_sqlite_db):
        """Test upsert with a new site (should insert)."""
        with civic_db_connection() as conn:
            # Upsert new site
            upsert_site(
                conn,
                {
                    "subdomain": "test",
                    "name": "Test City",
                    "state": "CA",
                },
            )

            # Verify inserted
            site = get_site_by_subdomain(conn, "test")
            assert site is not None
            assert site["name"] == "Test City"

    def test_upsert_site_update(self, temp_sqlite_db):
        """Test upsert with an existing site (should update)."""
        with civic_db_connection() as conn:
            # Insert site
            insert_site(conn, {"subdomain": "test", "name": "Original Name"})

            # Upsert same subdomain with different data
            upsert_site(
                conn,
                {
                    "subdomain": "test",
                    "name": "Updated Name",
                    "state": "NY",
                },
            )

            # Verify updated
            site = get_site_by_subdomain(conn, "test")
            assert site["name"] == "Updated Name"
            assert site["state"] == "NY"

    def test_get_all_sites(self, temp_sqlite_db):
        """Test retrieving all sites."""
        with civic_db_connection() as conn:
            # Insert multiple sites
            insert_site(conn, {"subdomain": "test1", "name": "Test City 1"})
            insert_site(conn, {"subdomain": "test2", "name": "Test City 2"})
            insert_site(conn, {"subdomain": "test3", "name": "Test City 3"})

            # Get all sites
            sites = get_all_sites(conn)
            assert len(sites) == 3
            assert {s["subdomain"] for s in sites} == {"test1", "test2", "test3"}

    def test_get_sites_where(self, temp_sqlite_db):
        """Test filtering sites by criteria."""
        with civic_db_connection() as conn:
            # Insert sites with different states
            insert_site(conn, {"subdomain": "ca1", "name": "CA City 1", "state": "CA"})
            insert_site(conn, {"subdomain": "ca2", "name": "CA City 2", "state": "CA"})
            insert_site(conn, {"subdomain": "ny1", "name": "NY City 1", "state": "NY"})

            # Filter by state
            ca_sites = get_sites_where(conn, state="CA")
            assert len(ca_sites) == 2
            assert all(s["state"] == "CA" for s in ca_sites)

            ny_sites = get_sites_where(conn, state="NY")
            assert len(ny_sites) == 1
            assert ny_sites[0]["subdomain"] == "ny1"

    def test_get_nonexistent_site_returns_none(self, temp_sqlite_db):
        """Test that getting a nonexistent site returns None."""
        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, "nonexistent")
            assert site is None


class TestPostgreSQLBackend:
    """Test database operations with PostgreSQL backend.

    Note: These tests require a PostgreSQL instance to be available.
    Set TEST_DATABASE_URL environment variable to run these tests.
    """

    @pytest.fixture
    def postgres_db(self, monkeypatch):
        """Create a PostgreSQL test database."""
        test_db_url = os.getenv("TEST_DATABASE_URL")
        if not test_db_url:
            pytest.skip("TEST_DATABASE_URL not set, skipping PostgreSQL tests")

        # Set DATABASE_URL to test database
        monkeypatch.setenv("DATABASE_URL", test_db_url)

        # Create schema
        engine = get_civic_db()
        metadata.create_all(engine)

        yield engine

        # Cleanup - drop all tables
        metadata.drop_all(engine)

    def test_get_civic_db_returns_postgresql_engine(self, monkeypatch):
        """Test that get_civic_db returns PostgreSQL engine when DATABASE_URL is set."""
        test_db_url = os.getenv("TEST_DATABASE_URL")
        if not test_db_url:
            pytest.skip("TEST_DATABASE_URL not set")

        monkeypatch.setenv("DATABASE_URL", test_db_url)
        engine = get_civic_db()
        assert "postgresql" in str(engine.url)

    def test_insert_and_get_site_postgresql(self, postgres_db):
        """Test inserting and retrieving a site with PostgreSQL."""
        with civic_db_connection() as conn:
            # Insert site
            insert_site(
                conn,
                {
                    "subdomain": "test-pg",
                    "name": "Test PG City",
                    "state": "CA",
                },
            )

            # Retrieve site
            site = get_site_by_subdomain(conn, "test-pg")
            assert site is not None
            assert site["subdomain"] == "test-pg"
            assert site["name"] == "Test PG City"

    def test_upsert_postgresql(self, postgres_db):
        """Test upsert operations with PostgreSQL."""
        with civic_db_connection() as conn:
            # Upsert new site
            upsert_site(
                conn,
                {
                    "subdomain": "test-pg",
                    "name": "Original",
                },
            )

            # Upsert same subdomain (should update)
            upsert_site(
                conn,
                {
                    "subdomain": "test-pg",
                    "name": "Updated",
                    "state": "NY",
                },
            )

            # Verify updated
            site = get_site_by_subdomain(conn, "test-pg")
            assert site["name"] == "Updated"
            assert site["state"] == "NY"


class TestErrorHandling:
    """Test error handling in database operations."""

    def test_invalid_database_url_fails_fast(self, monkeypatch):
        """Test that invalid DATABASE_URL causes immediate failure."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://badhost:5432/baddb")

        with pytest.raises(SystemExit):
            get_civic_db()

    def test_postgres_url_normalized_to_postgresql(self, monkeypatch, mocker):
        """Test that postgres:// URLs are normalized to postgresql://."""
        # Mock create_engine to avoid actual connection
        mock_engine = mocker.MagicMock()
        mock_connection = mocker.MagicMock()
        mock_engine.connect.return_value.__enter__ = mocker.MagicMock(return_value=mock_connection)
        mock_engine.connect.return_value.__exit__ = mocker.MagicMock(return_value=None)
        mock_connection.execute.return_value = None

        mock_create_engine = mocker.patch("clerk.db.create_engine", return_value=mock_engine)

        # Set DATABASE_URL with postgres:// scheme
        monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@host:5432/db")

        get_civic_db()

        # Verify create_engine was called with postgresql:// (normalized)
        call_args = mock_create_engine.call_args[0][0]
        assert call_args.startswith("postgresql://")
        assert not call_args.startswith("postgres://")
