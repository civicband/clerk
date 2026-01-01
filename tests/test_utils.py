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
        monkeypatch.chdir(tmp_path)

        # Create clean database
        db = assert_db_exists()

        # Get initial table count
        initial_tables = set(db.table_names())

        # Call again - should not create any new tables
        db = assert_db_exists()
        final_tables = set(db.table_names())

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


class TestBuildTableFromTextExtraction:
    """Tests for extraction integration in build_table_from_text."""

    def test_extraction_populates_json_columns(self, tmp_path, monkeypatch):
        """Extraction produces valid JSON in new columns."""
        import importlib
        import json

        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        # Create test structure
        site_dir = tmp_path / "test-site"
        txt_dir = site_dir / "txt" / "CityCouncil" / "2024-01-15"
        txt_dir.mkdir(parents=True)

        (txt_dir / "1.txt").write_text("Present: Smith, Jones, Lee.\nThe motion passed 5-0.")

        db = sqlite_utils.Database(":memory:")
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

        import clerk.utils

        importlib.reload(clerk.utils)

        from clerk.utils import build_table_from_text

        build_table_from_text("test-site", str(site_dir / "txt"), db, "minutes")

        rows = list(db["minutes"].rows)
        assert len(rows) == 1

        entities = json.loads(rows[0]["entities_json"])
        votes = json.loads(rows[0]["votes_json"])

        assert "persons" in entities
        assert "votes" in votes


class TestSpacyChunkSize:
    """Tests for SPACY_CHUNK_SIZE constant."""

    def test_spacy_chunk_size_constant_exists(self):
        """Test that SPACY_CHUNK_SIZE constant is defined."""
        from clerk.utils import SPACY_CHUNK_SIZE
        assert SPACY_CHUNK_SIZE == 20_000


def test_spacy_n_process_default_is_two(mocker, monkeypatch, tmp_path):
    """Test that SPACY_N_PROCESS defaults to 2."""
    # Clear any existing env var
    monkeypatch.delenv("SPACY_N_PROCESS", raising=False)

    # Mock get_nlp to avoid spaCy dependency
    mock_nlp = mocker.MagicMock()
    # Make pipe return a mock doc for each text passed in
    mock_doc = mocker.MagicMock()
    mock_nlp.pipe.return_value = iter([mock_doc])
    mocker.patch("clerk.utils.get_nlp", return_value=mock_nlp)
    mocker.patch("clerk.utils.EXTRACTION_ENABLED", True)

    # Mock extraction and context functions to avoid dependencies
    mocker.patch("clerk.utils.create_meeting_context", return_value={})
    mocker.patch("clerk.utils.extract_entities", return_value={"persons": [], "orgs": [], "locations": []})
    mocker.patch("clerk.utils.detect_roll_call", return_value=None)
    mocker.patch("clerk.utils.extract_votes", return_value={"votes": []})
    mocker.patch("clerk.utils.update_context")

    # Create minimal test data
    import sqlite_utils

    from clerk.utils import build_table_from_text

    db = sqlite_utils.Database(str(tmp_path / "test.db"))

    # Create directory structure: txt_dir/meeting/meeting_date/page.txt
    txt_dir = tmp_path / "txt"
    meeting_dir = txt_dir / "CityCouncil"
    date_dir = meeting_dir / "2024-01-01"
    date_dir.mkdir(parents=True)

    # Create a test page file
    (date_dir / "1.txt").write_text("test content")

    build_table_from_text(
        subdomain="test",
        txt_dir=str(txt_dir),
        db=db,
        table_name="minutes"
    )

    # Check that nlp.pipe was called with n_process=2
    call_kwargs = mock_nlp.pipe.call_args[1]
    assert call_kwargs.get("n_process") == 2


class TestChunkedProcessing:
    """Tests for chunked processing of large batches."""

    def test_small_batch_no_chunking(self, mocker, monkeypatch, tmp_path):
        """Test that batches under SPACY_CHUNK_SIZE are not chunked."""
        monkeypatch.delenv("SPACY_N_PROCESS", raising=False)

        # Mock get_nlp
        mock_nlp = mocker.MagicMock()
        mock_docs = [mocker.MagicMock() for _ in range(100)]
        mock_nlp.pipe.return_value = iter(mock_docs)
        mocker.patch("clerk.utils.get_nlp", return_value=mock_nlp)
        mocker.patch("clerk.utils.EXTRACTION_ENABLED", True)

        # Create 100 text files (under CHUNK_SIZE)
        txt_dir = tmp_path / "txt"
        txt_dir.mkdir()
        meeting_dir = txt_dir / "CityCouncil"
        meeting_dir.mkdir()
        date_dir = meeting_dir / "2024-01-15"
        date_dir.mkdir()
        for i in range(100):
            (date_dir / f"{i}.txt").write_text(f"content {i}")

        db = sqlite_utils.Database(tmp_path / "test.db")
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

        from clerk.utils import build_table_from_text
        build_table_from_text(
            db=db,
            subdomain="test",
            table_name="minutes",
            txt_dir=str(txt_dir)
        )

        # Should call nlp.pipe exactly once (no chunking)
        assert mock_nlp.pipe.call_count == 1

    def test_large_batch_uses_chunking(self, mocker, monkeypatch, tmp_path):
        """Test that batches over SPACY_CHUNK_SIZE are chunked."""
        monkeypatch.delenv("SPACY_N_PROCESS", raising=False)
        monkeypatch.setattr("clerk.utils.SPACY_CHUNK_SIZE", 100)  # Lower threshold for testing

        # Mock get_nlp
        mock_nlp = mocker.MagicMock()
        # Return different docs for each call
        mock_nlp.pipe.side_effect = [
            iter([mocker.MagicMock() for _ in range(100)]),  # First chunk
            iter([mocker.MagicMock() for _ in range(50)]),   # Second chunk
        ]
        mocker.patch("clerk.utils.get_nlp", return_value=mock_nlp)
        mocker.patch("clerk.utils.EXTRACTION_ENABLED", True)

        # Mock gc.collect to verify it's called
        mock_gc = mocker.patch("gc.collect")

        # Create 150 text files (over CHUNK_SIZE of 100)
        txt_dir = tmp_path / "txt"
        txt_dir.mkdir()
        meeting_dir = txt_dir / "CityCouncil"
        meeting_dir.mkdir()
        date_dir = meeting_dir / "2024-01-15"
        date_dir.mkdir()
        for i in range(150):
            (date_dir / f"{i}.txt").write_text(f"content {i}")

        db = sqlite_utils.Database(tmp_path / "test.db")
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

        from clerk.utils import build_table_from_text
        build_table_from_text(
            db=db,
            subdomain="test",
            table_name="minutes",
            txt_dir=str(txt_dir)
        )

        # Should call nlp.pipe twice (2 chunks: 100 + 50)
        assert mock_nlp.pipe.call_count == 2

        # Should call gc.collect once (after first chunk, not after last)
        assert mock_gc.call_count == 1
