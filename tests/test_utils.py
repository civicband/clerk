"""Unit tests for clerk.utils module."""

import os
from pathlib import Path

import sqlite_utils

from clerk.utils import STORAGE_DIR, assert_db_exists, pm


class TestAssertDbExists:
    """Tests for the assert_db_exists function."""

    def test_creates_database_if_not_exists(self, tmp_path, monkeypatch):
        """Test that assert_db_exists creates a new database if it doesn't exist."""
        db_path = tmp_path / "test_civic.db"
        monkeypatch.chdir(tmp_path)

        # Database shouldn't exist yet
        assert not db_path.exists()

        # Call assert_db_exists
        db = assert_db_exists()

        # Database should now exist
        assert Path("civic.db").exists()
        assert isinstance(db, sqlite_utils.Database)

    def test_creates_sites_table(self, tmp_path, monkeypatch):
        """Test that the sites table is created with correct schema."""
        monkeypatch.chdir(tmp_path)

        db = assert_db_exists()

        # Check sites table exists
        assert db["sites"].exists()

        # Check column names
        expected_columns = {
            "subdomain",
            "name",
            "state",
            "country",
            "kind",
            "scraper",
            "pages",
            "start_year",
            "extra",
            "status",
            "last_updated",
            "lat",
            "lng",
            "pipeline",
        }
        actual_columns = {col.name for col in db["sites"].columns}
        assert actual_columns == expected_columns

        # Check primary key
        assert db["sites"].pks == ["subdomain"]

    def test_creates_feed_entries_table(self, tmp_path, monkeypatch):
        """Test that the feed_entries table is created."""
        monkeypatch.chdir(tmp_path)

        db = assert_db_exists()

        # Check feed_entries table exists
        assert db["feed_entries"].exists()

        # Check column names
        expected_columns = {"subdomain", "date", "kind", "name"}
        actual_columns = {col.name for col in db["feed_entries"].columns}
        assert actual_columns == expected_columns

    def test_transforms_deprecated_columns(self, tmp_path, monkeypatch):
        """Test that deprecated columns are removed via transform."""
        monkeypatch.chdir(tmp_path)

        # Create a database with deprecated columns
        db = sqlite_utils.Database("civic.db")
        db["sites"].insert(
            {
                "subdomain": "test.civic.band",
                "name": "Test City",
                "state": "CA",
                "country": "US",
                "kind": "city-council",
                "scraper": "test",
                "pages": 0,
                "start_year": 2020,
                "extra": None,
                "status": "new",
                "last_updated": "2024-01-01T00:00:00",
                "lat": "0",
                "lng": "0",
                "ocr_class": "deprecated",  # Deprecated column
                "docker_port": "8080",  # Deprecated column
            },
            pk="subdomain",
        )

        # Call assert_db_exists which should remove deprecated columns
        db = assert_db_exists()

        # Check that deprecated columns are removed
        column_names = {col.name for col in db["sites"].columns}
        assert "ocr_class" not in column_names
        assert "docker_port" not in column_names
        assert "save_agendas" not in column_names
        assert "site_db" not in column_names

    def test_idempotent(self, tmp_path, monkeypatch):
        """Test that calling assert_db_exists multiple times is safe."""
        monkeypatch.chdir(tmp_path)

        # Call multiple times
        db1 = assert_db_exists()
        db2 = assert_db_exists()
        db3 = assert_db_exists()

        # Should all reference the same database
        assert db1["sites"].exists()
        assert db2["sites"].exists()
        assert db3["sites"].exists()


class TestPluginManager:
    """Tests for the plugin manager setup."""

    def test_plugin_manager_exists(self):
        """Test that the plugin manager is initialized."""
        assert pm is not None
        assert pm.project_name == "civicband.clerk"

    def test_hookspecs_registered(self):
        """Test that ClerkSpec hookspecs are registered."""
        # The plugin manager should have hookspecs registered
        assert pm.hook is not None


class TestStorageDir:
    """Tests for STORAGE_DIR environment variable."""

    def test_default_storage_dir(self):
        """Test the default STORAGE_DIR value."""
        assert STORAGE_DIR == os.environ.get("STORAGE_DIR", "../sites")


class TestPipelineColumn:
    """Tests for pipeline column in sites table."""

    def test_pipeline_column_exists(self, tmp_path, monkeypatch):
        """Test that pipeline column is created in new databases."""
        monkeypatch.chdir(tmp_path)

        from clerk.utils import assert_db_exists

        db = assert_db_exists()

        # Check column exists
        columns = {col.name for col in db["sites"].columns}
        assert "pipeline" in columns

    def test_pipeline_column_added_to_existing_db(self, tmp_path, monkeypatch):
        """Test that pipeline column is added to existing databases."""
        monkeypatch.chdir(tmp_path)

        import sqlite_utils

        # Create old-style database without pipeline column
        db = sqlite_utils.Database("civic.db")
        db["sites"].create(
            {
                "subdomain": str,
                "name": str,
                "state": str,
                "country": str,
                "kind": str,
                "scraper": str,
                "pages": int,
                "start_year": int,
                "extra": str,
                "status": str,
                "last_updated": str,
                "lat": str,
                "lng": str,
            },
            pk="subdomain",
        )

        # Now call assert_db_exists which should add the column
        from clerk.utils import assert_db_exists

        db = assert_db_exists()

        columns = {col.name for col in db["sites"].columns}
        assert "pipeline" in columns

    def test_pipeline_column_nullable(self, tmp_path, monkeypatch):
        """Test that pipeline column allows NULL values."""
        monkeypatch.chdir(tmp_path)

        from clerk.utils import assert_db_exists

        db = assert_db_exists()

        # Insert row without pipeline
        db["sites"].insert(
            {
                "subdomain": "test.civic.band",
                "name": "Test",
                "state": "CA",
                "country": "US",
                "kind": "council",
                "scraper": "test",
                "pages": 0,
                "start_year": 2020,
                "extra": None,
                "status": "new",
                "last_updated": None,
                "lat": "0",
                "lng": "0",
            }
        )

        site = db["sites"].get("test.civic.band")
        assert site["pipeline"] is None
