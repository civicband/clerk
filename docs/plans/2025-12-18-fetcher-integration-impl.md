# Fetcher Base Class Integration - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate `fetcher.py` as the base class for all fetchers, fixing imports, adding dependencies, and updating tests.

**Architecture:** Move shared transform functions to `utils.py` to break circular imports. Add HTTP/HTML deps as core, PDF deps as optional. Guard PDF imports at runtime. Update `MockFetcher` to inherit from `Fetcher`.

**Tech Stack:** Python 3.12, httpx, beautifulsoup4, sqlite-utils, pluggy, pytest

---

### Task 1: Add Core Dependencies

**Files:**
- Modify: `pyproject.toml:8-13`

**Step 1: Add httpx and beautifulsoup4 to dependencies**

Edit `pyproject.toml` dependencies list:

```toml
dependencies = [
    "click>=8.1.8",
    "logfire[sqlite3]>=2.0.0",
    "pluggy>=1.5.0",
    "sqlite-utils>=3.38",
    "httpx>=0.27.0",
    "beautifulsoup4>=4.12.0",
]
```

**Step 2: Run install to verify**

Run: `uv pip install -e .`
Expected: Successful install with new deps

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add httpx and beautifulsoup4 as core dependencies"
```

---

### Task 2: Add Optional PDF Dependencies

**Files:**
- Modify: `pyproject.toml:15-25`

**Step 1: Add pdf optional dependency group**

Edit `pyproject.toml` optional-dependencies section:

```toml
[project.optional-dependencies]
pdf = [
    "weasyprint>=60.0",
    "pdfkit>=1.0.0",
    "pdf2image>=1.16.0",
    "pypdf>=4.0.0",
]
dev = [
    "pytest>=7.4.0",
    "pytest-cov>=4.1.0",
    "pytest-mock>=3.12.0",
    "pytest-click>=1.1.0",
    "ruff>=0.1.0",
    "mypy>=1.7.0",
    "pre-commit>=3.5.0",
    "faker>=20.0.0",
]
```

**Step 2: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add optional pdf dependency group"
```

---

### Task 3: Move Transform Functions to utils.py

**Files:**
- Modify: `src/clerk/utils.py`
- Modify: `src/clerk/cli.py`

**Step 1: Add imports to utils.py**

Add these imports at the top of `src/clerk/utils.py`:

```python
import json
import os
import shutil
import time
from hashlib import sha256

import click
import logfire
import pluggy
import sqlite_utils

from .hookspecs import ClerkSpec
```

**Step 2: Add build_table_from_text to utils.py**

Add this function to `src/clerk/utils.py` after `assert_db_exists`:

```python
@logfire.instrument("build_table_from_text", extract_args=True)
def build_table_from_text(subdomain, txt_dir, db, table_name, municipality=None):
    logfire.info(
        "Building table from text",
        subdomain=subdomain,
        table_name=table_name,
        municipality=municipality,
    )
    directories = [
        directory for directory in sorted(os.listdir(txt_dir)) if directory != ".DS_Store"
    ]
    for meeting in directories:
        click.echo(click.style(subdomain, fg="cyan") + ": " + f"Processing {meeting}")
        meeting_dates = [
            meeting_date
            for meeting_date in sorted(os.listdir(f"{txt_dir}/{meeting}"))
            if meeting_date != ".DS_Store"
        ]
        entries = []
        for meeting_date in meeting_dates:
            for page in os.listdir(f"{txt_dir}/{meeting}/{meeting_date}"):
                if not page.endswith(".txt"):
                    continue
                key_hash = {"kind": "minutes"}
                page_file_path = f"{txt_dir}/{meeting}/{meeting_date}/{page}"
                with open(page_file_path) as page_file:
                    page_image_path = f"/{meeting}/{meeting_date}/{page.split('.')[0]}.png"
                    if table_name == "agendas":
                        key_hash["kind"] = "agenda"
                        page_image_path = (
                            f"/_agendas/{meeting}/{meeting_date}/{page.split('.')[0]}.png"
                        )
                    text = page_file.read()
                    page_number = int(page.split(".")[0])
                    key_hash.update(
                        {
                            "meeting": meeting,
                            "date": meeting_date,
                            "page": page_number,
                            "text": text,
                        }
                    )
                    if municipality:
                        key_hash.update({"subdomain": subdomain, "municipality": municipality})
                    key = sha256(json.dumps(key_hash, sort_keys=True).encode("utf-8")).hexdigest()
                    key = key[:12]
                    key_hash.update(
                        {
                            "id": key,
                            "text": text,
                            "page_image": page_image_path,
                        }
                    )
                    del key_hash["kind"]
                    entries.append(key_hash)
        db[table_name].insert_all(entries)
```

**Step 3: Add build_db_from_text_internal to utils.py**

Add this function to `src/clerk/utils.py` after `build_table_from_text`:

```python
@logfire.instrument("build_db_from_text", extract_args=True)
def build_db_from_text_internal(subdomain):
    st = time.time()
    logfire.info("Building database from text", subdomain=subdomain)
    minutes_txt_dir = f"{STORAGE_DIR}/{subdomain}/txt"
    agendas_txt_dir = f"{STORAGE_DIR}/{subdomain}/_agendas/txt"
    database = f"{STORAGE_DIR}/{subdomain}/meetings.db"
    db_backup = f"{STORAGE_DIR}/{subdomain}/meetings.db.bk"
    shutil.copy(database, db_backup)
    os.remove(database)
    db = sqlite_utils.Database(database)
    db["minutes"].create(
        {
            "id": str,
            "meeting": str,
            "date": str,
            "page": int,
            "text": str,
            "page_image": str,
        },
        pk=("id"),
    )
    db["agendas"].create(
        {
            "id": str,
            "meeting": str,
            "date": str,
            "page": int,
            "text": str,
            "page_image": str,
        },
        pk=("id"),
    )
    if os.path.exists(minutes_txt_dir):
        build_table_from_text(subdomain, minutes_txt_dir, db, "minutes")
    if os.path.exists(agendas_txt_dir):
        build_table_from_text(subdomain, agendas_txt_dir, db, "agendas")
    et = time.time()
    elapsed_time = et - st
    logfire.info("Database build completed", subdomain=subdomain, elapsed_time=elapsed_time)
    click.echo(f"Execution time: {elapsed_time} seconds")
```

**Step 4: Update cli.py to import from utils**

In `src/clerk/cli.py`, update the imports to:

```python
from .utils import assert_db_exists, pm, build_db_from_text_internal, build_table_from_text
```

Remove the `build_db_from_text_internal` and `build_table_from_text` function definitions from `cli.py` (keep only the CLI command wrapper `build_db_from_text` that calls `build_db_from_text_internal`).

**Step 5: Run tests to verify nothing broke**

Run: `uv run pytest tests/ -v --tb=short`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/clerk/utils.py src/clerk/cli.py
git commit -m "refactor: move transform functions from cli to utils"
```

---

### Task 4: Clean Up fetcher.py - Remove Dead Code

**Files:**
- Modify: `src/clerk/fetcher.py`

**Step 1: Remove debug print on line 55**

Delete this line:
```python
        self.message_print(f"{self.previous_page_count}")
```

**Step 2: Remove commented breakpoint on line 274**

Delete:
```python
        # breakpoint()
```

**Step 3: Remove commented breakpoint on line 303**

Delete:
```python
        # breakpoint()
```

**Step 4: Remove commented code block lines 242-244**

Delete:
```python
                # if match := self.fetch_doc(link, date):
                #     pass # Process the PDF file
                #     # add link doc for first page?
```

**Step 5: Remove commented code block lines 284-310**

Delete the large commented block starting with `# for html_path in sorted(glob.glob...` through `#     soup = BeautifulSoup(html_file, "html.parser")` etc.

**Step 6: Commit**

```bash
git add src/clerk/fetcher.py
git commit -m "cleanup: remove dead code and debug statements from fetcher"
```

---

### Task 5: Fix fetcher.py Imports

**Files:**
- Modify: `src/clerk/fetcher.py`

**Step 1: Update imports at top of file**

Replace the current imports with:

```python
import concurrent.futures
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime
from hashlib import sha256
from typing import Any
from xml.etree.ElementTree import ParseError

from bs4 import BeautifulSoup
import click
import httpx
import sqlite_utils

from clerk.utils import STORAGE_DIR, pm, build_db_from_text_internal

# Optional PDF dependencies
try:
    import pdfkit
    from pdf2image import convert_from_path
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    from weasyprint import HTML
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    PdfReader = None
    PdfReadError = Exception
    HTML = None
    pdfkit = None
    convert_from_path = None

NUM_WORKERS = int(os.environ.get("NUM_WORKERS", 10))
```

**Step 2: Commit**

```bash
git add src/clerk/fetcher.py
git commit -m "fix: update fetcher imports to use utils and guard PDF deps"
```

---

### Task 6: Add Type Hints to Fetcher Public Methods

**Files:**
- Modify: `src/clerk/fetcher.py`

**Step 1: Add type hint to __init__**

```python
    def __init__(self, site: dict[str, Any], start_year: int | None = None, all_agendas: bool = False) -> None:
```

**Step 2: Add type hint to child_init**

```python
    def child_init(self) -> None:
```

**Step 3: Add type hint to assert methods**

```python
    def assert_fetch_dirs(self) -> None:
    def assert_processed_dirs(self) -> None:
    def assert_site_db_exists(self) -> None:
```

**Step 4: Add type hint to request**

```python
    def request(
        self,
        method: str,
        url: str,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
    ) -> httpx.Response | None:
```

**Step 5: Add type hint to message_print**

```python
    def message_print(self, message: str) -> None:
```

**Step 6: Add type hint to check_if_exists**

```python
    def check_if_exists(self, meeting: str, date: str, kind: str) -> bool:
```

**Step 7: Add type hint to simplified_meeting_name**

```python
    def simplified_meeting_name(self, body: str) -> str:
```

**Step 8: Add type hint to fetch_and_write_pdf**

```python
    def fetch_and_write_pdf(
        self,
        url: str,
        kind: str,
        meeting: str,
        date: str,
        headers: dict[str, str] | None = None,
    ) -> None:
```

**Step 9: Add type hints to remaining public methods**

```python
    def fetch_docs_from_page(self, page_number: int, meeting: str, date: str, prefix: str) -> str | None:
    def make_html_from_pdf(self, date: str, doc_path: str) -> None:
    def ocr(self) -> None:
    def transform(self) -> None:
    def do_ocr(self, prefix: str = "") -> None:
    def do_ocr_job(self, job: tuple[str, str, str]) -> None:
```

**Step 10: Add fetch_events as abstract method**

```python
    def fetch_events(self) -> None:
        """Subclasses must override this to fetch meeting data."""
        raise NotImplementedError("Subclasses must implement fetch_events()")
```

**Step 11: Commit**

```bash
git add src/clerk/fetcher.py
git commit -m "feat: add type hints to fetcher public methods"
```

---

### Task 7: Add PDF Support Guard

**Files:**
- Modify: `src/clerk/fetcher.py`

**Step 1: Add guard to fetch_and_write_pdf**

Add at the start of `fetch_and_write_pdf` method:

```python
        if not PDF_SUPPORT:
            raise ImportError(
                "PDF support requires optional dependencies. "
                "Install with: pip install clerk[pdf]"
            )
```

**Step 2: Add guard to do_ocr_job**

Add at the start of `do_ocr_job` method:

```python
        if not PDF_SUPPORT:
            raise ImportError(
                "PDF support requires optional dependencies. "
                "Install with: pip install clerk[pdf]"
            )
```

**Step 3: Commit**

```bash
git add src/clerk/fetcher.py
git commit -m "feat: add PDF dependency guards with helpful error messages"
```

---

### Task 8: Export Fetcher from __init__.py

**Files:**
- Modify: `src/clerk/__init__.py`

**Step 1: Add Fetcher import and export**

Update `src/clerk/__init__.py`:

```python
import logfire

from .fetcher import Fetcher

logfire.configure()
logfire.instrument_sqlite3()

__all__ = ["Fetcher"]
```

**Step 2: Verify import works**

Run: `uv run python -c "from clerk import Fetcher; print(Fetcher)"`
Expected: `<class 'clerk.fetcher.Fetcher'>`

**Step 3: Commit**

```bash
git add src/clerk/__init__.py
git commit -m "feat: export Fetcher from clerk package"
```

---

### Task 9: Write Fetcher Unit Tests

**Files:**
- Create: `tests/test_fetcher.py`

**Step 1: Create test file with imports**

```python
"""Tests for the Fetcher base class."""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestFetcherImport:
    """Test that Fetcher can be imported."""

    def test_import_fetcher_from_package(self):
        """Fetcher should be importable from clerk package."""
        from clerk import Fetcher
        assert Fetcher is not None

    def test_import_fetcher_from_module(self):
        """Fetcher should be importable from fetcher module."""
        from clerk.fetcher import Fetcher
        assert Fetcher is not None


class TestFetcherPDFGuard:
    """Test PDF dependency guards."""

    def test_pdf_support_flag_exists(self):
        """PDF_SUPPORT flag should exist."""
        from clerk.fetcher import PDF_SUPPORT
        assert isinstance(PDF_SUPPORT, bool)


class TestFetcherContract:
    """Test the Fetcher base class contract."""

    def test_fetch_events_raises_not_implemented(self, tmp_path, monkeypatch):
        """Base Fetcher.fetch_events() should raise NotImplementedError."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        from clerk.fetcher import Fetcher

        # Create required directories
        site_dir = tmp_path / "test-site"
        site_dir.mkdir()
        for subdir in ["_docs/pdfs", "_docs/processed", "_docs/html"]:
            (site_dir / subdir).mkdir(parents=True)

        site = {
            "subdomain": "test-site",
            "start_year": 2020,
            "pages": 0,
        }

        fetcher = Fetcher(site)

        with pytest.raises(NotImplementedError, match="Subclasses must implement"):
            fetcher.fetch_events()


class TestFetcherCheckIfExists:
    """Test the check_if_exists method."""

    def test_returns_false_when_no_files_exist(self, tmp_path, monkeypatch):
        """check_if_exists returns False when no matching files exist."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        from clerk.fetcher import Fetcher

        # Create required directories
        site_dir = tmp_path / "test-site"
        site_dir.mkdir()
        for subdir in ["_docs/pdfs", "_docs/processed", "_docs/html", "pdfs", "processed"]:
            (site_dir / subdir).mkdir(parents=True)

        site = {
            "subdomain": "test-site",
            "start_year": 2020,
            "pages": 0,
        }

        fetcher = Fetcher(site)

        result = fetcher.check_if_exists("CityCouncil", "2024-01-15", "minutes")
        assert result is False

    def test_returns_true_when_pdf_exists(self, tmp_path, monkeypatch):
        """check_if_exists returns True when PDF exists in output dir."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        from clerk.fetcher import Fetcher

        # Create required directories
        site_dir = tmp_path / "test-site"
        site_dir.mkdir()
        for subdir in ["_docs/pdfs", "_docs/processed", "_docs/html", "pdfs/CityCouncil", "processed"]:
            (site_dir / subdir).mkdir(parents=True)

        # Create the PDF file
        (site_dir / "pdfs" / "CityCouncil" / "2024-01-15.pdf").write_bytes(b"fake pdf")

        site = {
            "subdomain": "test-site",
            "start_year": 2020,
            "pages": 0,
        }

        fetcher = Fetcher(site)

        result = fetcher.check_if_exists("CityCouncil", "2024-01-15", "minutes")
        assert result is True


class TestFetcherSimplifiedMeetingName:
    """Test the simplified_meeting_name method."""

    def test_removes_spaces(self, tmp_path, monkeypatch):
        """simplified_meeting_name removes spaces."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        from clerk.fetcher import Fetcher

        # Create required directories
        site_dir = tmp_path / "test-site"
        site_dir.mkdir()
        for subdir in ["_docs/pdfs", "_docs/processed", "_docs/html"]:
            (site_dir / subdir).mkdir(parents=True)

        site = {
            "subdomain": "test-site",
            "start_year": 2020,
            "pages": 0,
        }

        fetcher = Fetcher(site)

        result = fetcher.simplified_meeting_name("City Council")
        assert result == "CityCouncil"

    def test_replaces_special_chars(self, tmp_path, monkeypatch):
        """simplified_meeting_name replaces special characters."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        from clerk.fetcher import Fetcher

        # Create required directories
        site_dir = tmp_path / "test-site"
        site_dir.mkdir()
        for subdir in ["_docs/pdfs", "_docs/processed", "_docs/html"]:
            (site_dir / subdir).mkdir(parents=True)

        site = {
            "subdomain": "test-site",
            "start_year": 2020,
            "pages": 0,
        }

        fetcher = Fetcher(site)

        result = fetcher.simplified_meeting_name("Parks & Recreation")
        assert result == "ParksAndRecreation"
```

**Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_fetcher.py -v`
Expected: All tests pass

**Step 3: Commit**

```bash
git add tests/test_fetcher.py
git commit -m "test: add unit tests for Fetcher base class"
```

---

### Task 10: Update MockFetcher to Inherit from Fetcher

**Files:**
- Modify: `tests/mocks/mock_fetchers.py`

**Step 1: Update MockFetcher class**

Replace the entire `tests/mocks/mock_fetchers.py` with:

```python
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

    def ocr(self) -> None:
        """Simulate OCR processing."""
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

    def ocr(self) -> None:
        """Raise an error during OCR."""
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

    def ocr(self) -> None:
        """Simulate slow OCR."""
        time.sleep(self.delay)
        super().ocr()

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
```

**Step 2: Run all tests to verify nothing broke**

Run: `uv run pytest tests/ -v --tb=short`
Expected: All tests pass

**Step 3: Commit**

```bash
git add tests/mocks/mock_fetchers.py
git commit -m "refactor: MockFetcher now inherits from Fetcher base class"
```

---

### Task 11: Add Test for MockFetcher Inheritance

**Files:**
- Modify: `tests/test_fetcher.py`

**Step 1: Add inheritance test**

Add this test class to `tests/test_fetcher.py`:

```python
class TestMockFetcherInheritance:
    """Test that MockFetcher properly inherits from Fetcher."""

    def test_mock_fetcher_is_subclass(self):
        """MockFetcher should be a subclass of Fetcher."""
        from clerk.fetcher import Fetcher
        from tests.mocks.mock_fetchers import MockFetcher

        assert issubclass(MockFetcher, Fetcher)

    def test_mock_fetcher_instance(self):
        """MockFetcher instance should be instance of Fetcher."""
        from clerk.fetcher import Fetcher
        from tests.mocks.mock_fetchers import MockFetcher

        site = {"subdomain": "test", "start_year": 2020, "pages": 0}
        mock = MockFetcher(site, 2020)

        assert isinstance(mock, Fetcher)
        assert isinstance(mock, MockFetcher)
```

**Step 2: Run tests**

Run: `uv run pytest tests/test_fetcher.py -v`
Expected: All tests pass

**Step 3: Commit**

```bash
git add tests/test_fetcher.py
git commit -m "test: add MockFetcher inheritance verification tests"
```

---

### Task 12: Run Full Test Suite and Lint

**Files:** None (verification only)

**Step 1: Run full test suite**

Run: `uv run pytest tests/ -v --tb=short`
Expected: All tests pass

**Step 2: Run linter**

Run: `uv run ruff check src/ tests/`
Expected: No errors (or fix any that appear)

**Step 3: Run formatter check**

Run: `uv run ruff format --check src/ tests/`
Expected: No formatting issues (or run `uv run ruff format src/ tests/` to fix)

**Step 4: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: address linting and formatting issues"
```

---

### Task 13: Track fetcher.py in Git

**Files:**
- `src/clerk/fetcher.py`

**Step 1: Add fetcher.py to git**

```bash
git add src/clerk/fetcher.py
git commit -m "feat: add Fetcher base class for all site fetchers

Fetcher provides:
- HTTP request handling with retry logic
- PDF fetching and validation
- OCR processing with concurrent workers
- Directory and database setup helpers

Subclasses implement fetch_events() for site-specific scraping."
```

---

## Summary

After completing all tasks:
- `fetcher.py` is cleaned up with type hints and no dead code
- Circular imports are resolved (transform functions in utils.py)
- Dependencies are properly split (core vs optional PDF)
- `MockFetcher` inherits from `Fetcher`
- Comprehensive tests verify the base class contract
- `Fetcher` is exported from the `clerk` package
