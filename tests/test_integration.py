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

        # Also patch pipeline module's pm
        import clerk.pipeline
        monkeypatch.setattr(clerk.pipeline, "pm", mock_plugin_manager)

        runner = CliRunner()

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
        self, tmp_path, tmp_storage_dir, sample_text_files, monkeypatch, cli_module
    ):
        """Test the complete database building workflow."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))

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
        self, tmp_path, tmp_storage_dir, monkeypatch, mock_plugin_manager, cli_module
    ):
        """Test a complete pipeline: create → fetch → build → deploy."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))

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

        # Also patch pipeline module's pm
        import clerk.pipeline
        monkeypatch.setattr(clerk.pipeline, "pm", mock_plugin_manager)

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

    def test_fts_search_works_end_to_end(self, tmp_storage_dir, monkeypatch, cli_module):
        """Test that full-text search works after building database."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))

        subdomain = "search-test.civic.band"
        site_dir = tmp_storage_dir / subdomain
        site_dir.mkdir()

        # Create text files with searchable content
        minutes_dir = site_dir / "txt" / "Council" / "2024-01-01"
        minutes_dir.mkdir(parents=True)
        (minutes_dir / "1.txt").write_text("Discussion about parks and recreation")
        (minutes_dir / "2.txt").write_text("Budget allocation for infrastructure")

        # Build database
        from clerk.cli import build_db_from_text_internal

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
                "lat": "0",
                "lng": "0",
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
                "lat": "0",
                "lng": "0",
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

    def test_build_db_creates_backup(self, tmp_storage_dir, monkeypatch, cli_module):
        """Test that building database creates a backup of existing db."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))

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
        from clerk.cli import build_db_from_text_internal

        build_db_from_text_internal(subdomain)

        # Check backup exists
        backup_path = site_dir / "meetings.db.bk"
        assert backup_path.exists()

        # Check old data is in backup
        backup_db = sqlite_utils.Database(backup_path)
        assert "old_data" in backup_db.table_names()
        assert backup_db["old_data"].count == 1
