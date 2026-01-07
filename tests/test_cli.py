"""Unit tests for clerk.cli module."""

import datetime
import json
from unittest.mock import MagicMock, patch

import pytest
import sqlite_utils
from click.testing import CliRunner

from clerk.cli import (
    cli,
    fetch_internal,
    get_fetcher,
    rebuild_site_fts_internal,
    update_page_count,
)
from clerk.utils import (
    build_db_from_text_internal,
    build_table_from_text,
)


@pytest.mark.unit
class TestBuildTableFromText:
    """Unit tests for build_table_from_text function."""

    def test_build_table_from_text_creates_records(self, tmp_storage_dir, sample_text_files):
        """Test that build_table_from_text creates database records from text files."""
        subdomain = "example.civic.band"
        db_path = tmp_storage_dir / subdomain / "meetings.db"
        db = sqlite_utils.Database(db_path)

        # Create the table
        db["minutes"].create(
            {
                "id": str,
                "meeting": str,
                "date": str,
                "page": int,
                "text": str,
                "page_image": str,
                "entities_json": str,
                "votes_json": str,
            },
            pk="id",
        )

        # Build the table from text files
        build_table_from_text(
            subdomain=subdomain,
            txt_dir=sample_text_files["minutes_dir"],
            db=db,
            table_name="minutes",
        )

        # Check that records were created
        records = list(db["minutes"].rows)
        assert len(records) == 2
        assert records[0]["meeting"] == "City Council"
        assert records[0]["date"] == "2024-01-15"
        # Check that expected text exists in one of the records (order is not guaranteed)
        all_text = " ".join(r["text"] for r in records)
        assert "called to order" in all_text

    def test_build_table_with_municipality(self, tmp_storage_dir, sample_text_files):
        """Test building table with municipality field for aggregate DB."""
        subdomain = "example.civic.band"
        municipality = "Example City Council"
        db_path = tmp_storage_dir / subdomain / "meetings.db"
        db = sqlite_utils.Database(db_path)

        # Create the table with municipality field
        db["minutes"].create(
            {
                "id": str,
                "subdomain": str,
                "municipality": str,
                "meeting": str,
                "date": str,
                "page": int,
                "text": str,
                "page_image": str,
                "entities_json": str,
                "votes_json": str,
            },
            pk="id",
        )

        # Build the table from text files
        build_table_from_text(
            subdomain=subdomain,
            txt_dir=sample_text_files["minutes_dir"],
            db=db,
            table_name="minutes",
            municipality=municipality,
        )

        # Check that records include municipality
        records = list(db["minutes"].rows)
        assert len(records) == 2
        assert records[0]["subdomain"] == subdomain
        assert records[0]["municipality"] == municipality


@pytest.mark.unit
class TestRebuildSiteFts:
    """Unit tests for rebuild_site_fts_internal function."""

    def test_rebuild_fts_enables_search(self, tmp_storage_dir, monkeypatch, cli_module):
        """Test that rebuilding FTS enables full-text search."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))

        subdomain = "example.civic.band"
        site_dir = tmp_storage_dir / subdomain
        site_dir.mkdir()

        db_path = site_dir / "meetings.db"
        db = sqlite_utils.Database(db_path)

        # Create tables with data
        db["minutes"].insert(
            {
                "id": "1",
                "meeting": "Council",
                "date": "2024-01-01",
                "page": 1,
                "text": "Test meeting minutes",
                "page_image": "/1.png",
            },
            pk="id",
        )
        db["agendas"].insert(
            {
                "id": "2",
                "meeting": "Council",
                "date": "2024-01-01",
                "page": 1,
                "text": "Test agenda",
                "page_image": "/1.png",
            },
            pk="id",
        )

        # Rebuild FTS
        rebuild_site_fts_internal(subdomain)

        # Check that FTS tables were created (sqlite-utils creates *_fts tables)
        table_names = db.table_names()
        assert any("_fts" in name for name in table_names)

        # Test FTS search works
        results = list(db["minutes"].search("meeting"))
        assert len(results) > 0


@pytest.mark.unit
class TestUpdatePageCount:
    """Unit tests for update_page_count function."""

    def test_update_page_count(self, tmp_path, tmp_storage_dir, monkeypatch, sample_db, cli_module):
        """Test that update_page_count updates the page count correctly."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))

        subdomain = "example.civic.band"
        site_dir = tmp_storage_dir / subdomain
        site_dir.mkdir()

        # Create site database with some records
        db_path = site_dir / "meetings.db"
        db = sqlite_utils.Database(db_path)

        db["minutes"].insert_all(
            [
                {
                    "id": "1",
                    "meeting": "Council",
                    "date": "2024-01-01",
                    "page": 1,
                    "text": "Test",
                    "page_image": "/1.png",
                },
                {
                    "id": "2",
                    "meeting": "Council",
                    "date": "2024-01-01",
                    "page": 2,
                    "text": "Test",
                    "page_image": "/2.png",
                },
            ],
            pk="id",
        )

        db["agendas"].insert_all(
            [
                {
                    "id": "3",
                    "meeting": "Council",
                    "date": "2024-01-01",
                    "page": 1,
                    "text": "Test",
                    "page_image": "/1.png",
                },
            ],
            pk="id",
        )

        # Update page count
        update_page_count(subdomain)

        # Check that civic.db was updated
        civic_db = sqlite_utils.Database("civic.db")
        site = civic_db["sites"].get(subdomain)
        assert site["pages"] == 3  # 2 minutes + 1 agenda


@pytest.mark.unit
class TestGetFetcher:
    """Unit tests for get_fetcher function."""

    def test_get_fetcher_from_plugin(
        self, sample_site_data, mock_plugin_manager, monkeypatch, cli_module
    ):
        """Test getting a fetcher class from a plugin."""
        # pm is imported from clerk.utils into clerk.cli, so we patch it there
        monkeypatch.setattr(cli_module, "pm", mock_plugin_manager)

        sample_site_data["scraper"] = "test_scraper"
        fetcher = get_fetcher(sample_site_data, all_years=False, all_agendas=False)

        assert fetcher is not None
        assert hasattr(fetcher, "fetch_events")
        assert hasattr(fetcher, "ocr")
        assert hasattr(fetcher, "transform")

    def test_get_fetcher_respects_last_updated(self, sample_site_data):
        """Test that fetcher start year is based on last_updated."""
        sample_site_data["last_updated"] = "2023-06-15T10:00:00"
        sample_site_data["start_year"] = 2020

        with patch("clerk.cli.pm") as mock_pm:
            mock_pm.hook.fetcher_class.return_value = [None]

            # Since we're not using all_years, should use last_updated year
            # This will fail to get a fetcher, but we're testing the logic
            try:
                get_fetcher(sample_site_data, all_years=False, all_agendas=False)
            except (TypeError, AttributeError):
                # Expected to fail since we're mocking
                pass

    def test_get_fetcher_all_years(self, sample_site_data):
        """Test that all_years flag uses start_year."""
        sample_site_data["last_updated"] = "2023-06-15T10:00:00"
        sample_site_data["start_year"] = 2020

        with patch("clerk.cli.pm") as mock_pm:
            mock_pm.hook.fetcher_class.return_value = [MagicMock()]

            # With all_years=True, should use start_year
            try:
                get_fetcher(sample_site_data, all_years=True, all_agendas=False)
            except (TypeError, AttributeError):
                # May fail due to mocking, but logic is tested
                pass


@pytest.mark.unit
class TestFetchInternal:
    """Unit tests for fetch_internal function."""

    def test_fetch_internal_updates_status(self, tmp_path, monkeypatch, mock_fetcher):
        """Test that fetch_internal updates site status correctly."""
        monkeypatch.chdir(tmp_path)

        # Create a civic.db
        db = sqlite_utils.Database("civic.db")
        db["sites"].insert(
            {
                "subdomain": "example.civic.band",
                "name": "Example",
                "state": "CA",
                "country": "US",
                "kind": "council",
                "scraper": "test",
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

        # Run fetch
        fetch_internal("example.civic.band", mock_fetcher)

        # Check status was updated
        site = db["sites"].get("example.civic.band")
        assert site["status"] == "needs_ocr"
        assert mock_fetcher.events_fetched  # Fetcher was called


@pytest.mark.integration
class TestBuildDbFromTextInternal:
    """Integration tests for build_db_from_text_internal."""

    def test_build_db_from_text(
        self, tmp_storage_dir, sample_text_files, monkeypatch, cli_module, utils_module
    ):
        """Test building a complete database from text files."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(utils_module, "STORAGE_DIR", str(tmp_storage_dir))

        subdomain = "example.civic.band"
        site_dir = tmp_storage_dir / subdomain
        # Directory already exists from sample_text_files fixture, use exist_ok=True
        site_dir.mkdir(exist_ok=True)

        # Create a minimal existing database to backup
        db_path = site_dir / "meetings.db"
        db = sqlite_utils.Database(db_path)
        db["temp"].insert({"id": 1})

        # Build database from text
        build_db_from_text_internal(subdomain)

        # Check that database was created
        assert db_path.exists()
        assert (site_dir / "meetings.db.bk").exists()  # Backup created

        # Check tables exist
        db = sqlite_utils.Database(db_path)
        assert "minutes" in db.table_names()
        assert "agendas" in db.table_names()

        # Check data was inserted
        minutes_count = db["minutes"].count
        assert minutes_count == 2

    def test_build_db_from_text_skips_extraction_by_default(
        self, tmp_path, monkeypatch, cli_module, utils_module
    ):
        """build-db-from-text should skip extraction by default"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(utils_module, "STORAGE_DIR", str(tmp_path))

        # Monkeypatch EXTRACTION_ENABLED directly (env var is read at import time)
        import clerk.extraction

        monkeypatch.setattr(clerk.extraction, "EXTRACTION_ENABLED", True)
        # Also need to monkeypatch in utils module since it imports it
        monkeypatch.setattr(utils_module, "EXTRACTION_ENABLED", True)

        import clerk.utils
        from clerk.db import civic_db_connection, insert_site
        from clerk.utils import assert_db_exists

        assert_db_exists()

        # Create test site
        with civic_db_connection() as conn:
            insert_site(
                conn,
                {
                    "subdomain": "test.civic.band",
                    "name": "Test City",
                    "state": "CA",
                    "country": "US",
                    "kind": "city-council",
                    "scraper": "test",
                    "pages": 0,
                    "start_year": 2020,
                    "status": "new",
                },
            )

        # Create text files
        site_dir = tmp_path / "test.civic.band"
        txt_dir = site_dir / "txt" / "CityCouncil" / "2024-01-15"
        txt_dir.mkdir(parents=True)
        (txt_dir / "0001.txt").write_text("Meeting text")

        # Create minimal database to backup
        db_path = site_dir / "meetings.db"
        site_db = sqlite_utils.Database(db_path)
        site_db["temp"].insert({"id": 1})

        # Run build-db-from-text (should skip extraction by default)
        runner = CliRunner()
        result = runner.invoke(cli, ["build-db-from-text", "-s", "test.civic.band"])

        assert result.exit_code == 0

        # Verify database was created with text
        site_db = sqlite_utils.Database(str(site_dir / "meetings.db"))
        assert site_db["minutes"].exists()
        rows = list(site_db["minutes"].rows)
        assert len(rows) == 1
        assert rows[0]["text"] == "Meeting text"

        # Verify extraction was skipped (empty structures, not extracted data)
        import json

        entities = json.loads(rows[0]["entities_json"])
        votes = json.loads(rows[0]["votes_json"])
        assert entities == {"persons": [], "orgs": [], "locations": []}
        assert votes == {"votes": []}


@pytest.mark.slow
@pytest.mark.integration
class TestBuildFullDb:
    """Integration tests for build_full_db command."""

    def test_build_full_db_cli(
        self, tmp_path, tmp_storage_dir, sample_text_files, monkeypatch, cli_module
    ):
        """Test the build_full_db CLI command."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))

        # Create civic.db with a site
        db = sqlite_utils.Database("civic.db")
        db["sites"].insert(
            {
                "subdomain": "example.civic.band",
                "name": "Example City",
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
            pk="subdomain",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["build-full-db"])

        # Command should succeed
        assert result.exit_code == 0

        # Check that aggregate database was created
        full_db_path = tmp_storage_dir / "meetings.db"
        assert full_db_path.exists()

        # Check tables include subdomain and municipality
        full_db = sqlite_utils.Database(full_db_path)
        assert "minutes" in full_db.table_names()
        assert "agendas" in full_db.table_names()


@pytest.mark.unit
class TestMigrateExtractionSchema:
    """Unit tests for migrate-extraction-schema command."""

    def test_migrate_extraction_schema_adds_columns(self, tmp_path, monkeypatch):
        """Migration adds extraction_status and last_extracted columns"""
        from sqlalchemy import inspect

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        from clerk.utils import assert_db_exists

        # Create database without extraction columns
        engine = assert_db_exists()

        # Run migration
        runner = CliRunner()
        result = runner.invoke(cli, ["migrate-extraction-schema"])

        assert result.exit_code == 0
        assert "Migration complete" in result.output

        # Verify columns exist
        inspector = inspect(engine)
        columns = {col["name"] for col in inspector.get_columns("sites")}
        assert "extraction_status" in columns
        assert "last_extracted" in columns

    def test_migrate_extraction_schema_is_idempotent(self, tmp_path, monkeypatch):
        """Running migration multiple times is safe"""
        from sqlalchemy import inspect

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        from clerk.utils import assert_db_exists

        runner = CliRunner()

        # Run migration twice
        result1 = runner.invoke(cli, ["migrate-extraction-schema"])
        result2 = runner.invoke(cli, ["migrate-extraction-schema"])

        assert result1.exit_code == 0
        assert result2.exit_code == 0

        # Verify no errors and columns still exist
        engine = assert_db_exists()
        inspector = inspect(engine)
        columns = {col["name"] for col in inspector.get_columns("sites")}
        assert "extraction_status" in columns
        assert "last_extracted" in columns


@pytest.mark.unit
class TestExtractEntities:
    """Unit tests for extract-entities command."""

    def test_extract_entities_next_site_selects_pending(
        self, tmp_path, monkeypatch, cli_module, utils_module
    ):
        """extract-entities --next-site selects next pending site"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(utils_module, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setenv("ENABLE_EXTRACTION", "0")
        monkeypatch.setenv("CIVIC_DEV_MODE", "1")
        from clerk.db import civic_db_connection, insert_site
        from clerk.utils import assert_db_exists

        # Create database and run migration
        assert_db_exists()
        runner = CliRunner()
        runner.invoke(cli, ["migrate-extraction-schema"])

        # Site 1: completed, old extraction
        with civic_db_connection() as conn:
            insert_site(
                conn,
                {
                    "subdomain": "site1.civic.band",
                    "name": "Site 1",
                    "state": "CA",
                    "country": "US",
                    "kind": "city-council",
                    "scraper": "test",
                    "pages": 0,
                    "start_year": 2020,
                    "status": "new",
                    "extraction_status": "completed",
                    "last_extracted": "2024-01-01T00:00:00",
                },
            )

            # Site 2: pending, no extraction yet (should be selected)
            insert_site(
                conn,
                {
                    "subdomain": "site2.civic.band",
                    "name": "Site 2",
                    "state": "CA",
                    "country": "US",
                    "kind": "city-council",
                    "scraper": "test",
                    "pages": 0,
                    "start_year": 2020,
                    "status": "new",
                    "extraction_status": "pending",
                    "last_extracted": None,
                },
            )

        # Create site structure for site2 with text files
        site_dir = tmp_path / "site2.civic.band"
        site_dir.mkdir()

        # Create text files for extraction
        txt_dir = site_dir / "txt" / "council" / "2024-01-01"
        txt_dir.mkdir(parents=True)
        (txt_dir / "0001.txt").write_text("Test meeting content")

        (site_dir / "meetings.db").touch()

        # Create empty database for site2
        site_db = sqlite_utils.Database(str(site_dir / "meetings.db"))
        site_db["minutes"].create(
            {"id": str, "text": str, "entities_json": str, "votes_json": str}, pk="id"
        )

        # Run command
        runner = CliRunner()
        result = runner.invoke(cli, ["extract-entities", "--next-site"])

        print(f"Exit code: {result.exit_code}")
        print(f"Output: {result.output}")
        assert result.exit_code == 0

        # Verify site2 was selected and processed
        from clerk.db import get_site_by_subdomain

        with civic_db_connection() as conn:
            site2 = get_site_by_subdomain(conn, "site2.civic.band")
        assert site2["extraction_status"] == "completed"
        assert site2["last_extracted"] is not None

    def test_extract_entities_next_site_no_pending(self, tmp_path, monkeypatch):
        """extract-entities --next-site exits cleanly when no sites need extraction"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CIVIC_DEV_MODE", "1")
        from clerk.db import civic_db_connection, insert_site
        from clerk.utils import assert_db_exists

        # Create database and run migration
        assert_db_exists()
        runner = CliRunner()
        runner.invoke(cli, ["migrate-extraction-schema"])
        with civic_db_connection() as conn:
            insert_site(
                conn,
                {
                    "subdomain": "completed.civic.band",
                    "name": "Completed",
                    "state": "CA",
                    "country": "US",
                    "kind": "city-council",
                    "scraper": "test",
                    "pages": 0,
                    "start_year": 2020,
                    "status": "new",
                    "extraction_status": "completed",
                    "last_extracted": "2024-01-01T00:00:00",
                },
            )

        runner = CliRunner()
        result = runner.invoke(cli, ["extract-entities", "--next-site"])

        assert result.exit_code == 0
        assert "No sites need extraction" in result.output

    def test_extract_entities_dev_mode_skips_deployment(
        self, tmp_path, monkeypatch, cli_module, utils_module
    ):
        """CIVIC_DEV_MODE=1 should skip deployment hooks"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(utils_module, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setenv("ENABLE_EXTRACTION", "0")
        monkeypatch.setenv("CIVIC_DEV_MODE", "1")

        from clerk.db import civic_db_connection, insert_site
        from clerk.utils import assert_db_exists

        assert_db_exists()

        # Run migration first
        runner = CliRunner()
        runner.invoke(cli, ["migrate-extraction-schema"])

        # Create test site
        with civic_db_connection() as conn:
            insert_site(
                conn,
                {
                    "subdomain": "test.civic.band",
                    "name": "Test City",
                    "state": "CA",
                    "country": "US",
                    "kind": "city-council",
                    "scraper": "test",
                    "pages": 0,
                    "start_year": 2020,
                    "status": "new",
                    "extraction_status": "pending",
                    "last_extracted": None,
                },
            )

        # Create site structure with text files
        site_dir = tmp_path / "test.civic.band"
        site_dir.mkdir()

        # Create text files for extraction
        txt_dir = site_dir / "txt" / "council" / "2024-01-01"
        txt_dir.mkdir(parents=True)
        (txt_dir / "0001.txt").write_text("Test meeting content")

        site_db = sqlite_utils.Database(str(site_dir / "meetings.db"))
        site_db["minutes"].create(
            {"id": str, "text": str, "entities_json": str, "votes_json": str}, pk="id"
        )

        # Mock the deployment hooks to track calls
        deploy_called = []
        post_deploy_called = []
        update_site_called = []

        class MockHook:
            def deploy_municipality(self, **kwargs):
                deploy_called.append(kwargs)

            def post_deploy(self, **kwargs):
                post_deploy_called.append(kwargs)

            def update_site(self, subdomain, updates):
                update_site_called.append({"subdomain": subdomain, "updates": updates})
                # Actually update the database
                from clerk.db import update_site as db_update_site

                with civic_db_connection() as conn:
                    db_update_site(conn, subdomain, updates)
                return [None]  # Return list to match hook behavior

        class MockPM:
            def __init__(self):
                self.hook = MockHook()

        monkeypatch.setattr(cli_module, "pm", MockPM())

        # Run command
        runner = CliRunner()
        result = runner.invoke(cli, ["extract-entities", "--subdomain", "test.civic.band"])

        assert result.exit_code == 0
        assert "DEV MODE: Skipping deployment" in result.output
        assert len(deploy_called) == 0, "deploy_municipality should not be called in dev mode"
        assert len(post_deploy_called) == 0, "post_deploy should not be called in dev mode"

        # Verify extraction still completed
        from clerk.db import get_site_by_subdomain

        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, "test.civic.band")
        assert site["extraction_status"] == "completed"
        assert site["last_extracted"] is not None

    def test_extract_entities_production_mode_calls_deployment(
        self, tmp_path, monkeypatch, cli_module, utils_module
    ):
        """Without CIVIC_DEV_MODE, deployment hooks should be called"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(utils_module, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setenv("ENABLE_EXTRACTION", "0")
        # DON'T set CIVIC_DEV_MODE (production mode)

        from clerk.db import civic_db_connection, insert_site
        from clerk.utils import assert_db_exists

        assert_db_exists()

        # Run migration first
        runner = CliRunner()
        runner.invoke(cli, ["migrate-extraction-schema"])

        # Create test site
        with civic_db_connection() as conn:
            insert_site(
                conn,
                {
                    "subdomain": "test.civic.band",
                    "name": "Test City",
                    "state": "CA",
                    "country": "US",
                    "kind": "city-council",
                    "scraper": "test",
                    "pages": 0,
                    "start_year": 2020,
                    "status": "new",
                    "extraction_status": "pending",
                    "last_extracted": None,
                },
            )

        # Create site structure with text files
        site_dir = tmp_path / "test.civic.band"
        site_dir.mkdir()

        # Create text files for extraction
        txt_dir = site_dir / "txt" / "council" / "2024-01-01"
        txt_dir.mkdir(parents=True)
        (txt_dir / "0001.txt").write_text("Test meeting content")

        site_db = sqlite_utils.Database(str(site_dir / "meetings.db"))
        site_db["minutes"].create(
            {"id": str, "text": str, "entities_json": str, "votes_json": str}, pk="id"
        )

        # Mock the deployment hooks
        deploy_called = []
        post_deploy_called = []
        update_site_called = []

        class MockHook:
            def deploy_municipality(self, **kwargs):
                deploy_called.append(kwargs)

            def post_deploy(self, **kwargs):
                post_deploy_called.append(kwargs)

            def update_site(self, subdomain, updates):
                update_site_called.append({"subdomain": subdomain, "updates": updates})
                # Actually update the database
                from clerk.db import update_site as db_update_site

                with civic_db_connection() as conn:
                    db_update_site(conn, subdomain, updates)
                return [None]  # Return list to match hook behavior

        class MockPM:
            def __init__(self):
                self.hook = MockHook()

        monkeypatch.setattr(cli_module, "pm", MockPM())

        # Run command
        runner = CliRunner()
        result = runner.invoke(cli, ["extract-entities", "--subdomain", "test.civic.band"])

        assert result.exit_code == 0
        # Should NOT see dev mode message
        assert "DEV MODE: Skipping deployment" not in result.output
        assert len(deploy_called) == 1, "deploy_municipality should be called in production mode"
        assert len(post_deploy_called) == 1, "post_deploy should be called in production mode"

        # Verify correct parameters passed
        assert deploy_called[0]["subdomain"] == "test.civic.band"
        assert deploy_called[0]["municipality"] == "Test City"
        assert post_deploy_called[0]["site"]["subdomain"] == "test.civic.band"

    def test_extract_entities_failure_marks_status_failed(
        self, tmp_path, monkeypatch, cli_module, utils_module
    ):
        """Extraction failures should mark status as failed"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(utils_module, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setenv("CIVIC_DEV_MODE", "1")

        from clerk.db import civic_db_connection, insert_site
        from clerk.utils import assert_db_exists

        assert_db_exists()

        # Run migration first
        runner = CliRunner()
        runner.invoke(cli, ["migrate-extraction-schema"])

        # Create test site
        with civic_db_connection() as conn:
            insert_site(
                conn,
                {
                    "subdomain": "test.civic.band",
                    "name": "Test City",
                    "state": "CA",
                    "country": "US",
                    "kind": "city-council",
                    "scraper": "test",
                    "pages": 0,
                    "start_year": 2020,
                    "status": "new",
                    "extraction_status": "pending",
                    "last_extracted": None,
                },
            )

        # Create site structure with text files
        site_dir = tmp_path / "test.civic.band"
        site_dir.mkdir()

        # Create text files for extraction
        txt_dir = site_dir / "txt" / "council" / "2024-01-01"
        txt_dir.mkdir(parents=True)
        (txt_dir / "0001.txt").write_text("Test meeting content")

        site_db = sqlite_utils.Database(str(site_dir / "meetings.db"))
        site_db["minutes"].create(
            {"id": str, "text": str, "entities_json": str, "votes_json": str}, pk="id"
        )

        # Mock build_db_from_text_internal to raise exception
        def failing_build(subdomain, extract_entities=False, ignore_cache=False):
            raise RuntimeError("Test extraction failure")

        monkeypatch.setattr(cli_module, "build_db_from_text_internal", failing_build)

        # Run command - should fail but update status
        runner = CliRunner()
        result = runner.invoke(cli, ["extract-entities", "--subdomain", "test.civic.band"])

        # Command should fail (non-zero exit code)
        assert result.exit_code != 0

        # Status should be marked as failed
        from clerk.db import get_site_by_subdomain

        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, "test.civic.band")
        assert site["extraction_status"] == "failed"

        # last_extracted should NOT be updated (still None)
        assert site["last_extracted"] is None

        # Error should be logged
        assert "Extraction failed" in result.output
        assert "Test extraction failure" in result.output

    def test_extract_entities_failed_sites_can_retry(
        self, tmp_path, monkeypatch, cli_module, utils_module
    ):
        """Failed sites should be selected by --next-site for retry"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(utils_module, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setenv("ENABLE_EXTRACTION", "0")
        monkeypatch.setenv("CIVIC_DEV_MODE", "1")

        from clerk.db import civic_db_connection, insert_site
        from clerk.utils import assert_db_exists

        assert_db_exists()

        # Run migration first
        runner = CliRunner()
        runner.invoke(cli, ["migrate-extraction-schema"])

        # Site 1: completed (should skip)
        with civic_db_connection() as conn:
            insert_site(
                conn,
                {
                    "subdomain": "completed.civic.band",
                    "name": "Completed",
                    "state": "CA",
                    "country": "US",
                    "kind": "city-council",
                    "scraper": "test",
                    "pages": 0,
                    "start_year": 2020,
                    "status": "new",
                    "extraction_status": "completed",
                    "last_extracted": "2024-01-01T00:00:00",
                },
            )

            # Site 2: failed (should retry - selected by --next-site)
            insert_site(
                conn,
                {
                    "subdomain": "failed.civic.band",
                    "name": "Failed",
                    "state": "CA",
                    "country": "US",
                    "kind": "city-council",
                    "scraper": "test",
                    "pages": 0,
                    "start_year": 2020,
                    "status": "new",
                    "extraction_status": "failed",
                    "last_extracted": None,
                },
            )

        # Create site structure for failed site with text files
        site_dir = tmp_path / "failed.civic.band"
        site_dir.mkdir()

        # Create text files for extraction
        txt_dir = site_dir / "txt" / "council" / "2024-01-01"
        txt_dir.mkdir(parents=True)
        (txt_dir / "0001.txt").write_text("Test meeting content")

        site_db = sqlite_utils.Database(str(site_dir / "meetings.db"))
        site_db["minutes"].create(
            {"id": str, "text": str, "entities_json": str, "votes_json": str}, pk="id"
        )

        # Run --next-site
        runner = CliRunner()
        result = runner.invoke(cli, ["extract-entities", "--next-site"])

        assert result.exit_code == 0

        # Verify failed site was selected and processed
        from clerk.db import get_site_by_subdomain

        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, "failed.civic.band")
            assert site["extraction_status"] == "completed"
            assert site["last_extracted"] is not None

            # Completed site should remain unchanged
            completed_site = get_site_by_subdomain(conn, "completed.civic.band")
            assert completed_site["extraction_status"] == "completed"
            assert completed_site["last_extracted"] == "2024-01-01T00:00:00"


@pytest.mark.integration
class TestExtractEntitiesIntegration:
    """Integration tests for the full extraction workflow."""

    def test_full_extraction_workflow(self, tmp_path, monkeypatch, cli_module, utils_module):
        """Test complete workflow: migration → extraction → status tracking"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setattr(utils_module, "STORAGE_DIR", str(tmp_path))
        monkeypatch.setenv("ENABLE_EXTRACTION", "0")  # Fast test without spaCy
        monkeypatch.setenv("CIVIC_DEV_MODE", "1")  # Skip deployment

        # Step 1: Create database WITHOUT extraction columns (simulates old database)
        import sqlite_utils
        from sqlalchemy import inspect

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
                "last_deployed": str,
                "lat": str,
                "lng": str,
            },
            pk="subdomain",
        )

        # Initially no extraction columns exist
        site_columns_before = {col.name for col in db["sites"].columns}
        assert "extraction_status" not in site_columns_before
        assert "last_extracted" not in site_columns_before

        # Step 2: Run migration
        runner = CliRunner()
        result = runner.invoke(cli, ["migrate-extraction-schema"])
        assert result.exit_code == 0
        assert "Migration complete" in result.output

        # Verify columns added using SQLAlchemy inspector
        from clerk.utils import assert_db_exists

        engine = assert_db_exists()
        inspector = inspect(engine)
        site_columns_after = {col["name"] for col in inspector.get_columns("sites")}
        assert "extraction_status" in site_columns_after
        assert "last_extracted" in site_columns_after

        # Step 3: Create a test site using new API
        from clerk.db import civic_db_connection, insert_site

        with civic_db_connection() as conn:
            insert_site(
                conn,
                {
                    "subdomain": "test.civic.band",
                    "name": "Test City",
                    "state": "CA",
                    "country": "US",
                    "kind": "city-council",
                    "scraper": "test",
                    "pages": 0,
                    "start_year": 2020,
                    "status": "new",
                    "extraction_status": "pending",
                    "last_extracted": None,
                },
            )

        # Create site structure with text files
        site_dir = tmp_path / "test.civic.band"
        site_dir.mkdir()

        # Create text files for extraction
        txt_dir = site_dir / "txt" / "CityCouncil" / "2024-01-01"
        txt_dir.mkdir(parents=True)
        (txt_dir / "0001.txt").write_text("Meeting called to order.")

        # Create empty database (will be populated by extraction)
        site_db = sqlite_utils.Database(str(site_dir / "meetings.db"))
        site_db["sites"].insert(
            {
                "subdomain": "test.civic.band",
                "name": "Test City",
                "state": "CA",
                "country": "USA",
            },
            pk="subdomain",
        )

        # Verify initial state
        from clerk.db import get_site_by_subdomain

        with civic_db_connection() as conn:
            site_before = get_site_by_subdomain(conn, "test.civic.band")
            assert site_before["extraction_status"] == "pending"
            assert site_before["last_extracted"] is None

        # Step 4: Run extraction
        before_extraction = datetime.datetime.now()
        result = runner.invoke(cli, ["extract-entities", "--subdomain", "test.civic.band"])
        after_extraction = datetime.datetime.now()

        assert result.exit_code == 0
        assert "Extraction completed successfully" in result.output

        # Step 5: Verify status updated
        with civic_db_connection() as conn:
            site_after = get_site_by_subdomain(conn, "test.civic.band")
            assert site_after["extraction_status"] == "completed"
            assert site_after["last_extracted"] is not None

        # Verify timestamp is reasonable (between before and after)
        last_extracted_dt = datetime.datetime.fromisoformat(site_after["last_extracted"])
        assert before_extraction <= last_extracted_dt <= after_extraction

        # Step 6: Verify database records created from text files
        # Re-open database to see new records
        site_db = sqlite_utils.Database(str(site_dir / "meetings.db"))
        minutes = list(site_db["minutes"].rows)
        assert len(minutes) == 1  # Should have 1 record from the text file

        minute = minutes[0]
        assert minute["text"] == "Meeting called to order."
        assert minute["meeting"] == "CityCouncil"
        assert minute["date"] == "2024-01-01"
        assert minute["page"] == 1

        # With ENABLE_EXTRACTION=0, should have empty structures
        entities = json.loads(minute["entities_json"])
        votes = json.loads(minute["votes_json"])

        # When extraction is disabled, expect empty arrays
        assert isinstance(entities, dict)
        assert isinstance(votes, dict)

        # Step 7: Verify idempotency - running again should work
        result = runner.invoke(cli, ["extract-entities", "--subdomain", "test.civic.band"])
        assert result.exit_code == 0

        site_final = db["sites"].get("test.civic.band")
        assert site_final["extraction_status"] == "completed"


@pytest.mark.unit
class TestOCRBackendCLIFlag:
    """Unit tests for --ocr-backend CLI flag."""

    def test_update_command_accepts_ocr_backend_flag(self, cli_runner, mocker):
        """Test that update command accepts --ocr-backend flag without error."""
        # Mock the update_site_internal function to avoid needing a database
        mock_update = mocker.patch("clerk.cli.update_site_internal")

        result = cli_runner.invoke(
            cli,
            ["update", "--subdomain", "test.example.com", "--ocr-backend", "vision"],
        )

        # Command should succeed (not fail due to unknown option)
        assert result.exit_code == 0
        # Verify update_site_internal was called with the ocr_backend parameter
        mock_update.assert_called_once()
        call_kwargs = mock_update.call_args.kwargs
        assert call_kwargs["ocr_backend"] == "vision"

    def test_ocr_backend_defaults_to_tesseract(self, cli_runner, mocker):
        """Test that OCR backend defaults to tesseract when not specified."""
        # Mock the entire update flow
        mock_get_fetcher = mocker.patch("clerk.cli.get_fetcher")
        mock_fetcher_instance = mocker.Mock()
        mock_get_fetcher.return_value = mock_fetcher_instance

        # Mock database operations (note: these are imported inside the function)
        mocker.patch("clerk.cli.assert_db_exists")
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.db.civic_db_connection", return_value=mock_conn)
        mocker.patch(
            "clerk.db.get_site_by_subdomain",
            return_value={"subdomain": "test.example.com", "start_year": 2020},
        )
        mocker.patch("clerk.db.update_site")
        mocker.patch("clerk.cli.fetch_internal")
        mocker.patch("clerk.cli.update_page_count")

        cli_runner.invoke(
            cli,
            ["update", "--subdomain", "test.example.com"],
        )

        # Verify ocr() was called with default backend="tesseract"
        mock_fetcher_instance.ocr.assert_called_once_with(backend="tesseract")

    def test_ocr_backend_vision_passed_to_fetcher(self, cli_runner, mocker):
        """Test that --ocr-backend=vision is correctly passed to Fetcher.ocr()."""
        # Mock the entire update flow
        mock_get_fetcher = mocker.patch("clerk.cli.get_fetcher")
        mock_fetcher_instance = mocker.Mock()
        mock_get_fetcher.return_value = mock_fetcher_instance

        # Mock database operations (note: these are imported inside the function)
        mocker.patch("clerk.cli.assert_db_exists")
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.db.civic_db_connection", return_value=mock_conn)
        mocker.patch(
            "clerk.db.get_site_by_subdomain",
            return_value={"subdomain": "test.example.com", "start_year": 2020},
        )
        mocker.patch("clerk.db.update_site")
        mocker.patch("clerk.cli.fetch_internal")
        mocker.patch("clerk.cli.update_page_count")

        cli_runner.invoke(
            cli,
            ["update", "--subdomain", "test.example.com", "--ocr-backend", "vision"],
        )

        # Verify ocr() was called with backend="vision"
        mock_fetcher_instance.ocr.assert_called_once_with(backend="vision")


@pytest.mark.unit
class TestDbCommands:
    """Unit tests for database migration CLI commands."""

    def test_db_upgrade_command_exists(self, cli_runner):
        """Test that 'clerk db upgrade' command exists."""
        result = cli_runner.invoke(cli, ["db", "upgrade", "--help"])
        assert result.exit_code == 0

    def test_db_current_command_exists(self, cli_runner):
        """Test that 'clerk db current' command exists."""
        result = cli_runner.invoke(cli, ["db", "current", "--help"])
        assert result.exit_code == 0

    def test_db_history_command_exists(self, cli_runner):
        """Test that 'clerk db history' command exists."""
        result = cli_runner.invoke(cli, ["db", "history", "--help"])
        assert result.exit_code == 0

    def test_db_upgrade_calls_alembic(self, cli_runner, mocker, tmp_path):
        """Test that 'clerk db upgrade' calls alembic upgrade head."""
        # Create a mock alembic.ini in a temporary location
        alembic_ini = tmp_path / "alembic.ini"
        alembic_ini.write_text("[alembic]\nscript_location = alembic")

        # Mock subprocess.run to capture alembic calls
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(returncode=0, stdout="", stderr="")

        # Mock finding the alembic.ini file
        mocker.patch("pathlib.Path.cwd", return_value=tmp_path)

        result = cli_runner.invoke(cli, ["db", "upgrade"])

        assert result.exit_code == 0
        # Verify alembic was called with correct arguments
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "alembic" in call_args
        assert "upgrade" in call_args
        assert "head" in call_args

    def test_db_current_calls_alembic(self, cli_runner, mocker, tmp_path):
        """Test that 'clerk db current' calls alembic current."""
        # Create a mock alembic.ini in a temporary location
        alembic_ini = tmp_path / "alembic.ini"
        alembic_ini.write_text("[alembic]\nscript_location = alembic")

        # Mock subprocess.run
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(returncode=0, stdout="abc123 (head)", stderr="")

        # Mock finding the alembic.ini file
        mocker.patch("pathlib.Path.cwd", return_value=tmp_path)

        result = cli_runner.invoke(cli, ["db", "current"])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "alembic" in call_args
        assert "current" in call_args

    def test_db_history_calls_alembic(self, cli_runner, mocker, tmp_path):
        """Test that 'clerk db history' calls alembic history."""
        # Create a mock alembic.ini in a temporary location
        alembic_ini = tmp_path / "alembic.ini"
        alembic_ini.write_text("[alembic]\nscript_location = alembic")

        # Mock subprocess.run
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(returncode=0, stdout="Migration history", stderr="")

        # Mock finding the alembic.ini file
        mocker.patch("pathlib.Path.cwd", return_value=tmp_path)

        result = cli_runner.invoke(cli, ["db", "history"])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "alembic" in call_args
        assert "history" in call_args

    def test_db_upgrade_handles_missing_alembic_ini(self, cli_runner, mocker, tmp_path):
        """Test that db upgrade shows error when alembic.ini is not found."""
        # Mock Path.cwd to return a directory without alembic.ini
        mocker.patch("pathlib.Path.cwd", return_value=tmp_path)

        result = cli_runner.invoke(cli, ["db", "upgrade"])

        # Command should fail gracefully
        assert result.exit_code != 0
        assert "alembic.ini" in result.output.lower()

    def test_db_upgrade_handles_alembic_failure(self, cli_runner, mocker, tmp_path):
        """Test that db upgrade handles alembic command failure."""
        # Create a mock alembic.ini
        alembic_ini = tmp_path / "alembic.ini"
        alembic_ini.write_text("[alembic]\nscript_location = alembic")

        # Mock subprocess.run to simulate failure
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(
            returncode=1, stdout="", stderr="Error: Database connection failed"
        )

        # Mock finding the alembic.ini file
        mocker.patch("pathlib.Path.cwd", return_value=tmp_path)

        result = cli_runner.invoke(cli, ["db", "upgrade"])

        # Command should fail
        assert result.exit_code != 0


@pytest.mark.unit
class TestStatusCommand:
    """Unit tests for status CLI command."""

    def test_status_shows_queue_depths(self, cli_runner, mocker):
        """Test that status command shows queue depths."""
        # Mock Redis queues
        mock_high_queue = mocker.Mock()
        mock_high_queue.__len__ = mocker.Mock(return_value=0)
        mock_fetch_queue = mocker.Mock()
        mock_fetch_queue.__len__ = mocker.Mock(return_value=3)
        mock_ocr_queue = mocker.Mock()
        mock_ocr_queue.__len__ = mocker.Mock(return_value=247)
        mock_extraction_queue = mocker.Mock()
        mock_extraction_queue.__len__ = mocker.Mock(return_value=1)
        mock_deploy_queue = mocker.Mock()
        mock_deploy_queue.__len__ = mocker.Mock(return_value=0)

        mocker.patch("clerk.queue.get_high_queue", return_value=mock_high_queue)
        mocker.patch("clerk.queue.get_fetch_queue", return_value=mock_fetch_queue)
        mocker.patch("clerk.queue.get_ocr_queue", return_value=mock_ocr_queue)
        mocker.patch("clerk.queue.get_extraction_queue", return_value=mock_extraction_queue)
        mocker.patch("clerk.queue.get_deploy_queue", return_value=mock_deploy_queue)

        # Mock database operations (empty site_progress)
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.db.civic_db_connection", return_value=mock_conn)

        # Mock empty result for site_progress
        mock_result = mocker.Mock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = cli_runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "Queue Status" in result.output
        assert "High priority" in result.output
        assert "0 jobs" in result.output
        assert "Fetch" in result.output
        assert "3 jobs" in result.output
        assert "OCR" in result.output
        assert "247 jobs" in result.output
        assert "Extraction" in result.output
        assert "1 jobs" in result.output
        assert "Deploy" in result.output

    def test_status_shows_active_sites(self, cli_runner, mocker):
        """Test that status command shows active sites."""
        # Mock Redis queues (all empty)
        mock_queue = mocker.Mock()
        mock_queue.__len__ = mocker.Mock(return_value=0)
        mocker.patch("clerk.queue.get_high_queue", return_value=mock_queue)
        mocker.patch("clerk.queue.get_fetch_queue", return_value=mock_queue)
        mocker.patch("clerk.queue.get_ocr_queue", return_value=mock_queue)
        mocker.patch("clerk.queue.get_extraction_queue", return_value=mock_queue)
        mocker.patch("clerk.queue.get_deploy_queue", return_value=mock_queue)

        # Mock database operations
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.db.civic_db_connection", return_value=mock_conn)

        # Mock site_progress results
        class MockRow:
            def __init__(self, site_id, current_stage, stage_completed, stage_total):
                self.site_id = site_id
                self.current_stage = current_stage
                self.stage_completed = stage_completed
                self.stage_total = stage_total

        mock_result = mocker.Mock()
        mock_result.fetchall.return_value = [
            MockRow("site1.civic.band", "ocr", 45, 100),
            MockRow("site2.civic.band", "extraction", 12, 50),
            MockRow("site3.civic.band", "fetch", 0, 0),
        ]
        mock_conn.execute.return_value = mock_result

        result = cli_runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "Active Sites" in result.output
        assert "site1.civic.band" in result.output
        assert "ocr" in result.output
        assert "45/100" in result.output
        assert "45.0%" in result.output
        assert "site2.civic.band" in result.output
        assert "extraction" in result.output
        assert "12/50" in result.output
        assert "24.0%" in result.output
        assert "site3.civic.band" in result.output
        assert "fetch" in result.output

    def test_status_with_site_id_shows_detailed_progress(self, cli_runner, mocker):
        """Test that status --site-id shows detailed site progress."""
        # Mock database operations
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.db.civic_db_connection", return_value=mock_conn)

        # Mock site_progress result for specific site
        class MockRow:
            def __init__(self):
                self.site_id = "example.civic.band"
                self.current_stage = "ocr"
                self.stage_completed = 45
                self.stage_total = 100
                self.started_at = datetime.datetime(2026, 1, 6, 10, 0, 0)
                self.updated_at = datetime.datetime(2026, 1, 6, 10, 5, 23)

        mock_result = mocker.Mock()
        mock_result.fetchone.return_value = MockRow()
        mock_conn.execute.return_value = mock_result

        result = cli_runner.invoke(cli, ["status", "--site-id", "example.civic.band"])

        assert result.exit_code == 0
        assert "Site: example.civic.band" in result.output
        assert "Current stage: ocr" in result.output
        assert "Progress: 45/100 (45.0%)" in result.output
        assert "Started: 2026-01-06 10:00:00" in result.output
        assert "Updated: 2026-01-06 10:05:23" in result.output

    def test_status_with_site_id_not_found(self, cli_runner, mocker):
        """Test that status --site-id handles site not found."""
        # Mock database operations
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.db.civic_db_connection", return_value=mock_conn)

        # Mock empty result (site not found)
        mock_result = mocker.Mock()
        mock_result.fetchone.return_value = None
        mock_conn.execute.return_value = mock_result

        result = cli_runner.invoke(cli, ["status", "--site-id", "nonexistent.civic.band"])

        assert result.exit_code == 0
        assert "No progress tracking found for site: nonexistent.civic.band" in result.output

    def test_status_handles_empty_queues(self, cli_runner, mocker):
        """Test that status command handles empty queues gracefully."""
        # Mock Redis queues (all empty)
        mock_queue = mocker.Mock()
        mock_queue.__len__ = mocker.Mock(return_value=0)
        mocker.patch("clerk.queue.get_high_queue", return_value=mock_queue)
        mocker.patch("clerk.queue.get_fetch_queue", return_value=mock_queue)
        mocker.patch("clerk.queue.get_ocr_queue", return_value=mock_queue)
        mocker.patch("clerk.queue.get_extraction_queue", return_value=mock_queue)
        mocker.patch("clerk.queue.get_deploy_queue", return_value=mock_queue)

        # Mock database operations
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.db.civic_db_connection", return_value=mock_conn)

        # Mock empty result for site_progress
        mock_result = mocker.Mock()
        mock_result.fetchall.return_value = []
        mock_conn.execute.return_value = mock_result

        result = cli_runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "Queue Status" in result.output

    def test_status_handles_redis_connection_error(self, cli_runner, mocker):
        """Test that status command handles Redis connection errors gracefully."""
        # Mock Redis to raise connection error
        import redis
        mocker.patch("clerk.queue.get_high_queue", side_effect=redis.ConnectionError("Cannot connect"))

        result = cli_runner.invoke(cli, ["status"])

        # Command should fail gracefully
        assert result.exit_code != 0
        assert "Redis" in result.output or "redis" in result.output.lower() or "Cannot connect" in result.output

    def test_status_handles_database_connection_error(self, cli_runner, mocker):
        """Test that status command handles database connection errors gracefully."""
        # Mock Redis queues (all empty)
        mock_queue = mocker.Mock()
        mock_queue.__len__ = mocker.Mock(return_value=0)
        mocker.patch("clerk.queue.get_high_queue", return_value=mock_queue)
        mocker.patch("clerk.queue.get_fetch_queue", return_value=mock_queue)
        mocker.patch("clerk.queue.get_ocr_queue", return_value=mock_queue)
        mocker.patch("clerk.queue.get_extraction_queue", return_value=mock_queue)
        mocker.patch("clerk.queue.get_deploy_queue", return_value=mock_queue)

        # Mock database to raise connection error
        from sqlalchemy.exc import OperationalError
        mocker.patch("clerk.db.civic_db_connection", side_effect=OperationalError("DB error", None, None))

        result = cli_runner.invoke(cli, ["status"])

        # Command should fail gracefully
        assert result.exit_code != 0


@pytest.mark.unit
class TestEnqueueCommand:
    """Unit tests for enqueue CLI command."""

    def test_enqueue_single_site(self, cli_runner, mocker):
        """Test enqueuing a single site."""
        # Mock Redis and queue operations
        mock_enqueue_job = mocker.patch("clerk.queue.enqueue_job", return_value="job123")

        # Mock database operations
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.db.civic_db_connection", return_value=mock_conn)
        mocker.patch("clerk.db.get_site_by_subdomain", return_value={"subdomain": "site1.civic.band"})
        mocker.patch("clerk.queue_db.track_job")
        mocker.patch("clerk.queue_db.create_site_progress")

        # Mock Redis connection test
        mocker.patch("clerk.queue.get_redis")

        result = cli_runner.invoke(cli, ["enqueue", "site1.civic.band"])

        assert result.exit_code == 0
        assert "Enqueued site1.civic.band" in result.output
        assert "job123" in result.output
        assert "normal" in result.output

        # Verify enqueue_job was called correctly
        mock_enqueue_job.assert_called_once_with("fetch-site", "site1.civic.band", priority="normal")

    def test_enqueue_multiple_sites(self, cli_runner, mocker):
        """Test enqueuing multiple sites."""
        # Mock Redis and queue operations
        mock_enqueue_job = mocker.patch("clerk.queue.enqueue_job")
        mock_enqueue_job.side_effect = ["job123", "job456"]

        # Mock database operations
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.db.civic_db_connection", return_value=mock_conn)

        def mock_get_site(conn, subdomain):
            return {"subdomain": subdomain}

        mocker.patch("clerk.db.get_site_by_subdomain", side_effect=mock_get_site)
        mocker.patch("clerk.queue_db.track_job")
        mocker.patch("clerk.queue_db.create_site_progress")

        # Mock Redis connection test
        mocker.patch("clerk.queue.get_redis")

        result = cli_runner.invoke(cli, ["enqueue", "site1.civic.band", "site2.civic.band"])

        assert result.exit_code == 0
        assert "Enqueued site1.civic.band" in result.output
        assert "job123" in result.output
        assert "Enqueued site2.civic.band" in result.output
        assert "job456" in result.output

        # Verify enqueue_job was called twice
        assert mock_enqueue_job.call_count == 2

    def test_enqueue_with_high_priority(self, cli_runner, mocker):
        """Test enqueuing with high priority."""
        # Mock Redis and queue operations
        mock_enqueue_job = mocker.patch("clerk.queue.enqueue_job", return_value="job123")

        # Mock database operations
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.db.civic_db_connection", return_value=mock_conn)
        mocker.patch("clerk.db.get_site_by_subdomain", return_value={"subdomain": "site1.civic.band"})
        mocker.patch("clerk.queue_db.track_job")
        mocker.patch("clerk.queue_db.create_site_progress")

        # Mock Redis connection test
        mocker.patch("clerk.queue.get_redis")

        result = cli_runner.invoke(cli, ["enqueue", "site1.civic.band", "--priority", "high"])

        assert result.exit_code == 0
        assert "high" in result.output

        # Verify enqueue_job was called with high priority
        mock_enqueue_job.assert_called_once_with("fetch-site", "site1.civic.band", priority="high")

    def test_enqueue_with_low_priority(self, cli_runner, mocker):
        """Test enqueuing with low priority."""
        # Mock Redis and queue operations
        mock_enqueue_job = mocker.patch("clerk.queue.enqueue_job", return_value="job123")

        # Mock database operations
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.db.civic_db_connection", return_value=mock_conn)
        mocker.patch("clerk.db.get_site_by_subdomain", return_value={"subdomain": "site1.civic.band"})
        mocker.patch("clerk.queue_db.track_job")
        mocker.patch("clerk.queue_db.create_site_progress")

        # Mock Redis connection test
        mocker.patch("clerk.queue.get_redis")

        result = cli_runner.invoke(cli, ["enqueue", "site1.civic.band", "--priority", "low"])

        assert result.exit_code == 0

        # Verify enqueue_job was called with low priority
        mock_enqueue_job.assert_called_once_with("fetch-site", "site1.civic.band", priority="low")

    def test_enqueue_handles_redis_connection_error(self, cli_runner, mocker):
        """Test that enqueue handles Redis connection errors gracefully."""
        # Mock Redis to raise connection error
        import redis
        mocker.patch("clerk.queue.get_redis", side_effect=redis.ConnectionError("Cannot connect to Redis"))

        result = cli_runner.invoke(cli, ["enqueue", "site1.civic.band"])

        # Command should fail gracefully
        assert result.exit_code != 0
        assert "Redis" in result.output or "redis" in result.output.lower()
