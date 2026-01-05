"""Mock fetcher classes for testing."""

import os
import time
from pathlib import Path
from typing import Any

import sqlite_utils

from clerk.fetcher import Fetcher


class MockFetcher(Fetcher):
    """Mock fetcher that simulates the fetcher interface without external dependencies."""

    def __init__(self, site: dict[str, Any], start_year: int, all_agendas: bool = False):
        """Initialize the mock fetcher, skipping parent's filesystem setup.

        Args:
            site: Site configuration dictionary
            start_year: Year to start fetching from
            all_agendas: Whether to fetch all agendas
        """
        # Set attributes directly instead of calling parent __init__
        # to avoid filesystem and database setup
        self.site = site
        self.subdomain = site["subdomain"]
        self.start_year = start_year
        self.all_agendas = all_agendas

        # Test tracking attributes
        self.events_fetched: list[dict[str, Any]] = []
        self.ocr_complete = False
        self.transform_complete = False

    def fetch_events(self) -> None:
        """Simulate fetching events."""
        time.sleep(0.01)
        self.events_fetched = [
            {
                "meeting": "City Council",
                "date": "2024-01-15",
                "type": "minutes",
            },
            {
                "meeting": "City Council",
                "date": "2024-02-01",
                "type": "agenda",
            },
        ]

    def ocr(self, backend: str = "tesseract") -> None:
        """Simulate OCR processing.

        Args:
            backend: OCR backend to use ('tesseract' or 'vision')
        """
        time.sleep(0.01)
        self.ocr_complete = True

    def transform(self) -> None:
        """Simulate transform processing and create meetings.db."""
        time.sleep(0.01)
        self.transform_complete = True

        # Create a minimal meetings.db for update_page_count to work
        storage_dir = os.environ.get("STORAGE_DIR", "../sites")
        subdomain = self.site["subdomain"]
        site_dir = Path(storage_dir) / subdomain
        site_dir.mkdir(parents=True, exist_ok=True)

        db_path = site_dir / "meetings.db"
        db = sqlite_utils.Database(db_path)
        db["minutes"].create(
            {"id": str, "meeting": str, "date": str, "page": int, "text": str, "page_image": str},
            pk="id",
            if_not_exists=True,
        )
        db["agendas"].create(
            {"id": str, "meeting": str, "date": str, "page": int, "text": str, "page_image": str},
            pk="id",
            if_not_exists=True,
        )


class FailingFetcher(MockFetcher):
    """Mock fetcher that raises errors for testing error handling."""

    def fetch_events(self) -> None:
        """Raise an error when fetching events."""
        raise RuntimeError("Failed to fetch events")

    def ocr(self, backend: str = "tesseract") -> None:
        """Raise an error during OCR.

        Args:
            backend: OCR backend to use ('tesseract' or 'vision')
        """
        raise RuntimeError("OCR processing failed")

    def transform(self) -> None:
        """Raise an error during transform."""
        raise RuntimeError("Transform failed")


class SlowFetcher(MockFetcher):
    """Mock fetcher that simulates slow operations for performance testing."""

    def __init__(
        self, site: dict[str, Any], start_year: int, all_agendas: bool = False, delay: float = 0.5
    ):
        """Initialize the slow fetcher.

        Args:
            site: Site configuration dictionary
            start_year: Year to start fetching from
            all_agendas: Whether to fetch all agendas
            delay: Delay in seconds for each operation
        """
        super().__init__(site, start_year, all_agendas)
        self.delay = delay

    def fetch_events(self) -> None:
        """Simulate slow event fetching."""
        time.sleep(self.delay)
        super().fetch_events()

    def ocr(self, backend: str = "tesseract") -> None:
        """Simulate slow OCR.

        Args:
            backend: OCR backend to use ('tesseract' or 'vision')
        """
        time.sleep(self.delay)
        super().ocr(backend=backend)

    def transform(self) -> None:
        """Simulate slow transform."""
        time.sleep(self.delay)
        super().transform()


class FilesystemFetcher(MockFetcher):
    """Mock fetcher that actually creates files for integration testing."""

    def __init__(
        self,
        site: dict[str, Any],
        start_year: int,
        all_agendas: bool = False,
        storage_dir: Path | None = None,
    ):
        """Initialize the filesystem fetcher.

        Args:
            site: Site configuration dictionary
            start_year: Year to start fetching from
            all_agendas: Whether to fetch all agendas
            storage_dir: Path to storage directory
        """
        super().__init__(site, start_year, all_agendas)
        self.storage_dir = storage_dir or Path("../sites")

    def fetch_events(self) -> None:
        """Create actual text files as if they were fetched."""
        super().fetch_events()

        subdomain = self.site["subdomain"]

        # Create minutes files
        minutes_dir = self.storage_dir / subdomain / "txt" / "City Council" / "2024-01-15"
        minutes_dir.mkdir(parents=True, exist_ok=True)

        (minutes_dir / "1.txt").write_text("The meeting was called to order at 7:00 PM.")
        (minutes_dir / "2.txt").write_text("Roll call was taken. All members were present.")

        # Create agenda files if requested
        if self.all_agendas:
            agendas_dir = (
                self.storage_dir / subdomain / "_agendas" / "txt" / "City Council" / "2024-02-01"
            )
            agendas_dir.mkdir(parents=True, exist_ok=True)

            (agendas_dir / "1.txt").write_text("1. Call to Order\n2. Roll Call\n3. Public Comment")
