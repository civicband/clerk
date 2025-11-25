"""Pytest configuration and shared fixtures for clerk tests."""

import datetime
import json

import pluggy
import pytest
import sqlite_utils

from clerk.hookspecs import ClerkSpec
from tests.mocks.mock_fetchers import MockFetcher
from tests.mocks.mock_plugins import TestPlugin


@pytest.fixture
def tmp_storage_dir(tmp_path):
    """Create a temporary storage directory structure for testing.

    Creates a directory structure that mimics the STORAGE_DIR layout:
    - tmp_path/sites/{subdomain}/txt/
    - tmp_path/sites/{subdomain}/_agendas/txt/
    - tmp_path/sites/{subdomain}/meetings.db
    """
    storage_dir = tmp_path / "sites"
    storage_dir.mkdir()
    return storage_dir


@pytest.fixture
def sample_db(tmp_path):
    """Create a sample civic.db database with test data."""
    db_path = tmp_path / "civic.db"
    db = sqlite_utils.Database(db_path)

    # Create sites table
    db["sites"].insert_all(
        [
            {
                "subdomain": "example.civic.band",
                "name": "Example City Council",
                "state": "CA",
                "country": "US",
                "kind": "city-council",
                "scraper": "test_scraper",
                "pages": 10,
                "start_year": 2020,
                "extra": json.dumps({"key": "value"}),
                "status": "deployed",
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "lat": "37.7749",
                "lng": "-122.4194",
            },
            {
                "subdomain": "test.civic.band",
                "name": "Test City Planning Commission",
                "state": "NY",
                "country": "US",
                "kind": "planning-commission",
                "scraper": "custom",
                "pages": 5,
                "start_year": 2021,
                "extra": None,
                "status": "new",
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "lat": "40.7128",
                "lng": "-74.0060",
            },
            {
                "subdomain": "pending.civic.band",
                "name": "Pending Town Council",
                "state": "TX",
                "country": "US",
                "kind": "city-council",
                "scraper": "test_scraper",
                "pages": 0,
                "start_year": 2022,
                "extra": None,
                "status": "needs_ocr",
                "last_updated": "2023-01-01T00:00:00",
                "lat": "30.2672",
                "lng": "-97.7431",
            },
        ],
        pk="subdomain",
    )

    # Create feed_entries table
    db["feed_entries"].insert_all(
        [
            {
                "subdomain": "example.civic.band",
                "date": "2024-01-15",
                "kind": "minutes",
                "name": "City Council Regular Meeting",
            },
            {
                "subdomain": "example.civic.band",
                "date": "2024-02-01",
                "kind": "agenda",
                "name": "City Council Special Meeting",
            },
        ]
    )

    return db


@pytest.fixture
def sample_site_data():
    """Return sample site data as a dictionary."""
    return {
        "subdomain": "example.civic.band",
        "name": "Example City Council",
        "state": "CA",
        "country": "US",
        "kind": "city-council",
        "scraper": "test_scraper",
        "pages": 10,
        "start_year": 2020,
        "extra": json.dumps({"key": "value"}),
        "status": "deployed",
        "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "lat": "37.7749",
        "lng": "-122.4194",
    }


@pytest.fixture
def sample_site_db(tmp_storage_dir):
    """Create a sample per-site meetings.db with minutes and agendas."""
    subdomain = "example.civic.band"
    site_dir = tmp_storage_dir / subdomain
    site_dir.mkdir()

    db_path = site_dir / "meetings.db"
    db = sqlite_utils.Database(db_path)

    # Create minutes table
    db["minutes"].insert_all(
        [
            {
                "id": "abc123",
                "meeting": "City Council",
                "date": "2024-01-15",
                "page": 1,
                "text": "The meeting was called to order at 7:00 PM.",
                "page_image": "/City Council/2024-01-15/1.png",
            },
            {
                "id": "abc124",
                "meeting": "City Council",
                "date": "2024-01-15",
                "page": 2,
                "text": "Roll call was taken. All members were present.",
                "page_image": "/City Council/2024-01-15/2.png",
            },
        ],
        pk="id",
    )

    # Create agendas table
    db["agendas"].insert_all(
        [
            {
                "id": "def456",
                "meeting": "City Council",
                "date": "2024-02-01",
                "page": 1,
                "text": "1. Call to Order\n2. Roll Call\n3. Public Comment",
                "page_image": "/_agendas/City Council/2024-02-01/1.png",
            },
        ],
        pk="id",
    )

    # Enable FTS on both tables
    db["minutes"].enable_fts(["text"])
    db["agendas"].enable_fts(["text"])

    return db


@pytest.fixture
def sample_text_files(tmp_storage_dir):
    """Create sample text files mimicking OCR output."""
    subdomain = "example.civic.band"

    # Create minutes text files
    minutes_dir = tmp_storage_dir / subdomain / "txt" / "City Council" / "2024-01-15"
    minutes_dir.mkdir(parents=True)

    (minutes_dir / "1.txt").write_text("The meeting was called to order at 7:00 PM.")
    (minutes_dir / "2.txt").write_text("Roll call was taken. All members were present.")

    # Create agenda text files
    agendas_dir = tmp_storage_dir / subdomain / "_agendas" / "txt" / "City Council" / "2024-02-01"
    agendas_dir.mkdir(parents=True)

    (agendas_dir / "1.txt").write_text("1. Call to Order\n2. Roll Call\n3. Public Comment")

    return {
        "minutes_dir": tmp_storage_dir / subdomain / "txt",
        "agendas_dir": tmp_storage_dir / subdomain / "_agendas" / "txt",
    }


@pytest.fixture
def mock_fetcher(sample_site_data):
    """Create a mock fetcher instance."""
    return MockFetcher(sample_site_data, start_year=2020, all_agendas=False)


@pytest.fixture
def mock_plugin_manager():
    """Create a plugin manager with test plugins registered."""
    pm = pluggy.PluginManager("civicband.clerk")
    pm.add_hookspecs(ClerkSpec)
    pm.register(TestPlugin())
    return pm


@pytest.fixture
def monkeypatch_storage_dir(tmp_storage_dir, monkeypatch):
    """Monkeypatch the STORAGE_DIR environment variable."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
    return tmp_storage_dir


@pytest.fixture(autouse=True)
def disable_logfire(monkeypatch):
    """Disable logfire for tests to avoid authentication requirements."""
    import logfire

    monkeypatch.setattr(logfire, "configure", lambda *args, **kwargs: None)
    monkeypatch.setattr(logfire, "instrument_sqlite3", lambda *args, **kwargs: None)
    monkeypatch.setattr(logfire, "instrument", lambda *args, **kwargs: lambda f: f)
    monkeypatch.setattr(logfire, "info", lambda *args, **kwargs: None)
