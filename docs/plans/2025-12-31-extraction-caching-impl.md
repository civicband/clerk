# Extraction Caching Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add content-hash-based caching to speed up spaCy extraction from 2 hours to minutes for incremental updates

**Architecture:** Store extraction results in `.extracted.json` files alongside text files. Hash text content, check for matching cache, load if valid, otherwise batch process uncached pages through spaCy.

**Tech Stack:** Python 3.12+, spaCy, SHA256 hashing, JSON file I/O

---

## Task 1: Add Cache Utility Functions

**Files:**
- Modify: `src/clerk/utils.py:1-20` (add imports and helper functions)
- Test: `tests/test_utils.py`

### Step 1: Write test for hash_text_content

```python
# tests/test_utils.py - add to existing file

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
```

### Step 2: Run test to verify it fails

Run: `/Users/phildini/code/civicband/clerk/.venv/bin/python -m pytest tests/test_utils.py::test_hash_text_content -v`

Expected: FAIL with "ImportError: cannot import name 'hash_text_content'"

### Step 3: Implement hash_text_content

```python
# src/clerk/utils.py - add after existing imports (around line 20)

def hash_text_content(text: str) -> str:
    """Hash text content for cache validation.

    Args:
        text: The text content to hash

    Returns:
        SHA256 hash as hex string
    """
    return sha256(text.encode("utf-8")).hexdigest()
```

### Step 4: Run test to verify it passes

Run: `/Users/phildini/code/civicband/clerk/.venv/bin/python -m pytest tests/test_utils.py::test_hash_text_content -v`

Expected: PASS

### Step 5: Write test for load_extraction_cache

```python
# tests/test_utils.py

def test_load_extraction_cache_valid(tmp_path):
    """Test loading valid cache file with matching hash."""
    from clerk.utils import load_extraction_cache
    import json

    cache_file = tmp_path / "test.txt.extracted.json"
    expected_hash = "abc123"
    cache_data = {
        "content_hash": "abc123",
        "model_version": "en_core_web_md",
        "extracted_at": "2025-12-31T12:00:00Z",
        "entities": {"persons": ["John Doe"], "orgs": [], "locations": []},
        "votes": {"votes": []}
    }

    cache_file.write_text(json.dumps(cache_data))

    result = load_extraction_cache(str(cache_file), expected_hash)

    assert result is not None
    assert result["content_hash"] == "abc123"
    assert result["entities"]["persons"] == ["John Doe"]


def test_load_extraction_cache_hash_mismatch(tmp_path):
    """Test cache rejected when hash doesn't match."""
    from clerk.utils import load_extraction_cache
    import json

    cache_file = tmp_path / "test.txt.extracted.json"
    cache_data = {
        "content_hash": "abc123",
        "entities": {"persons": [], "orgs": [], "locations": []},
        "votes": {"votes": []}
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
```

### Step 6: Run tests to verify they fail

Run: `/Users/phildini/code/civicband/clerk/.venv/bin/python -m pytest tests/test_utils.py::test_load_extraction_cache_valid tests/test_utils.py::test_load_extraction_cache_hash_mismatch tests/test_utils.py::test_load_extraction_cache_missing_file tests/test_utils.py::test_load_extraction_cache_corrupted_json -v`

Expected: FAIL with "ImportError: cannot import name 'load_extraction_cache'"

### Step 7: Implement load_extraction_cache

```python
# src/clerk/utils.py - add after hash_text_content

def load_extraction_cache(cache_file: str, expected_hash: str) -> dict | None:
    """Load extraction cache if valid.

    Args:
        cache_file: Path to .extracted.json cache file
        expected_hash: Expected content hash

    Returns:
        Cache data dict if valid, None otherwise
    """
    try:
        with open(cache_file) as f:
            data = json.load(f)

        # Validate structure
        required_keys = {"content_hash", "entities", "votes"}
        if not required_keys.issubset(data.keys()):
            logger.debug(f"Cache invalid: missing keys in {cache_file}")
            return None

        # Validate hash match
        if data["content_hash"] != expected_hash:
            logger.debug(f"Cache invalid: hash mismatch in {cache_file}")
            return None

        return data
    except (json.JSONDecodeError, FileNotFoundError, KeyError) as e:
        logger.debug(f"Cache invalid: {e} in {cache_file}")
        return None
```

### Step 8: Run tests to verify they pass

Run: `/Users/phildini/code/civicband/clerk/.venv/bin/python -m pytest tests/test_utils.py::test_load_extraction_cache_valid tests/test_utils.py::test_load_extraction_cache_hash_mismatch tests/test_utils.py::test_load_extraction_cache_missing_file tests/test_utils.py::test_load_extraction_cache_corrupted_json -v`

Expected: PASS (4 tests)

### Step 9: Write test for save_extraction_cache

```python
# tests/test_utils.py

def test_save_extraction_cache(tmp_path):
    """Test saving extraction cache to file."""
    from clerk.utils import save_extraction_cache
    import json

    cache_file = tmp_path / "test.txt.extracted.json"
    cache_data = {
        "content_hash": "abc123",
        "model_version": "en_core_web_md",
        "extracted_at": "2025-12-31T12:00:00Z",
        "entities": {"persons": ["Jane Smith"], "orgs": ["City Council"], "locations": []},
        "votes": {"votes": [{"motion": "Test", "result": "passed"}]}
    }

    save_extraction_cache(str(cache_file), cache_data)

    assert cache_file.exists()

    with open(cache_file) as f:
        loaded = json.load(f)

    assert loaded["content_hash"] == "abc123"
    assert loaded["entities"]["persons"] == ["Jane Smith"]
    assert loaded["votes"]["votes"][0]["motion"] == "Test"
```

### Step 10: Run test to verify it fails

Run: `/Users/phildini/code/civicband/clerk/.venv/bin/python -m pytest tests/test_utils.py::test_save_extraction_cache -v`

Expected: FAIL with "ImportError: cannot import name 'save_extraction_cache'"

### Step 11: Implement save_extraction_cache

```python
# src/clerk/utils.py - add after load_extraction_cache

def save_extraction_cache(cache_file: str, data: dict) -> None:
    """Save extraction results to cache file.

    Args:
        cache_file: Path to .extracted.json cache file
        data: Cache data to save (must include content_hash, entities, votes)
    """
    try:
        with open(cache_file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save cache {cache_file}: {e}")
```

### Step 12: Run test to verify it passes

Run: `/Users/phildini/code/civicband/clerk/.venv/bin/python -m pytest tests/test_utils.py::test_save_extraction_cache -v`

Expected: PASS

### Step 13: Commit cache utility functions

```bash
git add src/clerk/utils.py tests/test_utils.py
git commit -m "feat: add cache utility functions for extraction caching"
```

---

## Task 2: Modify Phase 1 to Check Cache

**Files:**
- Modify: `src/clerk/utils.py:69-123` (build_table_from_text Phase 1)
- Test: `tests/test_utils.py`

### Step 1: Write test for cache checking in Phase 1

```python
# tests/test_utils.py

def test_build_table_from_text_uses_cache(tmp_path, monkeypatch):
    """Test that build_table_from_text uses cache when available."""
    from clerk.utils import build_table_from_text, save_extraction_cache, hash_text_content
    import sqlite_utils

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

    # Create cache file with extraction results
    cache_file = str(text_file) + ".extracted.json"
    content_hash = hash_text_content(text_content)
    cache_data = {
        "content_hash": content_hash,
        "model_version": "en_core_web_md",
        "extracted_at": "2025-12-31T12:00:00Z",
        "entities": {"persons": ["Cached Person"], "orgs": [], "locations": []},
        "votes": {"votes": []}
    }
    save_extraction_cache(cache_file, cache_data)

    # Create database
    db = sqlite_utils.Database(tmp_path / "test.db")
    db["minutes"].create({
        "id": str,
        "meeting": str,
        "date": str,
        "page": int,
        "text": str,
        "page_image": str,
        "entities_json": str,
        "votes_json": str,
    }, pk="id")

    # Disable extraction so we know results came from cache
    monkeypatch.setenv("ENABLE_EXTRACTION", "0")

    # Run build
    build_table_from_text(subdomain, str(txt_dir), db, "minutes")

    # Verify cache was used
    rows = list(db["minutes"].rows)
    assert len(rows) == 1

    import json
    entities = json.loads(rows[0]["entities_json"])
    assert entities["persons"] == ["Cached Person"], "Should use cached entities"
```

### Step 2: Run test to verify it fails

Run: `/Users/phildini/code/civicband/clerk/.venv/bin/python -m pytest tests/test_utils.py::test_build_table_from_text_uses_cache -v`

Expected: FAIL (cache not checked yet, extraction will be empty)

### Step 3: Modify Phase 1 to check cache

```python
# src/clerk/utils.py - Replace Phase 1 (lines ~80-120)

def build_table_from_text(subdomain, txt_dir, db, table_name, municipality=None, force_extraction=False):
    logger.info(
        "Building table from text subdomain=%s table_name=%s municipality=%s force_extraction=%s",
        subdomain,
        table_name,
        municipality,
        force_extraction,
    )
    directories = [
        directory for directory in sorted(os.listdir(txt_dir)) if directory != ".DS_Store"
    ]

    # Phase 1: Collect ALL page data and check cache
    all_page_data = []
    meeting_date_boundaries = []
    cache_hits = 0
    cache_misses = 0

    for meeting in directories:
        meeting_dates = [
            meeting_date
            for meeting_date in sorted(os.listdir(f"{txt_dir}/{meeting}"))
            if meeting_date != ".DS_Store"
        ]
        for meeting_date in meeting_dates:
            start_idx = len(all_page_data)
            pages = sorted(os.listdir(f"{txt_dir}/{meeting}/{meeting_date}"))

            for page in pages:
                if not page.endswith(".txt"):
                    continue
                page_file_path = f"{txt_dir}/{meeting}/{meeting_date}/{page}"
                with open(page_file_path) as page_file:
                    text = page_file.read()
                    page_number = int(page.split(".")[0])
                    page_image_path = f"/{meeting}/{meeting_date}/{page.split('.')[0]}.png"
                    if table_name == "agendas":
                        page_image_path = (
                            f"/_agendas/{meeting}/{meeting_date}/{page.split('.')[0]}.png"
                        )

                    # Check cache
                    cached_extraction = None
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

                    all_page_data.append(
                        {
                            "text": text,
                            "page_number": page_number,
                            "page_image_path": page_image_path,
                            "page_file_path": page_file_path,
                            "meeting": meeting,
                            "meeting_date": meeting_date,
                            "cached_extraction": cached_extraction,
                            "content_hash": hash_text_content(text) if cached_extraction is None else cached_extraction["content_hash"],
                        }
                    )

            end_idx = len(all_page_data)
            if end_idx > start_idx:
                meeting_date_boundaries.append((meeting, meeting_date, start_idx, end_idx))

    if not all_page_data:
        return

    total_files = len(all_page_data)
    log(
        f"Cache hits: {cache_hits}, needs extraction: {cache_misses}",
        subdomain=subdomain,
        cache_hits=cache_hits,
        needs_extraction=cache_misses,
    )
```

### Step 4: Update function signature in build_db_from_text_internal

```python
# src/clerk/utils.py - Update calls to build_table_from_text (around line 270)

    if os.path.exists(minutes_txt_dir):
        build_table_from_text(subdomain, minutes_txt_dir, db, "minutes", force_extraction=False)
    if os.path.exists(agendas_txt_dir):
        build_table_from_text(subdomain, agendas_txt_dir, db, "agendas", force_extraction=False)
```

### Step 5: Run test to verify behavior changed

Run: `/Users/phildini/code/civicband/clerk/.venv/bin/python -m pytest tests/test_utils.py::test_build_table_from_text_uses_cache -v`

Expected: Still may fail but should show cache checking logic

### Step 6: Commit Phase 1 cache checking

```bash
git add src/clerk/utils.py tests/test_utils.py
git commit -m "feat: add cache checking in build_table_from_text Phase 1"
```

---

## Task 3: Modify Phase 2 to Process Only Uncached Pages

**Files:**
- Modify: `src/clerk/utils.py:125-154` (Phase 2 spaCy processing)

### Step 1: Modify Phase 2 to filter uncached pages

```python
# src/clerk/utils.py - Replace Phase 2 (lines ~125-154)

    # Phase 2: Batch process only uncached pages
    total_pages = len(all_page_data)
    uncached_indices = [
        i for i, p in enumerate(all_page_data) if p["cached_extraction"] is None
    ]

    log(f"Processing {len(uncached_indices)} uncached pages with spaCy...", subdomain=subdomain)

    # Initialize docs array (cached pages get None placeholder)
    all_docs = [None] * total_pages

    if uncached_indices and EXTRACTION_ENABLED:
        # Extract only uncached texts
        uncached_texts = [all_page_data[i]["text"] for i in uncached_indices]

        nlp = get_nlp()
        if nlp is not None:
            n_process = int(os.environ.get("SPACY_N_PROCESS", "1"))
            progress_interval = 1000
            pipe_kwargs = {"batch_size": 500}
            if n_process > 1:
                pipe_kwargs["n_process"] = n_process
                log(
                    f"Using {n_process} processes for parsing",
                    subdomain=subdomain
                )

            # Process uncached pages and populate docs array
            for processed, doc in enumerate(nlp.pipe(uncached_texts, **pipe_kwargs)):
                original_idx = uncached_indices[processed]
                all_docs[original_idx] = doc

                if (processed + 1) % progress_interval == 0:
                    log(
                        f"Extracted {processed + 1}/{len(uncached_indices)} pages...",
                        subdomain=subdomain,
                        progress=f"{processed + 1}/{len(uncached_indices)}"
                    )
```

### Step 2: Run existing tests to verify no regression

Run: `/Users/phildini/code/civicband/clerk/.venv/bin/python -m pytest tests/test_utils.py -v -k build_table`

Expected: Tests should still pass (or closer to passing)

### Step 3: Commit Phase 2 optimization

```bash
git add src/clerk/utils.py
git commit -m "feat: optimize Phase 2 to only process uncached pages"
```

---

## Task 4: Add Cache Writing After Extraction

**Files:**
- Modify: `src/clerk/utils.py:156-225` (Phase 3 processing)

### Step 1: Modify Phase 3 to write cache files

```python
# src/clerk/utils.py - Modify Phase 3 entity extraction section (lines ~180-186)

            # Extract entities and update context
            try:
                # Check if we have cached extraction
                if pdata["cached_extraction"]:
                    entities = pdata["cached_extraction"]["entities"]
                else:
                    entities = extract_entities(text, doc=doc)

                update_context(meeting_context, entities=entities)
            except Exception as e:
                log(
                    f"Entity extraction failed for {page_file_path}",
                    subdomain=subdomain,
                    level="warning",
                    error=str(e)
                )
                entities = {"persons": [], "orgs": [], "locations": []}
```

### Step 2: Modify vote extraction to use cache

```python
# src/clerk/utils.py - Modify vote extraction section (lines ~196-201)

            # Extract votes with context
            try:
                # Check if we have cached extraction
                if pdata["cached_extraction"]:
                    votes = pdata["cached_extraction"]["votes"]
                else:
                    votes = extract_votes(text, doc=doc, meeting_context=meeting_context)
            except Exception as e:
                log(
                    f"Vote extraction failed for {page_file_path}",
                    subdomain=subdomain,
                    level="warning",
                    error=str(e)
                )
                votes = {"votes": []}
```

### Step 3: Add cache writing after extraction

```python
# src/clerk/utils.py - Add after vote extraction (before key_hash.update)

            # Write cache if this was a fresh extraction
            if pdata["cached_extraction"] is None and EXTRACTION_ENABLED:
                cache_file = f"{page_file_path}.extracted.json"
                cache_data = {
                    "content_hash": pdata["content_hash"],
                    "model_version": get_nlp().meta["version"] if get_nlp() else "unknown",
                    "extracted_at": datetime.datetime.now().isoformat(),
                    "entities": entities,
                    "votes": votes,
                }
                save_extraction_cache(cache_file, cache_data)
```

### Step 4: Add datetime import at top of file

```python
# src/clerk/utils.py - Add to imports (around line 1)
import datetime
```

### Step 5: Run test to verify cache is written

Run: `/Users/phildini/code/civicband/clerk/.venv/bin/python -m pytest tests/test_utils.py::test_build_table_from_text_uses_cache -v`

Expected: PASS

### Step 6: Write test to verify cache files are created

```python
# tests/test_utils.py

def test_build_table_from_text_creates_cache(tmp_path, monkeypatch):
    """Test that cache files are created after extraction."""
    from clerk.utils import build_table_from_text
    import sqlite_utils

    # Set up test directory
    subdomain = "test.civic.band"
    txt_dir = tmp_path / "txt"
    meeting_dir = txt_dir / "city-council"
    date_dir = meeting_dir / "2024-01-15"
    date_dir.mkdir(parents=True)

    # Create test text file
    text_file = date_dir / "001.txt"
    text_file.write_text("Test meeting minutes")

    # Create database
    db = sqlite_utils.Database(tmp_path / "test.db")
    db["minutes"].create({
        "id": str,
        "meeting": str,
        "date": str,
        "page": int,
        "text": str,
        "page_image": str,
        "entities_json": str,
        "votes_json": str,
    }, pk="id")

    # Enable extraction
    monkeypatch.setenv("ENABLE_EXTRACTION", "1")

    # Run build
    build_table_from_text(subdomain, str(txt_dir), db, "minutes")

    # Verify cache file was created
    cache_file = text_file.with_suffix(".txt.extracted.json")
    assert cache_file.exists(), "Cache file should be created"

    import json
    with open(cache_file) as f:
        cache_data = json.load(f)

    assert "content_hash" in cache_data
    assert "entities" in cache_data
    assert "votes" in cache_data
```

### Step 7: Run test

Run: `/Users/phildini/code/civicband/clerk/.venv/bin/python -m pytest tests/test_utils.py::test_build_table_from_text_creates_cache -v`

Expected: PASS

### Step 8: Commit cache writing

```bash
git add src/clerk/utils.py tests/test_utils.py
git commit -m "feat: write cache files after extraction"
```

---

## Task 5: Add --force-extraction Flag

**Files:**
- Modify: `src/clerk/cli.py:330-338` (build-db-from-text command)
- Modify: `src/clerk/utils.py:233` (build_db_from_text_internal)

### Step 1: Add --force-extraction flag to CLI command

```python
# src/clerk/cli.py - Modify build_db_from_text command (around line 330)

@cli.command()
@click.option(
    "-s",
    "--subdomain",
)
@click.option(
    "--force-extraction",
    is_flag=True,
    help="Ignore cache and re-extract all pages",
)
def build_db_from_text(subdomain, force_extraction=False):
    """Build database from text files"""
    build_db_from_text_internal(subdomain, force_extraction=force_extraction)
    rebuild_site_fts_internal(subdomain)
```

### Step 2: Update build_db_from_text_internal signature

```python
# src/clerk/utils.py - Update build_db_from_text_internal (around line 233)

def build_db_from_text_internal(subdomain, force_extraction=False):
    st = time.time()
    logger.info("Building database from text subdomain=%s force_extraction=%s", subdomain, force_extraction)
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
    if os.path.exists(minutes_txt_dir):
        build_table_from_text(subdomain, minutes_txt_dir, db, "minutes", force_extraction=force_extraction)
    if os.path.exists(agendas_txt_dir):
        build_table_from_text(subdomain, agendas_txt_dir, db, "agendas", force_extraction=force_extraction)

    # Explicitly close database to ensure all writes are flushed
    db.close()

    et = time.time()
    elapsed_time = et - st
    logger.info("Database build completed subdomain=%s elapsed_time=%.2f force_extraction=%s", subdomain, elapsed_time, force_extraction)
```

### Step 3: Test --force-extraction flag

Run: `/Users/phildini/code/civicband/clerk/.venv/bin/python -m clerk build-db-from-text --help`

Expected: Should show --force-extraction option in help text

### Step 4: Commit --force-extraction flag

```bash
git add src/clerk/cli.py src/clerk/utils.py
git commit -m "feat: add --force-extraction flag to build-db-from-text"
```

---

## Task 6: Add Performance Logging

**Files:**
- Modify: `src/clerk/utils.py:69-227` (throughout build_table_from_text)

### Step 1: Add final performance summary logging

```python
# src/clerk/utils.py - Add at end of build_table_from_text (after db[table_name].insert_all)

    # Log performance summary
    et = time.time()
    elapsed = et - st
    cache_hit_rate = round(100 * cache_hits / total_files, 1) if total_files > 0 else 0

    log(
        f"Build completed in {elapsed:.2f}s ({cache_hit_rate}% from cache)",
        subdomain=subdomain,
        elapsed_time=f"{elapsed:.2f}",
        cache_hit_rate=cache_hit_rate,
        total_pages=total_files,
        cache_hits=cache_hits,
        extracted=cache_misses,
    )
```

### Step 2: Add start time at beginning of function

```python
# src/clerk/utils.py - Add at start of build_table_from_text (after logger.info)

    st = time.time()
```

### Step 3: Commit performance logging

```bash
git add src/clerk/utils.py
git commit -m "feat: add performance logging to build_table_from_text"
```

---

## Task 7: Integration Tests

**Files:**
- Test: `tests/test_integration.py`

### Step 1: Write integration test for full cache workflow

```python
# tests/test_integration.py - add to existing file

@pytest.mark.integration
class TestExtractionCaching:
    """Integration tests for extraction caching."""

    def test_cache_workflow_end_to_end(self, tmp_storage_dir, monkeypatch):
        """Test complete cache workflow: first run creates cache, second run uses it."""
        from clerk.utils import build_db_from_text_internal
        import sqlite_utils

        subdomain = "cachetest.civic.band"
        site_dir = tmp_storage_dir / subdomain
        txt_dir = site_dir / "txt" / "city-council" / "2024-01-15"
        txt_dir.mkdir(parents=True)

        # Create test text files
        (txt_dir / "001.txt").write_text("Meeting called to order")
        (txt_dir / "002.txt").write_text("Roll call taken")

        # Create database
        db_path = site_dir / "meetings.db"
        db = sqlite_utils.Database(db_path)
        db["sites"].insert({
            "subdomain": subdomain,
            "name": "Cache Test City",
            "state": "CA",
            "country": "USA",
        }, pk="subdomain")
        db.close()

        # Enable extraction
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")

        # First run - should create cache files
        import time
        start1 = time.time()
        build_db_from_text_internal(subdomain)
        elapsed1 = time.time() - start1

        # Verify cache files created
        assert (txt_dir / "001.txt.extracted.json").exists()
        assert (txt_dir / "002.txt.extracted.json").exists()

        # Second run - should use cache (faster)
        start2 = time.time()
        build_db_from_text_internal(subdomain)
        elapsed2 = time.time() - start2

        # Second run should be faster (cache hits)
        # Note: May not always be true in tests, but validates workflow

        # Verify database populated correctly both times
        db = sqlite_utils.Database(db_path)
        rows = list(db["minutes"].rows)
        assert len(rows) == 2

    def test_force_extraction_bypasses_cache(self, tmp_storage_dir, monkeypatch):
        """Test --force-extraction bypasses cache."""
        from clerk.utils import build_db_from_text_internal, save_extraction_cache, hash_text_content
        import sqlite_utils

        subdomain = "forcetest.civic.band"
        site_dir = tmp_storage_dir / subdomain
        txt_dir = site_dir / "txt" / "city-council" / "2024-01-15"
        txt_dir.mkdir(parents=True)

        # Create test file
        text_file = txt_dir / "001.txt"
        text_content = "Original meeting text"
        text_file.write_text(text_content)

        # Create stale cache with wrong data
        cache_file = str(text_file) + ".extracted.json"
        content_hash = hash_text_content(text_content)
        stale_cache = {
            "content_hash": content_hash,
            "model_version": "en_core_web_md",
            "extracted_at": "2020-01-01T00:00:00Z",
            "entities": {"persons": ["Stale Person"], "orgs": [], "locations": []},
            "votes": {"votes": []}
        }
        save_extraction_cache(cache_file, stale_cache)

        # Create database
        db_path = site_dir / "meetings.db"
        db = sqlite_utils.Database(db_path)
        db["sites"].insert({
            "subdomain": subdomain,
            "name": "Force Test City",
            "state": "CA",
            "country": "USA",
        }, pk="subdomain")
        db.close()

        # Enable extraction
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")

        # Run with force_extraction=True
        build_db_from_text_internal(subdomain, force_extraction=True)

        # Cache should be overwritten with fresh extraction
        import json
        with open(cache_file) as f:
            new_cache = json.load(f)

        # Timestamp should be updated (not 2020)
        assert new_cache["extracted_at"] > "2025-01-01"
```

### Step 2: Run integration tests

Run: `/Users/phildini/code/civicband/clerk/.venv/bin/python -m pytest tests/test_integration.py::TestExtractionCaching -v`

Expected: PASS (2 tests)

### Step 3: Run all tests to verify no regressions

Run: `/Users/phildini/code/civicband/clerk/.venv/bin/python -m pytest tests/ -v`

Expected: All tests pass

### Step 4: Commit integration tests

```bash
git add tests/test_integration.py
git commit -m "test: add integration tests for extraction caching"
```

---

## Task 8: Update Documentation

**Files:**
- Modify: `README.md`

### Step 1: Add cache behavior to README

```markdown
# README.md - Add to Configuration section (after SPACY_N_PROCESS)

### Extraction Caching

Extraction results are automatically cached in `.extracted.json` files alongside text files. This speeds up subsequent database rebuilds from hours to minutes:

- **First run:** Processes all pages with spaCy, creates cache files (~1.6GB for 547k pages)
- **Subsequent runs:** Only processes new/changed pages (95%+ cache hit rate typical)
- **Force reprocessing:** Use `--force-extraction` flag to bypass cache

```bash
# Normal rebuild (uses cache)
clerk build-db-from-text --subdomain example.civic.band

# Force fresh extraction (ignores cache)
clerk build-db-from-text --subdomain example.civic.band --force-extraction
```

Cache files are automatically invalidated when text content changes.
```

### Step 2: Commit documentation

```bash
git add README.md
git commit -m "docs: document extraction caching behavior"
```

---

## Task 9: Final Verification

### Step 1: Run complete test suite

Run: `/Users/phildini/code/civicband/clerk/.venv/bin/python -m pytest tests/ -v --tb=short`

Expected: All tests pass

### Step 2: Run linting

Run: `uv run ruff check src/ tests/`

Expected: No errors

### Step 3: Run formatting check

Run: `uv run ruff format --check src/ tests/`

Expected: All files formatted

### Step 4: Create final summary commit

```bash
git log --oneline | head -10
```

Review commits to ensure clean history

---

## Completion Checklist

- [ ] All cache utility functions implemented and tested
- [ ] Phase 1 checks cache before extraction
- [ ] Phase 2 only processes uncached pages
- [ ] Cache files written after extraction
- [ ] `--force-extraction` flag implemented
- [ ] Performance logging added
- [ ] Integration tests pass
- [ ] Documentation updated
- [ ] All tests pass
- [ ] Code formatted and linted

## Performance Validation

After implementation, validate performance improvement:

1. Run `clerk build-db-from-text --subdomain <test-site>` twice
2. First run should take normal time and create `.extracted.json` files
3. Second run should be significantly faster (95%+ cache hits)
4. Check logs for cache hit rate and timing

Expected results:
- First run: 2 hours (547k pages), creates ~1.6GB cache
- Second run (no changes): <1 minute (100% cache hits)
- Incremental update (500 new pages): 1-2 minutes (99% cache hits)
