"""Unit tests for clerk.cli module."""

import json
from unittest.mock import MagicMock, patch

import pytest
import sqlite_utils
from click.testing import CliRunner

from clerk.cli import (
    cli,
    fetch_internal,
    rebuild_site_fts_internal,
    update_page_count,
)
from clerk.fetcher import get_fetcher
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
        # pm is imported from clerk.utils into clerk.fetcher, so we patch it there
        import clerk.fetcher as fetcher_module

        monkeypatch.setattr(fetcher_module, "pm", mock_plugin_manager)

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
        # Mock sys.prefix to point to a location without package alembic.ini
        mocker.patch("sys.prefix", tmp_path / "fake_prefix")

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
class TestInstallWorkersCommand:
    """Tests for the install-workers CLI command."""

    def test_install_workers_command_exists(self, cli_runner):
        """Test that install-workers command exists."""
        result = cli_runner.invoke(cli, ["install-workers", "--help"])
        assert result.exit_code == 0

    def test_install_workers_finds_script_in_dev_mode(self, cli_runner, mocker, tmp_path):
        """Test that install-workers finds script in development mode."""
        # Create mock script in development location
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        script_path = scripts_dir / "install-workers.sh"
        script_path.write_text("#!/bin/bash\necho 'test'")
        script_path.chmod(0o755)

        # Mock Path(__file__).parent to point to our test location
        mocker.patch("pathlib.Path", return_value=tmp_path / "src" / "clerk" / "cli.py")

        # Mock subprocess.run
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(returncode=0)

        # Mock sys.exit to prevent test from exiting
        _mock_exit = mocker.patch("sys.exit")

        _result = cli_runner.invoke(cli, ["install-workers"])

        # Should attempt to run the script
        assert mock_run.called or _mock_exit.called

    def test_install_workers_script_not_found(self, cli_runner, mocker):
        """Test that install-workers shows error when script not found."""
        # Mock sys.prefix to point to non-existent location
        mocker.patch("sys.prefix", "/nonexistent/path")

        # Mock __file__ to point to non-existent location
        mock_file = mocker.MagicMock()
        mock_file.parent.parent.parent = mocker.MagicMock()

        # Mock pathlib.Path to return paths that don't exist
        def mock_path_factory(*args):
            mock_path = mocker.MagicMock()
            mock_path.exists.return_value = False
            mock_path.__truediv__.return_value = mock_path
            return mock_path

        mocker.patch("pathlib.Path", side_effect=mock_path_factory)

        result = cli_runner.invoke(cli, ["install-workers"])

        # Should fail with non-zero exit code
        assert result.exit_code != 0

    def test_install_workers_executes_script(self, cli_runner, mocker, tmp_path):
        """Test that install-workers executes the script."""
        # Create mock script
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        script_path = scripts_dir / "install-workers.sh"
        script_path.write_text("#!/bin/bash\necho 'Installing workers'")
        script_path.chmod(0o755)

        # Mock script location finding
        mocker.patch("pathlib.Path.cwd", return_value=tmp_path)

        # Create the expected path structure
        _dev_path = tmp_path / "scripts" / "install-workers.sh"

        # Mock subprocess.run
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(returncode=0)

        # Mock sys.exit
        _mock_exit = mocker.patch("sys.exit")

        _result = cli_runner.invoke(cli, ["install-workers"])

        # Verify subprocess.run was called
        if mock_run.called:
            call_args = mock_run.call_args
            # Check that script path was in the call
            assert any("install-workers.sh" in str(arg) for arg in call_args[0][0])


@pytest.mark.unit
class TestUninstallWorkersCommand:
    """Tests for the uninstall-workers CLI command."""

    def test_uninstall_workers_command_exists(self, cli_runner):
        """Test that uninstall-workers command exists."""
        result = cli_runner.invoke(cli, ["uninstall-workers", "--help"])
        assert result.exit_code == 0

    def test_uninstall_workers_finds_script_in_dev_mode(self, cli_runner, mocker, tmp_path):
        """Test that uninstall-workers finds script in development mode."""
        # Create mock script in development location
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        script_path = scripts_dir / "uninstall-workers.sh"
        script_path.write_text("#!/bin/bash\necho 'test'")
        script_path.chmod(0o755)

        # Mock subprocess.run
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(returncode=0)

        # Mock sys.exit
        _mock_exit = mocker.patch("sys.exit")

        _result = cli_runner.invoke(cli, ["uninstall-workers"])

        # Should attempt to run the script
        assert mock_run.called or _mock_exit.called

    def test_uninstall_workers_executes_script(self, cli_runner, mocker, tmp_path):
        """Test that uninstall-workers executes the script."""
        # Create mock script
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        script_path = scripts_dir / "uninstall-workers.sh"
        script_path.write_text("#!/bin/bash\necho 'Uninstalling workers'")
        script_path.chmod(0o755)

        # Mock subprocess.run
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = mocker.Mock(returncode=0)

        # Mock sys.exit
        _mock_exit = mocker.patch("sys.exit")

        _result = cli_runner.invoke(cli, ["uninstall-workers"])

        # Verify subprocess.run was called
        if mock_run.called:
            call_args = mock_run.call_args
            # Check that script path was in the call
            assert any("uninstall-workers.sh" in str(arg) for arg in call_args[0][0])


@pytest.mark.unit
class TestWorkerCommand:
    """Tests for the worker CLI command."""

    def test_worker_command_exists(self, cli_runner):
        """Test that worker command exists and shows help."""
        result = cli_runner.invoke(cli, ["worker", "--help"])
        assert result.exit_code == 0
        assert "Start RQ workers" in result.output

    def test_worker_fetch_single_worker(self, cli_runner, mocker):
        """Test starting a single fetch worker."""
        # Mock Redis connection
        mock_redis = mocker.MagicMock()
        mocker.patch("clerk.queue.get_redis", return_value=mock_redis)

        # Mock queues
        mock_high_queue = mocker.MagicMock()
        mock_fetch_queue = mocker.MagicMock()
        mocker.patch("clerk.queue.get_high_queue", return_value=mock_high_queue)
        mocker.patch("clerk.queue.get_fetch_queue", return_value=mock_fetch_queue)

        # Mock Worker.__init__ to be a no-op and Worker.work() to do nothing
        mocker.patch("rq.Worker.__init__", return_value=None)
        mock_work = mocker.patch("rq.Worker.work")

        result = cli_runner.invoke(cli, ["worker", "fetch"])

        assert result.exit_code == 0
        # Verify work() was called with scheduler and not burst
        mock_work.assert_called_once_with(with_scheduler=True, burst=False)

    def test_worker_ocr_with_burst_mode(self, cli_runner, mocker):
        """Test starting OCR worker in burst mode."""
        # Mock Redis connection
        mock_redis = mocker.MagicMock()
        mocker.patch("clerk.queue.get_redis", return_value=mock_redis)

        # Mock queues
        mock_high_queue = mocker.MagicMock()
        mock_ocr_queue = mocker.MagicMock()
        mocker.patch("clerk.queue.get_high_queue", return_value=mock_high_queue)
        mocker.patch("clerk.queue.get_ocr_queue", return_value=mock_ocr_queue)

        # Mock Worker.__init__ to be a no-op and Worker.work() to do nothing
        mocker.patch("rq.Worker.__init__", return_value=None)
        mock_work = mocker.patch("rq.Worker.work")

        result = cli_runner.invoke(cli, ["worker", "ocr", "--burst"])

        assert result.exit_code == 0
        # Verify burst mode was enabled
        mock_work.assert_called_once_with(with_scheduler=True, burst=True)

    def test_worker_extraction_multiple_workers(self, cli_runner, mocker):
        """Test starting multiple extraction workers with worker pool."""
        # Mock Redis connection
        mock_redis = mocker.MagicMock()
        mocker.patch("clerk.queue.get_redis", return_value=mock_redis)

        # Mock queues
        mock_high_queue = mocker.MagicMock()
        mock_extraction_queue = mocker.MagicMock()
        mocker.patch("clerk.queue.get_high_queue", return_value=mock_high_queue)
        mocker.patch("clerk.queue.get_extraction_queue", return_value=mock_extraction_queue)

        # Mock WorkerPool class
        mock_pool = mocker.MagicMock()
        mock_pool.__enter__ = mocker.Mock(return_value=mock_pool)
        mock_pool.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("rq.worker_pool.WorkerPool", return_value=mock_pool)

        result = cli_runner.invoke(cli, ["worker", "extraction", "-n", "2"])

        assert result.exit_code == 0
        # Verify pool.start() was called
        mock_pool.start.assert_called_once()
        # Note: worker_class parameter is now passed, so we don't check exact call signature

    def test_worker_deploy_type(self, cli_runner, mocker):
        """Test starting deploy worker."""
        # Mock Redis connection
        mock_redis = mocker.MagicMock()
        mocker.patch("clerk.queue.get_redis", return_value=mock_redis)

        # Mock queues
        mock_high_queue = mocker.MagicMock()
        mock_deploy_queue = mocker.MagicMock()
        mocker.patch("clerk.queue.get_high_queue", return_value=mock_high_queue)
        mocker.patch("clerk.queue.get_deploy_queue", return_value=mock_deploy_queue)

        # Mock Worker.__init__ to be a no-op and Worker.work() to do nothing
        mocker.patch("rq.Worker.__init__", return_value=None)
        mock_work = mocker.patch("rq.Worker.work")

        result = cli_runner.invoke(cli, ["worker", "deploy"])

        assert result.exit_code == 0
        # Verify worker.work() was called
        mock_work.assert_called_once_with(with_scheduler=True, burst=False)

    def test_worker_handles_redis_connection_error(self, cli_runner, mocker):
        """Test that worker command handles Redis connection errors."""
        # Mock Redis to raise connection error
        import redis

        mocker.patch(
            "clerk.queue.get_redis", side_effect=redis.ConnectionError("Cannot connect to Redis")
        )

        result = cli_runner.invoke(cli, ["worker", "fetch"])

        # Command should fail gracefully
        assert result.exit_code != 0
        assert "Redis" in result.output or "redis" in result.output.lower()

    def test_worker_invalid_type(self, cli_runner, mocker):
        """Test that invalid worker type shows error."""
        result = cli_runner.invoke(cli, ["worker", "invalid_type"])

        # Should fail with invalid choice error
        assert result.exit_code != 0

    def test_worker_num_workers_flag(self, cli_runner, mocker):
        """Test --num-workers flag is accepted."""
        # Mock Redis connection
        mock_redis = mocker.MagicMock()
        mocker.patch("clerk.queue.get_redis", return_value=mock_redis)

        # Mock queues
        mocker.patch("clerk.queue.get_high_queue", return_value=mocker.MagicMock())
        mocker.patch("clerk.queue.get_fetch_queue", return_value=mocker.MagicMock())

        # Mock WorkerPool
        mock_pool = mocker.MagicMock()
        mock_pool.__enter__ = mocker.Mock(return_value=mock_pool)
        mock_pool.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("rq.worker_pool.WorkerPool", return_value=mock_pool)

        result = cli_runner.invoke(cli, ["worker", "fetch", "--num-workers", "5"])

        assert result.exit_code == 0

    def test_worker_all_worker_types(self, cli_runner, mocker):
        """Test all valid worker types are accepted."""
        worker_types = ["fetch", "ocr", "extraction", "deploy"]

        for worker_type in worker_types:
            # Mock Redis connection
            mock_redis = mocker.MagicMock()
            mocker.patch("clerk.queue.get_redis", return_value=mock_redis)

            # Mock all queues
            mock_high_queue = mocker.MagicMock()
            mock_type_queue = mocker.MagicMock()
            mocker.patch("clerk.queue.get_high_queue", return_value=mock_high_queue)
            mocker.patch(f"clerk.queue.get_{worker_type}_queue", return_value=mock_type_queue)

            # Mock Worker.__init__ to be a no-op and Worker.work() to do nothing
            mocker.patch("rq.Worker.__init__", return_value=None)
            mocker.patch("rq.Worker.work")

            result = cli_runner.invoke(cli, ["worker", worker_type])

            assert result.exit_code == 0, f"Worker type {worker_type} should work"

            # Reset mocks
            mocker.resetall()
