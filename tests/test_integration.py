"""Integration tests for clerk library end-to-end workflows."""

import pytest
import sqlite_utils
from click.testing import CliRunner

from clerk.cli import cli


@pytest.mark.integration
class TestEndToEndWorkflow:
    """End-to-end integration tests for complete workflows."""

    def test_new_site_creation(
        self, tmp_path, tmp_storage_dir, monkeypatch, mock_plugin_manager, cli_module
    ):
        """Test creating a new site from scratch."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "pm", mock_plugin_manager)

        # Mock enqueue_job since Redis won't be available in test environment
        from unittest.mock import Mock

        mock_enqueue = Mock(return_value="job123")
        monkeypatch.setattr(cli_module, "enqueue_job", mock_enqueue)

        runner = CliRunner()

        # Create database with proper schema
        from clerk.utils import assert_db_exists

        assert_db_exists()

        # Create a new site interactively
        result = runner.invoke(
            cli,
            ["new"],
            input="test.civic.band\nTest City\nCA\nUS\ncity-council\n2020\nFalse\n37.77,-122.41\ntest_scraper\n",
        )

        # Command should succeed
        assert result.exit_code == 0
        assert "created" in result.output.lower()

        # Check that civic.db was created
        civic_db = sqlite_utils.Database("civic.db")
        assert civic_db["sites"].exists()

        # Check that the site was inserted
        site = civic_db["sites"].get("test.civic.band")
        assert site["name"] == "Test City"
        assert site["state"] == "CA"
        # After clerk new, status should be "new" (job is enqueued, not processed yet)
        assert site["status"] == "new"

    def test_database_build_workflow(
        self, tmp_path, tmp_storage_dir, sample_text_files, monkeypatch, cli_module, utils_module
    ):
        """Test the complete database building workflow."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(utils_module, "STORAGE_DIR", str(tmp_storage_dir))

        subdomain = "example.civic.band"

        # Create a minimal existing database (directory already exists from sample_text_files)
        site_dir = tmp_storage_dir / subdomain
        site_dir.mkdir(exist_ok=True)
        db_path = site_dir / "meetings.db"
        db = sqlite_utils.Database(db_path)
        db["temp"].insert({"id": 1})

        # Run the build command
        runner = CliRunner()
        result = runner.invoke(cli, ["build-db-from-text", "-s", subdomain])

        # Should succeed
        assert result.exit_code == 0

        # Check database was built
        db = sqlite_utils.Database(db_path)
        assert "minutes" in db.table_names()
        assert "agendas" in db.table_names()

        # Check data was inserted
        minutes = list(db["minutes"].rows)
        assert len(minutes) == 2
        assert minutes[0]["meeting"] == "City Council"

        # Check FTS is working (if rebuild_fts was called)
        # This depends on the workflow implementation

    def test_full_pipeline(
        self, tmp_path, tmp_storage_dir, monkeypatch, mock_plugin_manager, cli_module, utils_module
    ):
        """Test a complete pipeline: create → fetch → build → deploy."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(utils_module, "STORAGE_DIR", str(tmp_storage_dir))

        from tests.mocks.mock_fetchers import FilesystemFetcher

        # Register filesystem fetcher that creates actual files
        class FilesystemFetcherPlugin:
            from clerk import hookimpl

            @hookimpl
            def fetcher_class(self, label):
                if label == "test_scraper":
                    return FilesystemFetcher
                return None

            @hookimpl
            def fetcher_extra(self, label):
                return None

        monkeypatch.setattr(cli_module, "pm", mock_plugin_manager)

        # 1. Create civic.db with a test site
        civic_db = sqlite_utils.Database("civic.db")
        civic_db["sites"].insert(
            {
                "subdomain": "pipeline-test.civic.band",
                "name": "Pipeline Test City",
                "state": "CA",
                "country": "US",
                "kind": "city-council",
                "scraper": "test_scraper",
                "pages": 0,
                "start_year": 2024,
                "extra": None,
                "status": "new",
                "last_updated": "2024-01-01T00:00:00",
                "lat": "37.77",
                "lng": "-122.41",
            },
            pk="subdomain",
        )

        # 2. Create the site directory
        site_dir = tmp_storage_dir / "pipeline-test.civic.band"
        site_dir.mkdir()

        # 3. Simulate fetcher creating text files
        minutes_dir = site_dir / "txt" / "City Council" / "2024-01-15"
        minutes_dir.mkdir(parents=True)
        (minutes_dir / "1.txt").write_text("Test meeting content")

        # 4. Build database
        db_path = site_dir / "meetings.db"
        initial_db = sqlite_utils.Database(db_path)
        initial_db["temp"].insert({"id": 1})

        runner = CliRunner()
        result = runner.invoke(cli, ["build-db-from-text", "-s", "pipeline-test.civic.band"])

        assert result.exit_code == 0

        # 5. Verify database was built correctly
        db = sqlite_utils.Database(db_path)
        assert "minutes" in db.table_names()

        minutes = list(db["minutes"].rows)
        assert len(minutes) >= 1
        assert "Test meeting content" in minutes[0]["text"]


@pytest.mark.integration
class TestDatabaseOperations:
    """Integration tests for database operations."""

    def test_fts_search_works_end_to_end(
        self, tmp_storage_dir, monkeypatch, cli_module, utils_module
    ):
        """Test that full-text search works after building database."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(utils_module, "STORAGE_DIR", str(tmp_storage_dir))

        subdomain = "search-test.civic.band"
        site_dir = tmp_storage_dir / subdomain
        site_dir.mkdir()

        # Create text files with searchable content
        minutes_dir = site_dir / "txt" / "Council" / "2024-01-01"
        minutes_dir.mkdir(parents=True)
        (minutes_dir / "1.txt").write_text("Discussion about parks and recreation")
        (minutes_dir / "2.txt").write_text("Budget allocation for infrastructure")

        # Build database
        from clerk.utils import build_db_from_text_internal

        # Create initial DB for backup
        db_path = site_dir / "meetings.db"
        initial_db = sqlite_utils.Database(db_path)
        initial_db["temp"].insert({"id": 1})

        build_db_from_text_internal(subdomain)

        # Enable FTS
        from clerk.cli import rebuild_site_fts_internal

        rebuild_site_fts_internal(subdomain)

        # Test search
        db = sqlite_utils.Database(db_path)

        # Search for "parks" using sqlite-utils .search() method
        results = list(db["minutes"].search("parks"))
        assert len(results) == 1
        assert "recreation" in results[0]["text"]

        # Search for "budget"
        results = list(db["minutes"].search("budget"))
        assert len(results) == 1
        assert "infrastructure" in results[0]["text"]


@pytest.mark.integration
class TestPluginIntegration:
    """Integration tests for plugin system."""

    def test_plugin_hooks_called_during_workflow(self, tmp_path, monkeypatch, cli_module):
        """Test that plugin hooks are called at appropriate times."""
        monkeypatch.chdir(tmp_path)

        # Create plugin manager and register test plugin
        import pluggy

        from clerk.hookspecs import ClerkSpec
        from tests.mocks.mock_plugins import TestPlugin

        test_pm = pluggy.PluginManager("civicband.clerk")
        test_pm.add_hookspecs(ClerkSpec)
        test_plugin = TestPlugin()
        test_pm.register(test_plugin)

        # Replace the global pm in fetcher module where get_fetcher lives
        import clerk.fetcher as fetcher_module

        monkeypatch.setattr(fetcher_module, "pm", test_pm)

        # Create a site
        civic_db = sqlite_utils.Database("civic.db")
        civic_db["sites"].insert(
            {
                "subdomain": "plugin-test.civic.band",
                "name": "Plugin Test",
                "state": "CA",
                "country": "US",
                "kind": "council",
                "scraper": "test_scraper",
                "pages": 0,
                "start_year": 2020,
                "extra": None,
                "status": "new",
                "last_updated": "2024-01-01T00:00:00",
                "lat": "0",
                "lng": "0",
            },
            pk="subdomain",
        )

        # Test that fetcher_class hook works
        from clerk.fetcher import get_fetcher

        site = civic_db["sites"].get("plugin-test.civic.band")
        fetcher = get_fetcher(site, all_years=False, all_agendas=False)

        # Should get MockFetcher from TestPlugin
        assert fetcher is not None
        assert hasattr(fetcher, "fetch_events")


@pytest.mark.integration
class TestErrorHandling:
    """Integration tests for error handling."""

    def test_rebuild_fts_handles_missing_tables(self, tmp_storage_dir, monkeypatch, cli_module):
        """Test that rebuild_fts handles missing tables gracefully."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))

        subdomain = "empty.civic.band"
        site_dir = tmp_storage_dir / subdomain
        site_dir.mkdir()

        # Create empty database
        db_path = site_dir / "meetings.db"
        sqlite_utils.Database(db_path)  # Creates the file

        # Try to rebuild FTS on non-existent tables
        from clerk.cli import rebuild_site_fts_internal

        # Should not raise an exception
        rebuild_site_fts_internal(subdomain)

    def test_build_db_creates_backup(self, tmp_storage_dir, monkeypatch, cli_module, utils_module):
        """Test that building database creates a backup of existing db."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(utils_module, "STORAGE_DIR", str(tmp_storage_dir))

        subdomain = "backup-test.civic.band"
        site_dir = tmp_storage_dir / subdomain
        site_dir.mkdir()

        # Create existing database with data
        db_path = site_dir / "meetings.db"
        existing_db = sqlite_utils.Database(db_path)
        existing_db["old_data"].insert({"id": 1, "value": "important"})

        # Create text files
        minutes_dir = site_dir / "txt" / "Council" / "2024-01-01"
        minutes_dir.mkdir(parents=True)
        (minutes_dir / "1.txt").write_text("New meeting")

        # Build database (should backup old one)
        from clerk.utils import build_db_from_text_internal

        build_db_from_text_internal(subdomain)

        # Check backup exists
        backup_path = site_dir / "meetings.db.bk"
        assert backup_path.exists()

        # Check old data is in backup
        backup_db = sqlite_utils.Database(backup_path)
        assert "old_data" in backup_db.table_names()
        assert backup_db["old_data"].count == 1

    def test_no_cache_produces_empty_json(self, tmp_path, monkeypatch):
        """Without extraction cache, JSON columns have empty structures."""
        import json

        import sqlite_utils

        import clerk.utils

        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(clerk.utils, "STORAGE_DIR", str(tmp_path))

        # Create test site structure
        site_dir = tmp_path / "test-site"
        txt_dir = site_dir / "txt" / "CityCouncil" / "2024-01-15"
        txt_dir.mkdir(parents=True)

        (txt_dir / "1.txt").write_text("The motion passed 5-0.")
        (site_dir / "meetings.db").touch()

        from clerk.utils import build_db_from_text_internal

        build_db_from_text_internal("test-site")

        db = sqlite_utils.Database(site_dir / "meetings.db")
        rows = list(db["minutes"].rows)

        assert len(rows) == 1
        entities = json.loads(rows[0]["entities_json"])
        votes = json.loads(rows[0]["votes_json"])

        # Without cache, should have empty structures
        assert entities == {"persons": [], "orgs": [], "locations": []}
        assert votes == {"votes": []}


@pytest.mark.integration
class TestOCRFailureManifest:
    """Integration tests for OCR failure manifest creation."""

    def test_ocr_pipeline_with_failure_manifest(self, tmp_path, monkeypatch, mock_site):
        """Integration test: OCR pipeline creates failure manifest on errors."""
        import json
        from pathlib import Path
        from unittest.mock import Mock, patch

        mock_site["subdomain"] = "integration_test"

        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        # Patch the STORAGE_DIR in the clerk modules
        import clerk.fetcher
        import clerk.utils

        monkeypatch.setattr(clerk.fetcher, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(clerk.utils, "STORAGE_DIR", str(tmp_path))

        from clerk.fetcher import Fetcher

        fetcher = Fetcher(mock_site)

        # Create test PDF directory with one valid and one corrupted PDF
        pdf_dir = Path(tmp_path) / "integration_test" / "pdfs" / "TestMeeting"
        pdf_dir.mkdir(parents=True, exist_ok=True)

        (pdf_dir / "2024-01-01.pdf").write_bytes(b"%PDF-1.4 fake valid pdf")
        (pdf_dir / "2024-01-02.pdf").write_bytes(b"corrupted")

        # Mock PDF processing - need to mock PdfReadError too
        from clerk.ocr_utils import PdfReadError

        with (
            patch("clerk.fetcher.PDF_SUPPORT", True),
            patch("clerk.fetcher.PdfReader") as mock_reader,
            patch("clerk.fetcher.PdfReadError", PdfReadError),
            patch("clerk.fetcher.convert_from_path") as mock_convert,
            patch("subprocess.check_output") as mock_tesseract,
            patch("clerk.fetcher.pm.hook.upload_static_file"),
        ):
            # First PDF succeeds, second fails
            def pdf_side_effect(path):
                if "2024-01-01" in str(path):
                    mock = Mock()
                    mock.pages = [Mock()]
                    return mock
                else:
                    raise PdfReadError("corrupted")

            mock_reader.side_effect = pdf_side_effect
            mock_convert.return_value = [Mock()]
            mock_tesseract.return_value = b"test text"

            # Run OCR
            fetcher.do_ocr()

            # Verify failure manifest was created
            manifest_files = list(Path(tmp_path).glob("integration_test/ocr_failures_*.jsonl"))
            assert len(manifest_files) == 1

            # Verify manifest content
            with open(manifest_files[0]) as f:
                entries = [json.loads(line) for line in f]

            assert len(entries) == 1
            assert entries[0]["meeting"] == "TestMeeting"
            assert entries[0]["date"] == "2024-01-02"
            assert entries[0]["error_class"] == "PdfReadError"
