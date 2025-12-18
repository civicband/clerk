# Fetcher Base Class Integration Design

## Overview

Integrate `fetcher.py` as the base class for all fetchers in the clerk codebase. This involves fixing import issues, adding dependencies, cleaning up the code, and updating tests.

## Goals

- Make `Fetcher` the base class other fetchers inherit from
- Fix circular import issues
- Add missing dependencies with sensible grouping
- Clean up intern code (dead code, types on public API)
- Update tests to exercise the real base class

## Dependency Structure

### Core dependencies (add to `pyproject.toml`)

```toml
dependencies = [
    # existing...
    "httpx>=0.27.0",
    "beautifulsoup4>=4.12.0",
]
```

### Optional PDF dependencies

```toml
[project.optional-dependencies]
pdf = [
    "weasyprint>=60.0",
    "pdfkit>=1.0.0",
    "pdf2image>=1.16.0",
    "pypdf>=4.0.0",
]
```

Install with: `pip install clerk[pdf]`

### External binaries (not managed by pip)

- `tesseract` - OCR engine
- `pdftohtml` - PDF to HTML conversion (poppler-utils)

## Import & Module Changes

### Fix circular imports

1. Move `build_db_from_text_internal()` and `build_table_from_text()` from `cli.py` to `utils.py`
2. Update `cli.py` to import these from `utils`
3. Update `fetcher.py` to import from `utils` instead of `cli`

### Fix fetcher.py imports

Change:
```python
from clerk import pm
from clerk.cli import build_db_from_text_internal
```

To:
```python
from clerk.utils import pm, STORAGE_DIR, build_db_from_text_internal
```

### Guard PDF imports

```python
try:
    from weasyprint import HTML
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    from pdf2image import convert_from_path
    import pdfkit
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
```

Methods using PDF libs check `PDF_SUPPORT` and raise `ImportError` with helpful message if missing.

## Code Cleanup

### Remove dead code

- Delete `# breakpoint()` comments
- Delete commented-out code blocks (lines 242-244, 284-310)
- Remove debug print: `self.message_print(f"{self.previous_page_count}")`

### Add type hints to public methods

```python
def __init__(self, site: dict[str, Any], start_year: int | None = None, all_agendas: bool = False) -> None:
def child_init(self) -> None:
def fetch_events(self) -> None:
def ocr(self) -> None:
def transform(self) -> None:
def request(self, method: str, url: str, json: dict | None = None, data: dict | None = None, headers: dict | None = None, cookies: dict | None = None) -> httpx.Response | None:
def check_if_exists(self, meeting: str, date: str, kind: str) -> bool:
def fetch_and_write_pdf(self, url: str, kind: str, meeting: str, date: str, headers: dict | None = None) -> None:
def simplified_meeting_name(self, body: str) -> str:
def do_ocr(self, prefix: str = "") -> None:
def do_ocr_job(self, job: tuple[str, str, str]) -> None:
```

## Fetcher Contract

### Base class provides

- `request()` - HTTP with retry logic (3 attempts)
- `fetch_and_write_pdf()` - download, convert HTML if needed, validate PDF
- `ocr()` / `do_ocr()` - tesseract processing with concurrent workers
- `transform()` - build SQLite DB from text files
- `check_if_exists()` - deduplication helper
- Directory setup helpers (`assert_fetch_dirs`, `assert_processed_dirs`, etc.)

### Subclasses must implement

- `fetch_events()` - site-specific scraping logic

### Subclasses may override

- `child_init()` - additional initialization after base setup

## Testing Strategy

### Update MockFetcher to inherit from Fetcher

```python
from clerk.fetcher import Fetcher

class MockFetcher(Fetcher):
    def __init__(self, site: dict[str, Any], start_year: int, all_agendas: bool = False):
        # Skip parent __init__ to avoid filesystem/db setup
        self.site = site
        self.start_year = start_year
        self.all_agendas = all_agendas
        self.subdomain = site["subdomain"]
        # Test tracking
        self.events_fetched = []
        self.ocr_complete = False
        self.transform_complete = False

    def fetch_events(self) -> None:
        """Override to avoid network calls."""
        ...

    def ocr(self) -> None:
        """Override to avoid tesseract/filesystem."""
        self.ocr_complete = True

    def transform(self) -> None:
        """Override to create minimal meetings.db."""
        ...
```

### New test file: `tests/test_fetcher.py`

- Test instantiation with mocked filesystem
- Test `request()` with mocked httpx
- Test `check_if_exists()` with temp directories
- Test PDF guard raises helpful error when deps missing

## Public API

### Export from `__init__.py`

```python
from .fetcher import Fetcher
```

### Usage by plugins

```python
from clerk import Fetcher

class MyCustomFetcher(Fetcher):
    def fetch_events(self) -> None:
        # Site-specific scraping logic
        ...
```

## Implementation Order

1. Add dependencies to `pyproject.toml`
2. Move `build_db_from_text_internal` and `build_table_from_text` to `utils.py`
3. Update `cli.py` imports
4. Clean up and fix `fetcher.py` (imports, types, dead code, PDF guards)
5. Export `Fetcher` from `__init__.py`
6. Update `MockFetcher` to inherit from `Fetcher`
7. Add `tests/test_fetcher.py`
8. Run tests and fix any issues
