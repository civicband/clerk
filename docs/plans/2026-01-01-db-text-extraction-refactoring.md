# DB Text Extraction Refactoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Decompose complex DB building and text extraction functions into readable, testable helpers.

**Architecture:** Extract helpers by concern (filesystem, database, cache, spaCy, extraction) while keeping high-level phases visible in main orchestration functions. Use dataclasses for clearer signatures.

**Tech Stack:** Python 3.12+, pytest, sqlite-utils, spaCy (optional), dataclasses

---

## Task 1: Add Data Classes

**Files:**
- Modify: `src/clerk/utils.py` (add at top after imports)
- Test: Run existing tests to ensure no breakage

**Step 1: Add dataclasses import**

Add to imports in `src/clerk/utils.py`:

```python
from dataclasses import dataclass
```

**Step 2: Add PageFile dataclass**

Add after imports, before functions:

```python
@dataclass
class PageFile:
    """Represents a single page file with its metadata."""
    meeting: str
    date: str
    page_num: int
    text: str
    page_image_path: str
```

**Step 3: Add MeetingDateGroup dataclass**

```python
@dataclass
class MeetingDateGroup:
    """Groups page indices by meeting and date."""
    meeting: str
    date: str
    page_indices: list[int]
```

**Step 4: Add PageData dataclass**

```python
@dataclass
class PageData:
    """Page data with cache information for extraction."""
    page_id: str
    text: str
    page_file_path: str
    content_hash: str | None
    cached_extraction: dict | None  # {"entities": ..., "votes": ...}
```

**Step 5: Run tests to verify no breakage**

Run: `uv run pytest tests/ -q`
Expected: All tests pass (dataclasses don't break anything)

**Step 6: Commit**

```bash
git add src/clerk/utils.py
git commit -m "refactor: add dataclasses for refactoring"
```

---

## Task 2: Extract Pure Helper - group_pages_by_meeting_date

**Files:**
- Create test: `tests/test_utils_refactor.py`
- Modify: `src/clerk/utils.py`

**Step 1: Write the failing test**

Create `tests/test_utils_refactor.py`:

```python
"""Tests for refactored utility functions."""
import pytest
from clerk.utils import PageFile, MeetingDateGroup, group_pages_by_meeting_date


def test_group_pages_by_meeting_date_single_meeting():
    """Test grouping pages from a single meeting date."""
    pages = [
        PageFile("council", "2024-01-15", 1, "text1", "/council/2024-01-15/0001.png"),
        PageFile("council", "2024-01-15", 2, "text2", "/council/2024-01-15/0002.png"),
    ]

    groups = group_pages_by_meeting_date(pages)

    assert len(groups) == 1
    assert groups[0].meeting == "council"
    assert groups[0].date == "2024-01-15"
    assert groups[0].page_indices == [0, 1]


def test_group_pages_by_meeting_date_multiple_dates():
    """Test grouping pages from multiple meeting dates."""
    pages = [
        PageFile("council", "2024-01-15", 1, "text1", "/path1.png"),
        PageFile("council", "2024-01-15", 2, "text2", "/path2.png"),
        PageFile("council", "2024-02-20", 1, "text3", "/path3.png"),
        PageFile("planning", "2024-01-15", 1, "text4", "/path4.png"),
    ]

    groups = group_pages_by_meeting_date(pages)

    assert len(groups) == 3
    assert groups[0].meeting == "council"
    assert groups[0].date == "2024-01-15"
    assert groups[0].page_indices == [0, 1]
    assert groups[1].meeting == "council"
    assert groups[1].date == "2024-02-20"
    assert groups[1].page_indices == [2]
    assert groups[2].meeting == "planning"
    assert groups[2].date == "2024-01-15"
    assert groups[2].page_indices == [3]


def test_group_pages_by_meeting_date_empty():
    """Test grouping with no pages."""
    groups = group_pages_by_meeting_date([])
    assert groups == []
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_utils_refactor.py::test_group_pages_by_meeting_date_single_meeting -v`
Expected: FAIL with "cannot import name 'group_pages_by_meeting_date'"

**Step 3: Write minimal implementation**

Add to `src/clerk/utils.py`:

```python
def group_pages_by_meeting_date(page_files: list[PageFile]) -> list[MeetingDateGroup]:
    """Group page files by (meeting, date) for context management.

    Args:
        page_files: List of PageFile objects

    Returns:
        List of MeetingDateGroup objects with page indices
    """
    if not page_files:
        return []

    groups = []
    current_key = None
    current_indices = []

    for idx, pf in enumerate(page_files):
        key = (pf.meeting, pf.date)

        if key != current_key:
            if current_key is not None:
                groups.append(MeetingDateGroup(
                    meeting=current_key[0],
                    date=current_key[1],
                    page_indices=current_indices
                ))
            current_key = key
            current_indices = [idx]
        else:
            current_indices.append(idx)

    # Don't forget the last group
    if current_key is not None:
        groups.append(MeetingDateGroup(
            meeting=current_key[0],
            date=current_key[1],
            page_indices=current_indices
        ))

    return groups
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_utils_refactor.py -v`
Expected: All 3 tests PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/clerk/utils.py tests/test_utils_refactor.py
git commit -m "refactor: extract group_pages_by_meeting_date helper"
```

---

## Task 3: Extract Pure Helper - create_meetings_schema

**Files:**
- Modify test: `tests/test_utils_refactor.py`
- Modify: `src/clerk/utils.py`

**Step 1: Write the failing test**

Add to `tests/test_utils_refactor.py`:

```python
import sqlite_utils
from clerk.utils import create_meetings_schema


def test_create_meetings_schema():
    """Test schema creation for meetings database."""
    db = sqlite_utils.Database(memory=True)

    create_meetings_schema(db)

    assert "minutes" in db.table_names()
    assert "agendas" in db.table_names()

    # Check schema
    minutes_cols = {col.name: col.type for col in db["minutes"].columns}
    assert minutes_cols["id"] == "TEXT"
    assert minutes_cols["meeting"] == "TEXT"
    assert minutes_cols["date"] == "TEXT"
    assert minutes_cols["page"] == "INTEGER"
    assert minutes_cols["text"] == "TEXT"
    assert minutes_cols["page_image"] == "TEXT"
    assert minutes_cols["entities_json"] == "TEXT"
    assert minutes_cols["votes_json"] == "TEXT"

    # Check primary key
    assert db["minutes"].pks == ["id"]
    assert db["agendas"].pks == ["id"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_utils_refactor.py::test_create_meetings_schema -v`
Expected: FAIL with "cannot import name 'create_meetings_schema'"

**Step 3: Write minimal implementation**

Add to `src/clerk/utils.py`:

```python
def create_meetings_schema(db):
    """Create standard schema for meetings database.

    Args:
        db: sqlite_utils.Database instance
    """
    schema = {
        "id": str,
        "meeting": str,
        "date": str,
        "page": int,
        "text": str,
        "page_image": str,
        "entities_json": str,
        "votes_json": str,
    }
    db["minutes"].create(schema, pk=("id"))
    db["agendas"].create(schema, pk=("id"))
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_utils_refactor.py::test_create_meetings_schema -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/clerk/utils.py tests/test_utils_refactor.py
git commit -m "refactor: extract create_meetings_schema helper"
```

---

## Task 4: Extract Filesystem Helper - collect_page_files

**Files:**
- Modify test: `tests/test_utils_refactor.py`
- Modify: `src/clerk/utils.py`

**Step 1: Write the failing test**

Add to `tests/test_utils_refactor.py`:

```python
import tempfile
import os
from clerk.utils import collect_page_files


def test_collect_page_files(tmp_path):
    """Test collecting page files from directory structure."""
    # Create fixture directory structure: txt_dir/meeting/date/page.txt
    txt_dir = tmp_path / "txt"
    meeting_dir = txt_dir / "council"
    date_dir = meeting_dir / "2024-01-15"
    date_dir.mkdir(parents=True)

    # Create page files
    (date_dir / "0001.txt").write_text("Page 1 content")
    (date_dir / "0002.txt").write_text("Page 2 content")

    # Second date
    date_dir2 = meeting_dir / "2024-02-20"
    date_dir2.mkdir(parents=True)
    (date_dir2 / "0001.txt").write_text("Page 3 content")

    page_files = collect_page_files(str(txt_dir))

    assert len(page_files) == 3
    assert page_files[0].meeting == "council"
    assert page_files[0].date == "2024-01-15"
    assert page_files[0].page_num == 1
    assert page_files[0].text == "Page 1 content"
    assert page_files[0].page_image_path == "/council/2024-01-15/0001.png"

    assert page_files[2].date == "2024-02-20"
    assert page_files[2].page_num == 1


def test_collect_page_files_empty(tmp_path):
    """Test with empty directory."""
    txt_dir = tmp_path / "empty"
    txt_dir.mkdir()

    page_files = collect_page_files(str(txt_dir))

    assert page_files == []
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_utils_refactor.py::test_collect_page_files -v`
Expected: FAIL with "cannot import name 'collect_page_files'"

**Step 3: Write minimal implementation**

Add to `src/clerk/utils.py`:

```python
def collect_page_files(txt_dir: str) -> list[PageFile]:
    """Collect all page files from nested directory structure.

    Flattens meeting/date/page directory structure into a flat list.

    Args:
        txt_dir: Root directory containing meeting subdirectories

    Returns:
        List of PageFile objects sorted by meeting, date, page
    """
    page_files = []

    if not os.path.exists(txt_dir):
        return page_files

    meetings = sorted([
        d for d in os.listdir(txt_dir)
        if d != ".DS_Store" and os.path.isdir(os.path.join(txt_dir, d))
    ])

    for meeting in meetings:
        meeting_path = os.path.join(txt_dir, meeting)
        dates = sorted([
            d for d in os.listdir(meeting_path)
            if d != ".DS_Store" and os.path.isdir(os.path.join(meeting_path, d))
        ])

        for date in dates:
            date_path = os.path.join(meeting_path, date)
            pages = sorted([
                p for p in os.listdir(date_path)
                if p.endswith(".txt")
            ])

            for page in pages:
                page_path = os.path.join(date_path, page)
                with open(page_path) as f:
                    text = f.read()

                page_num = int(page.split(".")[0])
                page_image_path = f"/{meeting}/{date}/{page.split('.')[0]}.png"

                page_files.append(PageFile(
                    meeting=meeting,
                    date=date,
                    page_num=page_num,
                    text=text,
                    page_image_path=page_image_path
                ))

    return page_files
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_utils_refactor.py -k collect_page_files -v`
Expected: Both tests PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/clerk/utils.py tests/test_utils_refactor.py
git commit -m "refactor: extract collect_page_files helper"
```

---

## Task 5: Extract spaCy Helper - batch_parse_with_spacy

**Files:**
- Modify test: `tests/test_utils_refactor.py`
- Modify: `src/clerk/utils.py`

**Step 1: Write the failing test**

Add to `tests/test_utils_refactor.py`:

```python
import pytest
from clerk.utils import batch_parse_with_spacy
from clerk.extraction import EXTRACTION_ENABLED


@pytest.mark.skipif(not EXTRACTION_ENABLED, reason="Extraction not enabled")
def test_batch_parse_with_spacy():
    """Test batch parsing with spaCy."""
    texts = ["This is a test.", "Another test sentence."]

    docs = batch_parse_with_spacy(texts, "test.civic.band")

    assert len(docs) == 2
    assert docs[0] is not None
    assert len(list(docs[0])) > 0  # Has tokens


def test_batch_parse_with_spacy_extraction_disabled():
    """Test batch parsing when extraction is disabled."""
    import os
    old_val = os.environ.get("ENABLE_EXTRACTION")
    os.environ["ENABLE_EXTRACTION"] = "0"

    try:
        texts = ["Test"]
        docs = batch_parse_with_spacy(texts, "test.civic.band")
        assert all(doc is None for doc in docs)
    finally:
        if old_val:
            os.environ["ENABLE_EXTRACTION"] = old_val
        else:
            os.environ.pop("ENABLE_EXTRACTION", None)


def test_batch_parse_with_spacy_empty():
    """Test with empty text list."""
    docs = batch_parse_with_spacy([], "test.civic.band")
    assert docs == []
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_utils_refactor.py -k batch_parse_with_spacy -v`
Expected: FAIL with "cannot import name 'batch_parse_with_spacy'"

**Step 3: Write minimal implementation**

Add to `src/clerk/utils.py`:

```python
def batch_parse_with_spacy(texts: list[str], subdomain: str) -> list:
    """Batch parse texts with spaCy using nlp.pipe().

    Args:
        texts: List of text strings to parse
        subdomain: Site subdomain for logging

    Returns:
        List of spaCy Doc objects (or None if extraction disabled)
    """
    if not texts:
        return []

    if not EXTRACTION_ENABLED:
        return [None] * len(texts)

    nlp = get_nlp()
    if nlp is None:
        return [None] * len(texts)

    total_pages = len(texts)
    click.echo(click.style(subdomain, fg="cyan") + f": Parsing {total_pages} pages...")

    n_process = int(os.environ.get("SPACY_N_PROCESS", "1"))
    pipe_kwargs = {"batch_size": 500}

    if n_process > 1:
        pipe_kwargs["n_process"] = n_process
        click.echo(
            click.style(subdomain, fg="cyan") + f": Using {n_process} processes for parsing"
        )

    all_docs = []
    progress_interval = 1000

    for i, doc in enumerate(nlp.pipe(texts, **pipe_kwargs)):
        all_docs.append(doc)
        if (i + 1) % progress_interval == 0:
            click.echo(
                click.style(subdomain, fg="cyan")
                + f": Parsed {i + 1}/{total_pages} pages..."
            )

    return all_docs
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_utils_refactor.py -k batch_parse_with_spacy -v`
Expected: Tests PASS (may skip if extraction not enabled)

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/clerk/utils.py tests/test_utils_refactor.py
git commit -m "refactor: extract batch_parse_with_spacy helper"
```

---

## Task 6: Extract Processing Helper - process_page_for_db

**Files:**
- Modify test: `tests/test_utils_refactor.py`
- Modify: `src/clerk/utils.py`

**Step 1: Write the failing test**

Add to `tests/test_utils_refactor.py`:

```python
from clerk.utils import process_page_for_db, PageFile
from clerk.extraction import create_meeting_context
import json


def test_process_page_for_db():
    """Test processing a page for database insertion."""
    page_file = PageFile(
        meeting="council",
        date="2024-01-15",
        page_num=1,
        text="Mayor Smith called the meeting to order. Motion to approve passed 5-0.",
        page_image_path="/council/2024-01-15/0001.png"
    )

    context = create_meeting_context()

    # Process without doc (extraction disabled case)
    entry = process_page_for_db(
        page_file=page_file,
        doc=None,
        context=context,
        subdomain="test.civic.band",
        table_name="minutes",
        municipality=None
    )

    assert entry["meeting"] == "council"
    assert entry["date"] == "2024-01-15"
    assert entry["page"] == 1
    assert entry["text"] == page_file.text
    assert entry["page_image"] == "/council/2024-01-15/0001.png"
    assert "id" in entry
    assert len(entry["id"]) == 12  # Hash prefix

    # Check entities/votes JSON (should be empty when extraction disabled)
    entities = json.loads(entry["entities_json"])
    votes = json.loads(entry["votes_json"])
    assert "persons" in entities
    assert "votes" in votes
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_utils_refactor.py::test_process_page_for_db -v`
Expected: FAIL with "cannot import name 'process_page_for_db'"

**Step 3: Write minimal implementation**

Add to `src/clerk/utils.py`:

```python
def process_page_for_db(
    page_file: PageFile,
    doc,
    context: dict,
    subdomain: str,
    table_name: str,
    municipality: str | None
) -> dict:
    """Process a single page for database insertion.

    Extracts entities/votes, updates context, formats as DB entry.

    Args:
        page_file: PageFile with page metadata and text
        doc: spaCy Doc object (or None if extraction disabled)
        context: Meeting context dict for accumulating entities
        subdomain: Site subdomain
        table_name: "minutes" or "agendas"
        municipality: Optional municipality name

    Returns:
        Dict ready for db.insert() with all required fields
    """
    text = page_file.text

    # Extract entities and update context
    try:
        entities = extract_entities(text, doc=doc)
        update_context(context, entities=entities)
    except Exception as e:
        logger.warning(
            f"Entity extraction failed for {page_file.meeting}/{page_file.date}/{page_file.page_num}: {e}"
        )
        entities = {"persons": [], "orgs": [], "locations": []}

    # Detect roll call and update context
    try:
        attendees = detect_roll_call(text)
        if attendees:
            update_context(context, attendees=attendees)
    except Exception as e:
        logger.warning(
            f"Roll call detection failed for {page_file.meeting}/{page_file.date}/{page_file.page_num}: {e}"
        )

    # Extract votes with context
    try:
        votes = extract_votes(text, doc=doc, meeting_context=context)
    except Exception as e:
        logger.warning(
            f"Vote extraction failed for {page_file.meeting}/{page_file.date}/{page_file.page_num}: {e}"
        )
        votes = {"votes": []}

    # Build database entry
    key_hash = {
        "kind": "minutes" if table_name != "agendas" else "agenda",
        "meeting": page_file.meeting,
        "date": page_file.date,
        "page": page_file.page_num,
        "text": text,
    }

    if municipality:
        key_hash.update({"subdomain": subdomain, "municipality": municipality})

    key = sha256(json.dumps(key_hash, sort_keys=True).encode("utf-8")).hexdigest()
    key = key[:12]

    entry = {
        "id": key,
        "meeting": page_file.meeting,
        "date": page_file.date,
        "page": page_file.page_num,
        "text": text,
        "page_image": page_file.page_image_path,
        "entities_json": json.dumps(entities),
        "votes_json": json.dumps(votes),
    }

    return entry
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_utils_refactor.py::test_process_page_for_db -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/clerk/utils.py tests/test_utils_refactor.py
git commit -m "refactor: extract process_page_for_db helper"
```

---

## Task 7: Extract Database Helpers for extract_entities_for_site

**Files:**
- Modify test: `tests/test_utils_refactor.py`
- Modify: `src/clerk/utils.py`

**Step 1: Write failing test for load_pages_from_db**

Add to `tests/test_utils_refactor.py`:

```python
from clerk.utils import load_pages_from_db, create_meetings_schema
import sqlite_utils


def test_load_pages_from_db(tmp_path):
    """Test loading pages from database."""
    # Create test database
    db_path = tmp_path / "test.db"
    db = sqlite_utils.Database(str(db_path))
    create_meetings_schema(db)

    # Insert test data
    db["minutes"].insert_all([
        {"id": "abc", "meeting": "council", "date": "2024-01-15", "page": 1,
         "text": "test", "page_image": "/path.png", "entities_json": "{}",
         "votes_json": "{}"},
        {"id": "def", "meeting": "council", "date": "2024-01-15", "page": 2,
         "text": "test2", "page_image": "/path2.png", "entities_json": "{}",
         "votes_json": "{}"},
    ])
    db.close()

    # Create subdomain directory structure
    subdomain_dir = tmp_path / "test.civic.band"
    subdomain_dir.mkdir()
    (subdomain_dir / "meetings.db").write_bytes((tmp_path / "test.db").read_bytes())

    # Test loading (need to set STORAGE_DIR)
    import os
    old_storage = os.environ.get("STORAGE_DIR")
    os.environ["STORAGE_DIR"] = str(tmp_path)

    try:
        pages = load_pages_from_db("test.civic.band", "minutes")

        assert len(pages) == 2
        assert pages[0]["id"] == "abc"
        assert pages[0]["meeting"] == "council"
        assert pages[1]["page"] == 2
    finally:
        if old_storage:
            os.environ["STORAGE_DIR"] = old_storage
        else:
            os.environ.pop("STORAGE_DIR", None)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_utils_refactor.py::test_load_pages_from_db -v`
Expected: FAIL with "cannot import name 'load_pages_from_db'"

**Step 3: Write implementation for load_pages_from_db**

Add to `src/clerk/utils.py`:

```python
def load_pages_from_db(subdomain: str, table_name: str) -> list[dict]:
    """Load all page records from site's database.

    Args:
        subdomain: Site subdomain
        table_name: "minutes" or "agendas"

    Returns:
        List of page dicts from database
    """
    storage_dir = os.environ.get("STORAGE_DIR", "../sites")
    site_db_path = f"{storage_dir}/{subdomain}/meetings.db"
    db = sqlite_utils.Database(site_db_path)

    if not db[table_name].exists():
        return []

    return list(db[table_name].rows)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_utils_refactor.py::test_load_pages_from_db -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/clerk/utils.py tests/test_utils_refactor.py
git commit -m "refactor: extract load_pages_from_db helper"
```

---

## Task 8: Extract collect_page_data_with_cache Helper

**Files:**
- Modify test: `tests/test_utils_refactor.py`
- Modify: `src/clerk/utils.py`

**Step 1: Write the failing test**

Add to `tests/test_utils_refactor.py`:

```python
from clerk.utils import collect_page_data_with_cache
import json


def test_collect_page_data_with_cache(tmp_path):
    """Test collecting page data with cache checking."""
    # Create text files
    txt_dir = tmp_path / "txt"
    meeting_dir = txt_dir / "council" / "2024-01-15"
    meeting_dir.mkdir(parents=True)

    page1 = meeting_dir / "0001.txt"
    page1.write_text("Test content")

    # Create cache file
    cache_file = meeting_dir / "0001.txt.extracted.json"
    cache_data = {
        "content_hash": "abc123",
        "extracted_at": "2024-01-01T00:00:00",
        "entities": {"persons": [], "orgs": [], "locations": []},
        "votes": {"votes": []}
    }
    cache_file.write_text(json.dumps(cache_data))

    pages = [
        {"id": "test1", "meeting": "council", "date": "2024-01-15", "page": 1}
    ]

    # Mock STORAGE_DIR
    import os
    old_storage = os.environ.get("STORAGE_DIR")
    os.environ["STORAGE_DIR"] = str(tmp_path)
    subdomain_dir = tmp_path / "test.civic.band"
    subdomain_dir.mkdir()
    txt_final = subdomain_dir / "txt"
    txt_final.symlink_to(txt_dir)

    try:
        page_data = collect_page_data_with_cache(
            pages, "test.civic.band", "minutes", force_extraction=False
        )

        assert len(page_data) == 1
        assert page_data[0].page_id == "test1"
        assert page_data[0].text == "Test content"
        assert page_data[0].cached_extraction is not None
    finally:
        if old_storage:
            os.environ["STORAGE_DIR"] = old_storage
        else:
            os.environ.pop("STORAGE_DIR", None)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_utils_refactor.py::test_collect_page_data_with_cache -v`
Expected: FAIL with "cannot import name 'collect_page_data_with_cache'"

**Step 3: Write minimal implementation**

Add to `src/clerk/utils.py`:

```python
def collect_page_data_with_cache(
    pages: list[dict],
    subdomain: str,
    table_name: str,
    force_extraction: bool
) -> list[PageData]:
    """Collect page data with cache checking.

    Reads text files and checks extraction cache for each page.

    Args:
        pages: List of page dicts from database
        subdomain: Site subdomain
        table_name: "minutes" or "agendas"
        force_extraction: If True, ignore cache

    Returns:
        List of PageData objects with cache information
    """
    from .output import log

    storage_dir = os.environ.get("STORAGE_DIR", "../sites")
    txt_subdir = "txt" if table_name == "minutes" else "_agendas/txt"
    txt_dir = f"{storage_dir}/{subdomain}/{txt_subdir}"

    if not os.path.exists(txt_dir):
        return []

    all_page_data = []
    cache_hits = 0
    cache_misses = 0

    for page in pages:
        meeting = page["meeting"]
        date = page["date"]
        page_num = page["page"]

        # Find corresponding text file
        page_file_path = f"{txt_dir}/{meeting}/{date}/{page_num:04d}.txt"

        if not os.path.exists(page_file_path):
            logger.warning(f"Text file not found: {page_file_path}")
            continue

        with open(page_file_path) as f:
            text = f.read()

        # Check cache
        cached_extraction = None
        content_hash = None

        if not force_extraction:
            content_hash = hash_text_content(text)
            cache_file = f"{page_file_path}.extracted.json"
            cached_extraction = load_extraction_cache(cache_file, content_hash)

            if cached_extraction:
                cache_hits += 1
            else:
                cache_misses += 1
        else:
            cache_misses += 1

        all_page_data.append(PageData(
            page_id=page["id"],
            text=text,
            page_file_path=page_file_path,
            content_hash=content_hash,
            cached_extraction=cached_extraction,
        ))

    log(
        f"Cache status: {cache_hits} hits, {cache_misses} misses",
        subdomain=subdomain,
        cache_hits=cache_hits,
        cache_misses=cache_misses
    )

    return all_page_data
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_utils_refactor.py::test_collect_page_data_with_cache -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 6: Commit**

```bash
git add src/clerk/utils.py tests/test_utils_refactor.py
git commit -m "refactor: extract collect_page_data_with_cache helper"
```

---

## Task 9: Extract batch_process_uncached_pages Helper

**Files:**
- Modify: `src/clerk/utils.py`
- Test: Run existing tests

**Step 1: Write minimal implementation**

Add to `src/clerk/utils.py`:

```python
def batch_process_uncached_pages(page_data: list[PageData], subdomain: str) -> list:
    """Batch process uncached pages with spaCy.

    Args:
        page_data: List of PageData objects
        subdomain: Site subdomain for logging

    Returns:
        List of Docs parallel to page_data (None for cached pages)
    """
    from .output import log

    uncached_indices = [i for i, p in enumerate(page_data) if p.cached_extraction is None]
    all_docs = [None] * len(page_data)

    if uncached_indices and EXTRACTION_ENABLED:
        uncached_texts = [page_data[i].text for i in uncached_indices]
        nlp = get_nlp()
        if nlp:
            log(f"Batch processing {len(uncached_texts)} uncached pages with nlp.pipe()", subdomain=subdomain)
            # Single batch process with nlp.pipe()
            for processed, doc in enumerate(nlp.pipe(uncached_texts, batch_size=500)):
                original_idx = uncached_indices[processed]
                all_docs[original_idx] = doc

    return all_docs
```

**Step 2: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 3: Commit**

```bash
git add src/clerk/utils.py
git commit -m "refactor: extract batch_process_uncached_pages helper"
```

---

## Task 10: Extract save_extractions_to_db Helper

**Files:**
- Modify: `src/clerk/utils.py`
- Test: Run existing tests

**Step 1: Write minimal implementation**

Add to `src/clerk/utils.py`:

```python
def save_extractions_to_db(
    page_data: list[PageData],
    docs: list,
    subdomain: str,
    table_name: str
):
    """Save extractions to database (extract or use cache).

    For each page: use cached extraction OR extract from doc,
    save to cache, update database.

    Args:
        page_data: List of PageData objects
        docs: List of spaCy Docs (parallel to page_data)
        subdomain: Site subdomain
        table_name: "minutes" or "agendas"
    """
    storage_dir = os.environ.get("STORAGE_DIR", "../sites")
    site_db_path = f"{storage_dir}/{subdomain}/meetings.db"
    db = sqlite_utils.Database(site_db_path)

    for i, pdata in enumerate(page_data):
        doc = docs[i]
        cached = pdata.cached_extraction

        if cached:
            entities = cached["entities"]
            votes = cached["votes"]
        else:
            if not EXTRACTION_ENABLED:
                # Skip extraction if disabled
                continue

            # Extract entities and votes using pre-parsed doc
            try:
                entities = extract_entities(pdata.text, doc=doc)
                votes = extract_votes(pdata.text, doc=doc, meeting_context={})
            except Exception as e:
                logger.warning(f"Extraction failed for {pdata.page_file_path}: {e}")
                entities = {"persons": [], "orgs": [], "locations": []}
                votes = {"votes": []}

            # Write cache
            content_hash = pdata.content_hash
            if content_hash is None:
                content_hash = hash_text_content(pdata.text)
            cache_file = f"{pdata.page_file_path}.extracted.json"
            cache_data = {
                "content_hash": content_hash,
                "extracted_at": datetime.datetime.now().isoformat(),
                "entities": entities,
                "votes": votes,
            }
            save_extraction_cache(cache_file, cache_data)

        # Update database
        db[table_name].update(
            pdata.page_id,
            {
                "entities_json": json.dumps(entities),
                "votes_json": json.dumps(votes)
            }
        )
```

**Step 2: Run full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 3: Commit**

```bash
git add src/clerk/utils.py
git commit -m "refactor: extract save_extractions_to_db helper"
```

---

## Task 11: Refactor build_db_from_text_internal

**Files:**
- Modify: `src/clerk/utils.py`
- Test: Run existing tests

**Step 1: Refactor to use create_meetings_schema**

Find `build_db_from_text_internal` in `src/clerk/utils.py` and replace the schema creation section with a call to `create_meetings_schema(db)`.

Before (lines ~288-312):
```python
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
            "entities_json": str,
            "votes_json": str,
        },
        pk=("id"),
    )
```

After:
```python
    create_meetings_schema(db)
```

**Step 2: Run tests to verify behavior unchanged**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 3: Commit**

```bash
git add src/clerk/utils.py
git commit -m "refactor: use create_meetings_schema in build_db_from_text_internal"
```

---

## Task 12: Refactor build_table_from_text - Phase 1

**Files:**
- Modify: `src/clerk/utils.py`
- Test: Run existing tests

**Step 1: Replace Phase 1 (directory walking) with collect_page_files**

Find `build_table_from_text` function. Replace the directory walking section (lines ~124-168) with:

```python
    # Phase 1: Collect all page files
    page_files = collect_page_files(txt_dir)
    if not page_files:
        return

    # Phase 2: Batch parse all texts with spaCy
    texts = [pf.text for pf in page_files]
```

Remove the old nested loop code that built `all_page_data`.

**Step 2: Run tests to verify behavior unchanged**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 3: Commit**

```bash
git add src/clerk/utils.py
git commit -m "refactor: use collect_page_files in build_table_from_text phase 1"
```

---

## Task 13: Refactor build_table_from_text - Phase 2

**Files:**
- Modify: `src/clerk/utils.py`
- Test: Run existing tests

**Step 1: Replace Phase 2 (spaCy parsing) with batch_parse_with_spacy**

Find the section that does spaCy parsing (lines ~174-202). Replace with:

```python
    docs = batch_parse_with_spacy(texts, subdomain)
```

**Step 2: Run tests to verify behavior unchanged**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 3: Commit**

```bash
git add src/clerk/utils.py
git commit -m "refactor: use batch_parse_with_spacy in build_table_from_text phase 2"
```

---

## Task 14: Refactor build_table_from_text - Phase 3

**Files:**
- Modify: `src/clerk/utils.py`
- Test: Run existing tests

**Step 1: Use group_pages_by_meeting_date and process_page_for_db**

Replace Phase 3 processing (lines ~204-274) with:

```python
    # Phase 3: Process pages grouped by meeting date (for context)
    entries = []
    for meeting_date_group in group_pages_by_meeting_date(page_files):
        # Log progress per meeting
        if meeting_date_group.meeting != getattr(build_table_from_text, '_last_meeting', None):
            click.echo(click.style(subdomain, fg="cyan") + ": " + f"Processing {meeting_date_group.meeting}")
            build_table_from_text._last_meeting = meeting_date_group.meeting

        # Create fresh context for each meeting date
        meeting_context = create_meeting_context()

        # Process pages for this meeting date with their pre-parsed docs
        for idx in meeting_date_group.page_indices:
            entry = process_page_for_db(
                page_files[idx], docs[idx], meeting_context,
                subdomain, table_name, municipality
            )
            entries.append(entry)

    # Phase 4: Insert to database
    db[table_name].insert_all(entries)
```

**Step 2: Run tests to verify behavior unchanged**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 3: Commit**

```bash
git add src/clerk/utils.py
git commit -m "refactor: use helpers in build_table_from_text phase 3"
```

---

## Task 15: Refactor extract_entities_for_site

**Files:**
- Modify: `src/clerk/utils.py`
- Test: Run existing tests

**Step 1: Extract extract_table_entities helper**

Add new function before `extract_entities_for_site`:

```python
def extract_table_entities(subdomain: str, table_name: str, force_extraction: bool):
    """Extract entities for one table (minutes or agendas).

    Args:
        subdomain: Site subdomain
        table_name: "minutes" or "agendas"
        force_extraction: If True, bypass cache
    """
    # Phase 1: Load pages and check cache
    pages = load_pages_from_db(subdomain, table_name)
    if not pages:
        return

    page_data = collect_page_data_with_cache(
        pages, subdomain, table_name, force_extraction
    )

    # Phase 2: Batch process uncached pages
    docs = batch_process_uncached_pages(page_data, subdomain)

    # Phase 3: Save extractions (extract/cache/update DB)
    save_extractions_to_db(page_data, docs, subdomain, table_name)
```

**Step 2: Refactor extract_entities_for_site to use helper**

Replace the body of `extract_entities_for_site` (keep timing/logging):

```python
def extract_entities_for_site(subdomain, force_extraction=False):
    """Extract entities for all pages in a site's database

    Reads existing database records, processes uncached pages with spaCy,
    and updates entities_json/votes_json columns.

    Args:
        subdomain: Site subdomain (e.g., "alameda.ca.civic.band")
        force_extraction: If True, bypass cache and re-extract all pages
    """
    from .output import log

    st = time.time()
    logger.info("Extracting entities subdomain=%s force_extraction=%s", subdomain, force_extraction)

    # Process both minutes and agendas
    for table_name in ["minutes", "agendas"]:
        extract_table_entities(subdomain, table_name, force_extraction)

    et = time.time()
    elapsed = et - st
    log(f"Total extraction time: {elapsed:.2f}s", subdomain=subdomain, elapsed_time=f"{elapsed:.2f}")
```

**Step 3: Run tests to verify behavior unchanged**

Run: `uv run pytest tests/ -q`
Expected: All tests pass

**Step 4: Commit**

```bash
git add src/clerk/utils.py
git commit -m "refactor: simplify extract_entities_for_site with helpers"
```

---

## Task 16: Final Verification and Cleanup

**Files:**
- All modified files
- Test: Full test suite

**Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS

**Step 2: Run linter**

Run: `uv run ruff check src/ tests/`
Expected: No errors (or fix any that appear)

**Step 3: Run type checker (if available)**

Run: `uv run mypy src/clerk/utils.py` (or skip if mypy not installed)
Expected: No errors

**Step 4: Manual smoke test (optional)**

If you have test data available:
```bash
uv run clerk build-db-from-text --subdomain example.civic.band
```

Expected: Builds successfully with same behavior as before

**Step 5: Final commit if any fixes needed**

```bash
git add -u
git commit -m "refactor: final cleanup and fixes"
```

---

## Summary

This plan refactors `build_table_from_text`, `extract_entities_for_site`, and `build_db_from_text_internal` into smaller, focused helper functions organized by concern:

- **Data classes**: `PageFile`, `PageData`, `MeetingDateGroup`
- **Pure helpers**: `group_pages_by_meeting_date`, `create_meetings_schema`
- **Filesystem**: `collect_page_files`
- **spaCy**: `batch_parse_with_spacy`, `batch_process_uncached_pages`
- **Processing**: `process_page_for_db`
- **Database**: `load_pages_from_db`, `collect_page_data_with_cache`, `save_extractions_to_db`
- **Orchestration**: `extract_table_entities`

The refactored code maintains identical behavior while being more readable, testable, and maintainable.
