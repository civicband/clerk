"""Unit tests for clerk.utils module."""

import json
import os
from pathlib import Path

import pytest
import sqlite_utils

from clerk.utils import STORAGE_DIR, assert_db_exists, pm


class TestAssertDbExists:
    """Tests for the assert_db_exists function."""

    @pytest.fixture(autouse=True)
    def _use_sqlite(self, monkeypatch):
        """Ensure tests use local SQLite, not a production DATABASE_URL."""
        monkeypatch.delenv("DATABASE_URL", raising=False)

    def test_creates_database_if_not_exists(self, tmp_path, monkeypatch):
        """Test that assert_db_exists creates a new database if it doesn't exist."""
        from sqlalchemy import Engine

        db_path = tmp_path / "test_civic.db"
        monkeypatch.chdir(tmp_path)

        # Database shouldn't exist yet
        assert not db_path.exists()

        # Call assert_db_exists
        engine = assert_db_exists()

        # Database should now exist
        assert Path("civic.db").exists()
        assert isinstance(engine, Engine)

    def test_creates_sites_table(self, tmp_path, monkeypatch):
        """Test that the sites table is created with correct schema."""
        from sqlalchemy import inspect

        monkeypatch.chdir(tmp_path)

        engine = assert_db_exists()

        # Check sites table exists
        inspector = inspect(engine)
        assert "sites" in inspector.get_table_names()

        # Check column names (including pipeline state columns)
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
            "last_deployed",
            "lat",
            "lng",
            "extraction_status",
            "last_extracted",
            # Pipeline state columns
            "current_stage",
            "started_at",
            "updated_at",
            "fetch_total",
            "fetch_completed",
            "fetch_failed",
            "ocr_total",
            "ocr_completed",
            "ocr_failed",
            "compilation_total",
            "compilation_completed",
            "compilation_failed",
            "extraction_total",
            "extraction_completed",
            "extraction_failed",
            "deploy_total",
            "deploy_completed",
            "deploy_failed",
            "coordinator_enqueued",
            "last_error_stage",
            "last_error_message",
            "last_error_at",
            # Finance data columns
            "has_finance_data",
            "finance_last_updated",
            "finance_source",
            "finance_coverage_start",
            "finance_coverage_end",
            "finance_record_count",
            "finance_data_types",
        }
        actual_columns = {col["name"] for col in inspector.get_columns("sites")}
        assert actual_columns == expected_columns

        # Check primary key
        pk_constraint = inspector.get_pk_constraint("sites")
        assert pk_constraint["constrained_columns"] == ["subdomain"]

    def test_creates_feed_entries_table(self, tmp_path, monkeypatch):
        """Test that the feed_entries table is created."""
        from sqlalchemy import inspect

        monkeypatch.chdir(tmp_path)

        engine = assert_db_exists()

        # Check feed_entries table exists
        inspector = inspect(engine)
        assert "feed_entries" in inspector.get_table_names()

        # Check column names
        expected_columns = {"subdomain", "date", "kind", "name"}
        actual_columns = {col["name"] for col in inspector.get_columns("feed_entries")}
        assert actual_columns == expected_columns

    def test_transforms_deprecated_columns(self, tmp_path, monkeypatch):
        """Test that deprecated columns are removed via transform."""
        from sqlalchemy import inspect

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
        engine = assert_db_exists()

        # Check that deprecated columns are removed
        inspector = inspect(engine)
        column_names = {col["name"] for col in inspector.get_columns("sites")}
        assert "ocr_class" not in column_names
        assert "docker_port" not in column_names
        assert "save_agendas" not in column_names
        assert "site_db" not in column_names

    def test_idempotent(self, tmp_path, monkeypatch):
        """Test that calling assert_db_exists multiple times is safe."""
        from sqlalchemy import inspect

        monkeypatch.chdir(tmp_path)

        # Call multiple times
        engine1 = assert_db_exists()
        engine2 = assert_db_exists()
        engine3 = assert_db_exists()

        # Should all reference the same database
        inspector1 = inspect(engine1)
        inspector2 = inspect(engine2)
        inspector3 = inspect(engine3)
        assert "sites" in inspector1.get_table_names()
        assert "sites" in inspector2.get_table_names()
        assert "sites" in inspector3.get_table_names()

    def test_no_orphan_tables_on_repeated_calls(self, tmp_path, monkeypatch):
        """Test that repeated calls don't create orphan sites_new_* tables."""
        monkeypatch.chdir(tmp_path)

        # Call multiple times (simulating cron job running repeatedly)
        for _ in range(5):
            assert_db_exists()

        # Check that no sites_new_* tables exist
        db = sqlite_utils.Database("civic.db")
        table_names = db.table_names()
        orphan_tables = [t for t in table_names if t.startswith("sites_new_")]

        assert orphan_tables == [], f"Found orphan tables: {orphan_tables}"

    def test_skips_transform_when_no_deprecated_columns(self, tmp_path, monkeypatch):
        """Test that transform is skipped when deprecated columns don't exist."""
        from sqlalchemy import inspect

        monkeypatch.chdir(tmp_path)

        # Create clean database
        engine = assert_db_exists()

        # Get initial table count
        inspector = inspect(engine)
        initial_tables = set(inspector.get_table_names())

        # Call again - should not create any new tables
        engine = assert_db_exists()
        inspector = inspect(engine)
        final_tables = set(inspector.get_table_names())

        # No new tables should have been created
        new_tables = final_tables - initial_tables
        assert new_tables == set(), f"Unexpected new tables: {new_tables}"


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


def test_hash_text_content():
    """Test consistent hashing of text content."""
    from clerk.utils import hash_text_content

    text1 = "Sample meeting minutes"
    text2 = "Sample meeting minutes"
    text3 = "Different content"

    hash1 = hash_text_content(text1)
    hash2 = hash_text_content(text2)
    hash3 = hash_text_content(text3)

    assert hash1 == hash2, "Same text should produce same hash"
    assert hash1 != hash3, "Different text should produce different hash"
    assert len(hash1) == 64, "SHA256 should produce 64-char hex string"
