"""Integration tests for clerk library end-to-end workflows."""

import pytest
import sqlite_utils
from click.testing import CliRunner

from clerk.cli import cli
from clerk.extraction import EXTRACTION_ENABLED


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

        runner = CliRunner()

        # Run migration to add extraction columns
        from clerk.utils import assert_db_exists

        assert_db_exists()
        runner.invoke(cli, ["migrate-extraction-schema"])

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
        # After full new workflow (create + update), status should be "deployed"
        assert site["status"] == "deployed"

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

    def test_aggregate_database_combines_sites(
        self, tmp_path, tmp_storage_dir, monkeypatch, cli_module
    ):
        """Test that aggregate database correctly combines multiple sites."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))

        # Create civic.db with multiple sites
        civic_db = sqlite_utils.Database("civic.db")
        sites = [
            {
                "subdomain": "site1.civic.band",
                "name": "Site One",
                "state": "CA",
                "country": "US",
                "kind": "council",
                "scraper": "test",
                "pages": 0,
                "start_year": 2020,
                "extra": None,
                "status": "deployed",
                "last_updated": "2024-01-01T00:00:00",
                "last_deployed": None,
                "lat": "0",
                "lng": "0",
                "extraction_status": "pending",
                "last_extracted": None,
            },
            {
                "subdomain": "site2.civic.band",
                "name": "Site Two",
                "state": "NY",
                "country": "US",
                "kind": "commission",
                "scraper": "test",
                "pages": 0,
                "start_year": 2021,
                "extra": None,
                "status": "deployed",
                "last_updated": "2024-01-01T00:00:00",
                "last_deployed": None,
                "lat": "0",
                "lng": "0",
                "extraction_status": "pending",
                "last_extracted": None,
            },
        ]
        civic_db["sites"].insert_all(sites, pk="subdomain")

        # Create text files for each site
        for site in sites:
            subdomain = site["subdomain"]
            site_dir = tmp_storage_dir / subdomain
            minutes_dir = site_dir / "txt" / "Council" / "2024-01-01"
            minutes_dir.mkdir(parents=True)
            (minutes_dir / "1.txt").write_text(f"Meeting for {site['name']}")

        # Build aggregate database using CLI runner (build_full_db is a Click command)
        runner = CliRunner()
        result = runner.invoke(cli, ["build-full-db"])
        assert result.exit_code == 0, f"build-full-db failed: {result.output}"

        # Check aggregate database
        agg_db_path = tmp_storage_dir / "meetings.db"
        assert agg_db_path.exists()

        agg_db = sqlite_utils.Database(agg_db_path)
        all_minutes = list(agg_db["minutes"].rows)

        # Should have records from both sites
        assert len(all_minutes) == 2

        # Check that subdomain and municipality are included
        subdomains = {m["subdomain"] for m in all_minutes}
        assert "site1.civic.band" in subdomains
        assert "site2.civic.band" in subdomains

        municipalities = {m["municipality"] for m in all_minutes}
        assert "Site One" in municipalities
        assert "Site Two" in municipalities


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

        # Replace the global pm
        monkeypatch.setattr(cli_module, "pm", test_pm)

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
        from clerk.cli import get_fetcher

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


@pytest.mark.skipif(not EXTRACTION_ENABLED, reason="Extraction disabled or spaCy not available")
@pytest.mark.integration
class TestExtractionCaching:
    """Integration tests for extraction caching."""

    def test_cache_workflow_end_to_end(
        self, tmp_storage_dir, monkeypatch, cli_module, utils_module
    ):
        """Test complete cache workflow: extraction creates cache, subsequent runs use it."""
        import sqlite_utils

        from clerk.utils import build_db_from_text_internal

        # Set up storage directory
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(utils_module, "STORAGE_DIR", str(tmp_storage_dir))

        subdomain = "cachetest.civic.band"
        site_dir = tmp_storage_dir / subdomain
        txt_dir = site_dir / "txt" / "city-council" / "2024-01-15"
        txt_dir.mkdir(parents=True)

        # Create test text files (4-digit naming like real pages)
        (txt_dir / "0001.txt").write_text("Meeting called to order")
        (txt_dir / "0002.txt").write_text("Roll call taken")

        # Create initial database for backup
        db_path = site_dir / "meetings.db"
        db = sqlite_utils.Database(db_path)
        db["sites"].insert(
            {
                "subdomain": subdomain,
                "name": "Cache Test City",
                "state": "CA",
                "country": "USA",
            },
            pk="subdomain",
        )
        db.close()

        # Enable extraction
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")

        # Build database (without extraction - no cache created)
        build_db_from_text_internal(subdomain, extract_entities=False)

        # First extraction run - should create cache files
        build_db_from_text_internal(subdomain, extract_entities=True, ignore_cache=False)

        # Verify cache files created
        assert (txt_dir / "0001.txt.extracted.json").exists()
        assert (txt_dir / "0002.txt.extracted.json").exists()

        # Second extraction run - should use cache
        build_db_from_text_internal(subdomain, extract_entities=True, ignore_cache=False)

        # Verify database populated correctly
        db = sqlite_utils.Database(db_path)
        rows = list(db["minutes"].rows)
        assert len(rows) == 2

    def test_ignore_cache_bypasses_cache(
        self, tmp_storage_dir, monkeypatch, cli_module, utils_module
    ):
        """Test --ignore-cache bypasses cache during extraction."""
        import sqlite_utils

        from clerk.utils import (
            build_db_from_text_internal,
            hash_text_content,
            save_extraction_cache,
        )

        # Set up storage directory
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(utils_module, "STORAGE_DIR", str(tmp_storage_dir))

        subdomain = "forcetest.civic.band"
        site_dir = tmp_storage_dir / subdomain
        txt_dir = site_dir / "txt" / "city-council" / "2024-01-15"
        txt_dir.mkdir(parents=True)

        # Create test file (4-digit naming like real pages)
        text_file = txt_dir / "0001.txt"
        text_content = "Original meeting text"
        text_file.write_text(text_content)

        # Create stale cache with wrong data
        cache_file = str(text_file) + ".extracted.json"
        content_hash = hash_text_content(text_content)
        stale_cache = {
            "content_hash": content_hash,
            "model_version": "en_core_web_md",
            "extracted_at": "2020-01-01T00:00:00Z",
            "entities": {"persons": ["Stale Person"], "orgs": [], "locations": []},
            "votes": {"votes": []},
        }
        save_extraction_cache(cache_file, stale_cache)

        # Create initial database for backup
        db_path = site_dir / "meetings.db"
        db = sqlite_utils.Database(db_path)
        db["sites"].insert(
            {
                "subdomain": subdomain,
                "name": "Force Test City",
                "state": "CA",
                "country": "USA",
            },
            pk="subdomain",
        )
        db.close()

        # Enable extraction
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")

        # Build database first
        build_db_from_text_internal(subdomain, extract_entities=False)

        # Run extraction with ignore_cache=True to bypass cache
        build_db_from_text_internal(subdomain, extract_entities=True, ignore_cache=True)

        # Cache should be overwritten with fresh extraction
        import json

        with open(cache_file) as f:
            new_cache = json.load(f)

        # Timestamp should be updated (not 2020)
        assert new_cache["extracted_at"] > "2025-01-01"


@pytest.mark.integration
class TestChunkedProcessing:
    """Integration tests for chunked processing performance optimization."""

    @pytest.mark.slow
    def test_chunked_processing_integration(self, tmp_path, monkeypatch):
        """Integration test for chunked processing with realistic data."""
        # Lower chunk size for testing
        monkeypatch.setattr("clerk.utils.SPACY_CHUNK_SIZE", 100)
        monkeypatch.delenv("SPACY_N_PROCESS", raising=False)

        # Create test site structure
        site_dir = tmp_path / "test.civic.band"
        site_dir.mkdir()

        # Create proper directory structure: txt/Meeting/Date/
        minutes_dir = site_dir / "txt" / "City Council" / "2024-01-01"
        minutes_dir.mkdir(parents=True)

        # Create 250 text files to trigger chunking (100 + 100 + 50)
        for i in range(250):
            page_file = minutes_dir / f"{i + 1}.txt"
            page_file.write_text(f"Meeting content page {i}\nSome text here.")

        db_path = site_dir / "site.db"
        db = sqlite_utils.Database(db_path)

        from clerk.utils import build_table_from_text

        # Should complete without errors and process all pages
        build_table_from_text(
            db=db, subdomain="test.civic.band", table_name="minutes", txt_dir=str(site_dir / "txt")
        )

        # Verify all pages were processed
        records = list(db["minutes"].rows)
        assert len(records) == 250

        # Verify database has expected structure
        assert "text" in db["minutes"].columns_dict
        assert "meeting" in db["minutes"].columns_dict


@pytest.mark.integration
class TestExtractionIntegration:
    """End-to-end tests for text extraction pipeline."""

    def test_full_extraction_pipeline(self, tmp_path, monkeypatch):
        """Test extraction from text files to searchable database."""
        import json

        import sqlite_utils

        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")

        # Create test site structure
        site_dir = tmp_path / "test-site"
        txt_dir = site_dir / "txt" / "CityCouncil" / "2024-01-15"
        txt_dir.mkdir(parents=True)

        # Page 1: Roll call (4-digit naming)
        (txt_dir / "0001.txt").write_text(
            "City Council Meeting - January 15, 2024\n"
            "Roll Call: Members present were Smith, Jones, Lee, Brown, Garcia.\n"
        )

        # Page 2: Discussion and vote (4-digit naming)
        (txt_dir / "0002.txt").write_text(
            "Motion by Smith, seconded by Jones.\n"
            "The motion to approve the budget passed 5-0.\n"
            "Ayes: Smith, Jones, Lee, Brown, Garcia. Nays: None.\n"
        )

        # Create empty meetings.db to be replaced
        (site_dir / "meetings.db").touch()

        import importlib

        import clerk.extraction
        import clerk.utils

        importlib.reload(clerk.extraction)
        importlib.reload(clerk.utils)

        from clerk.utils import build_db_from_text_internal

        build_db_from_text_internal("test-site", extract_entities=True)

        # Verify extraction results
        db = sqlite_utils.Database(site_dir / "meetings.db")
        rows = list(db["minutes"].rows)

        assert len(rows) == 2

        # Check page 2 has vote extraction
        page2 = [r for r in rows if r["page"] == 2][0]
        votes = json.loads(page2["votes_json"])

        assert len(votes["votes"]) >= 1
        vote = votes["votes"][0]
        assert vote["result"] == "passed"
        assert vote["tally"]["ayes"] == 5
        assert vote["motion_by"] == "Smith"
        assert vote["seconded_by"] == "Jones"

        # Check entities extraction
        entities = json.loads(page2["entities_json"])
        assert "persons" in entities
        assert "orgs" in entities
        assert "locations" in entities

    def test_extraction_disabled_produces_empty_json(self, tmp_path, monkeypatch):
        """When extraction disabled, JSON columns have empty structures."""
        import json

        import sqlite_utils

        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.delenv("ENABLE_EXTRACTION", raising=False)

        # Create test site structure
        site_dir = tmp_path / "test-site"
        txt_dir = site_dir / "txt" / "CityCouncil" / "2024-01-15"
        txt_dir.mkdir(parents=True)

        (txt_dir / "1.txt").write_text("The motion passed 5-0.")
        (site_dir / "meetings.db").touch()

        import importlib

        import clerk.extraction
        import clerk.utils

        importlib.reload(clerk.extraction)
        importlib.reload(clerk.utils)

        from clerk.utils import build_db_from_text_internal

        build_db_from_text_internal("test-site")

        db = sqlite_utils.Database(site_dir / "meetings.db")
        rows = list(db["minutes"].rows)

        assert len(rows) == 1
        entities = json.loads(rows[0]["entities_json"])
        votes = json.loads(rows[0]["votes_json"])

        # When disabled, should have empty structures
        assert entities == {"persons": [], "orgs": [], "locations": []}
        assert votes == {"votes": []}
