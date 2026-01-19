"""Unit tests for clerk.utils module."""

import json
import os
from pathlib import Path

import sqlite_utils

from clerk.utils import STORAGE_DIR, assert_db_exists, pm


class TestAssertDbExists:
    """Tests for the assert_db_exists function."""

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


class TestBuildTableFromTextExtraction:
    """Tests for extraction integration in build_table_from_text."""

    def test_extraction_populates_json_columns(self, tmp_path, monkeypatch):
        """Extraction produces valid JSON in new columns."""
        import importlib

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


def test_spacy_n_process_default_is_one(mocker, monkeypatch, tmp_path):
    """Test that SPACY_N_PROCESS defaults to 1 (single process)."""
    # Clear any existing env var
    monkeypatch.delenv("SPACY_N_PROCESS", raising=False)

    # Mock get_nlp to avoid spaCy dependency
    mock_nlp = mocker.MagicMock()
    # Make pipe return a mock doc for each text passed in
    mock_doc = mocker.MagicMock()
    mock_nlp.pipe.return_value = iter([mock_doc])
    mocker.patch("clerk.utils.get_nlp", return_value=mock_nlp)
    mocker.patch("clerk.utils.EXTRACTION_ENABLED", True)

    # Mock extraction functions to avoid dependencies
    mocker.patch(
        "clerk.utils.extract_entities", return_value={"persons": [], "orgs": [], "locations": []}
    )
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
    (date_dir / "0001.txt").write_text("test content")

    # Enable extraction to trigger spaCy processing
    build_table_from_text(
        subdomain="test", txt_dir=str(txt_dir), db=db, table_name="minutes", extract_entities=True
    )

    # Check that nlp.pipe was NOT called with n_process (default is 1, so no n_process kwarg)
    call_kwargs = mock_nlp.pipe.call_args[1]
    assert call_kwargs.get("n_process") is None, "Default of 1 means no n_process kwarg"


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


def test_load_extraction_cache_valid(tmp_path):
    """Test loading valid cache file with matching hash."""
    from clerk.utils import load_extraction_cache

    cache_file = tmp_path / "test.txt.extracted.json"
    expected_hash = "abc123"
    cache_data = {
        "content_hash": "abc123",
        "model_version": "en_core_web_md",
        "extracted_at": "2025-12-31T12:00:00Z",
        "entities": {"persons": ["John Doe"], "orgs": [], "locations": []},
        "votes": {"votes": []},
    }

    cache_file.write_text(json.dumps(cache_data))

    result = load_extraction_cache(str(cache_file), expected_hash)

    assert result is not None
    assert result["content_hash"] == "abc123"
    assert result["entities"]["persons"] == ["John Doe"]


def test_load_extraction_cache_hash_mismatch(tmp_path):
    """Test cache rejected when hash doesn't match."""
    from clerk.utils import load_extraction_cache

    cache_file = tmp_path / "test.txt.extracted.json"
    cache_data = {
        "content_hash": "abc123",
        "entities": {"persons": [], "orgs": [], "locations": []},
        "votes": {"votes": []},
    }

    cache_file.write_text(json.dumps(cache_data))

    result = load_extraction_cache(str(cache_file), "different_hash")

    assert result is None


def test_load_extraction_cache_missing_file():
    """Test cache returns None for missing file."""
    from clerk.utils import load_extraction_cache

    result = load_extraction_cache("/nonexistent/file.json", "abc123")

    assert result is None


def test_load_extraction_cache_corrupted_json(tmp_path):
    """Test cache returns None for corrupted JSON."""
    from clerk.utils import load_extraction_cache

    cache_file = tmp_path / "test.txt.extracted.json"
    cache_file.write_text("{ invalid json")

    result = load_extraction_cache(str(cache_file), "abc123")

    assert result is None


def test_save_extraction_cache(tmp_path):
    """Test saving extraction cache to file."""
    from clerk.utils import save_extraction_cache

    cache_file = tmp_path / "test.txt.extracted.json"
    cache_data = {
        "content_hash": "abc123",
        "model_version": "en_core_web_md",
        "extracted_at": "2025-12-31T12:00:00Z",
        "entities": {"persons": ["Jane Smith"], "orgs": ["City Council"], "locations": []},
        "votes": {"votes": [{"motion": "Test", "result": "passed"}]},
    }

    save_extraction_cache(str(cache_file), cache_data)

    assert cache_file.exists()

    with open(cache_file) as f:
        loaded = json.load(f)

    assert loaded["content_hash"] == "abc123"
    assert loaded["entities"]["persons"] == ["Jane Smith"]
    assert loaded["votes"]["votes"][0]["motion"] == "Test"


def test_build_table_from_text_is_fresh_processing(tmp_path, monkeypatch):
    """Test that build_table_from_text does fresh processing (doesn't use cache).

    Cache is only used during the extraction phase (extract_entities_for_site).
    Build phase is always fresh processing to populate the database.
    """
    import sqlite_utils

    from clerk.utils import build_table_from_text, hash_text_content, save_extraction_cache

    # Set up test directory structure
    subdomain = "test.civic.band"
    txt_dir = tmp_path / "txt"
    meeting_dir = txt_dir / "city-council"
    date_dir = meeting_dir / "2024-01-15"
    date_dir.mkdir(parents=True)

    # Create test text file
    text_file = date_dir / "001.txt"
    text_content = "Test meeting minutes"
    text_file.write_text(text_content)

    # Create cache file - build should ignore this
    cache_file = str(text_file) + ".extracted.json"
    content_hash = hash_text_content(text_content)
    cache_data = {
        "content_hash": content_hash,
        "model_version": "en_core_web_md",
        "extracted_at": "2025-12-31T12:00:00Z",
        "entities": {
            "persons": [{"text": "Cached Person", "confidence": 0.85}],
            "orgs": [],
            "locations": [],
        },
        "votes": {"votes": []},
    }
    save_extraction_cache(cache_file, cache_data)

    # Create database
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

    # Disable extraction
    import clerk.extraction

    monkeypatch.setattr(clerk.extraction, "EXTRACTION_ENABLED", False)

    # Run build - should NOT use cache, just populate database with empty entities
    build_table_from_text(subdomain, str(txt_dir), db, "minutes")

    # Verify database populated (but cache was ignored during build)
    rows = list(db["minutes"].rows)
    assert len(rows) == 1

    # Build doesn't use cache - entities should be empty
    entities = json.loads(rows[0]["entities_json"])
    assert len(entities["persons"]) == 0, "Build phase doesn't use cache"
