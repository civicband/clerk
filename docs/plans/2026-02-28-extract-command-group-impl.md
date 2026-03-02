# Extract Command Group Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rework entity/vote extraction into a standalone `clerk extract` command group, remove inline extraction from DB compilation, and clean up dormant pipeline code.

**Architecture:** New `extract_cli.py` module with click command group (following `etl.py` pattern). Extraction orchestration moves out of `utils.py`. DB compilation (`build_table_from_text`) becomes a pure data-assembly step that reads cached extraction results but never runs extraction itself.

**Tech Stack:** Python, Click, spaCy, SQLite (sqlite_utils), SQLAlchemy

---

### Task 1: Create `extract_cli.py` with command group skeleton

**Files:**
- Create: `src/clerk/extract_cli.py`
- Test: `tests/test_extract_cli.py`

**Step 1: Write the failing test**

```python
"""Tests for clerk.extract_cli module."""

from click.testing import CliRunner

from clerk.extract_cli import extract


class TestExtractCommandGroup:
    """Tests for the extract command group."""

    def test_extract_group_exists(self):
        """The extract command group should exist."""
        runner = CliRunner()
        result = runner.invoke(extract, ["--help"])
        assert result.exit_code == 0
        assert "entities" in result.output
        assert "votes" in result.output
        assert "all" in result.output

    def test_entities_subcommand_requires_subdomain_or_next_site(self):
        """entities subcommand should error without --subdomain or --next-site."""
        runner = CliRunner()
        result = runner.invoke(extract, ["entities"])
        assert result.exit_code != 0

    def test_votes_subcommand_requires_subdomain_or_next_site(self):
        """votes subcommand should error without --subdomain or --next-site."""
        runner = CliRunner()
        result = runner.invoke(extract, ["votes"])
        assert result.exit_code != 0

    def test_all_subcommand_requires_subdomain_or_next_site(self):
        """all subcommand should error without --subdomain or --next-site."""
        runner = CliRunner()
        result = runner.invoke(extract, ["all"])
        assert result.exit_code != 0
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/phildini/code/civicband/clerk && python -m pytest tests/test_extract_cli.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

**Step 3: Write minimal implementation**

Create `src/clerk/extract_cli.py`:

```python
"""CLI commands for entity and vote extraction.

Provides the `clerk extract` command group with subcommands:
- entities: Extract persons, orgs, locations
- votes: Extract vote records
- all: Run both entity and vote extraction
"""

import click


@click.group()
def extract():
    """Extract entities and votes from site text files."""
    pass


def _validate_site_args(subdomain, next_site):
    """Validate that either --subdomain or --next-site is provided."""
    if not subdomain and not next_site:
        raise click.UsageError("Must specify --subdomain or --next-site")


@extract.command()
@click.option("-s", "--subdomain", help="Site subdomain to extract from")
@click.option("-n", "--next-site", is_flag=True, help="Auto-select next site needing extraction")
@click.option("--rebuild", is_flag=True, help="Ignore cache and re-extract everything")
def entities(subdomain, next_site, rebuild):
    """Extract entities (persons, orgs, locations) from site text files."""
    _validate_site_args(subdomain, next_site)
    click.echo(f"Entity extraction: subdomain={subdomain}, next_site={next_site}, rebuild={rebuild}")


@extract.command()
@click.option("-s", "--subdomain", help="Site subdomain to extract from")
@click.option("-n", "--next-site", is_flag=True, help="Auto-select next site needing extraction")
@click.option("--rebuild", is_flag=True, help="Ignore cache and re-extract everything")
def votes(subdomain, next_site, rebuild):
    """Extract vote records from site text files."""
    _validate_site_args(subdomain, next_site)
    click.echo(f"Vote extraction: subdomain={subdomain}, next_site={next_site}, rebuild={rebuild}")


@extract.command(name="all")
@click.option("-s", "--subdomain", help="Site subdomain to extract from")
@click.option("-n", "--next-site", is_flag=True, help="Auto-select next site needing extraction")
@click.option("--rebuild", is_flag=True, help="Ignore cache and re-extract everything")
def all_(subdomain, next_site, rebuild):
    """Extract both entities and votes from site text files."""
    _validate_site_args(subdomain, next_site)
    click.echo(f"Full extraction: subdomain={subdomain}, next_site={next_site}, rebuild={rebuild}")
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/phildini/code/civicband/clerk && python -m pytest tests/test_extract_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/extract_cli.py tests/test_extract_cli.py
git commit -m "Add extract command group skeleton with entities, votes, all subcommands"
```

---

### Task 2: Register extract group in cli.py and remove old commands

**Files:**
- Modify: `src/clerk/cli.py`

**Step 1: Add import and register extract group**

In `cli.py`, add to imports (around line 32):
```python
from .extract_cli import extract
```

At the bottom (around line 2090), add:
```python
cli.add_command(extract)
```

**Step 2: Remove old extract-entities command**

Remove the `extract_entities` function (lines 470-475), the `extract_entities_internal` function (lines 478-576), and the `cli.add_command(extract_entities)` line (line 2087).

**Step 3: Remove fix-extraction-stage command**

Remove the `fix_extraction_stage` function (lines 2010-2081).

**Step 4: Remove --extract-entities and --ignore-cache from build-db-from-text**

Simplify `build_db_from_text` command (lines 384-411): remove the two `@click.option` decorators for `--extract-entities` and `--ignore-cache`, update the function signature and body to not pass those args.

**Step 5: Run tests**

Run: `cd /Users/phildini/code/civicband/clerk && python -m pytest tests/ -v -k "not test_spacy" --timeout=30`
Expected: PASS (existing tests should still pass)

**Step 6: Commit**

```bash
git add src/clerk/cli.py
git commit -m "Register extract group, remove old extract-entities and fix-extraction-stage commands"
```

---

### Task 3: Implement extraction orchestration in extract_cli.py

**Files:**
- Modify: `src/clerk/extract_cli.py`
- Test: `tests/test_extract_cli.py`

**Step 1: Write tests for extraction orchestration**

Add to `tests/test_extract_cli.py`:

```python
import json
import os
from unittest.mock import MagicMock, patch


class TestRunExtraction:
    """Tests for the extraction orchestration logic."""

    def test_run_extraction_entities_only_creates_cache(self, tmp_path):
        """Extracting entities only should cache entities, leave votes empty."""
        from clerk.extract_cli import _run_extraction_for_site

        # Set up text file structure
        meeting_dir = tmp_path / "txt" / "city-council" / "2024-01-15"
        meeting_dir.mkdir(parents=True)
        (meeting_dir / "0001.txt").write_text("Mayor Smith called the meeting to order.")

        with patch("clerk.extract_cli.EXTRACTION_ENABLED", True), \
             patch("clerk.extract_cli.extract_entities") as mock_extract, \
             patch("clerk.extract_cli.get_nlp") as mock_nlp:
            mock_nlp.return_value = MagicMock()
            mock_nlp.return_value.pipe = MagicMock(return_value=[MagicMock()])
            mock_extract.return_value = {"persons": [{"name": "Smith"}], "orgs": [], "locations": []}

            _run_extraction_for_site(
                subdomain="test-site",
                txt_dir=str(tmp_path / "txt"),
                mode="entities",
                rebuild=False,
            )

        # Check cache file was created
        cache_file = meeting_dir / "0001.txt.extracted.json"
        assert cache_file.exists()
        cache_data = json.loads(cache_file.read_text())
        assert "entities" in cache_data
        assert cache_data["entities"]["persons"][0]["name"] == "Smith"

    def test_run_extraction_votes_only_creates_cache(self, tmp_path):
        """Extracting votes only should cache votes, leave entities empty."""
        from clerk.extract_cli import _run_extraction_for_site

        meeting_dir = tmp_path / "txt" / "city-council" / "2024-01-15"
        meeting_dir.mkdir(parents=True)
        (meeting_dir / "0001.txt").write_text("Motion passed 5-2.")

        with patch("clerk.extract_cli.EXTRACTION_ENABLED", True), \
             patch("clerk.extract_cli.extract_votes") as mock_votes, \
             patch("clerk.extract_cli.get_nlp") as mock_nlp:
            mock_nlp.return_value = MagicMock()
            mock_nlp.return_value.pipe = MagicMock(return_value=[MagicMock()])
            mock_votes.return_value = {"votes": [{"result": "passed", "tally": {"ayes": 5, "nays": 2}}]}

            _run_extraction_for_site(
                subdomain="test-site",
                txt_dir=str(tmp_path / "txt"),
                mode="votes",
                rebuild=False,
            )

        cache_file = meeting_dir / "0001.txt.extracted.json"
        assert cache_file.exists()
        cache_data = json.loads(cache_file.read_text())
        assert "votes" in cache_data
        assert cache_data["votes"]["votes"][0]["result"] == "passed"

    def test_run_extraction_rebuild_ignores_existing_cache(self, tmp_path):
        """--rebuild should ignore existing cache and re-extract."""
        from clerk.extract_cli import _run_extraction_for_site

        meeting_dir = tmp_path / "txt" / "city-council" / "2024-01-15"
        meeting_dir.mkdir(parents=True)
        text = "Mayor Smith called the meeting to order."
        (meeting_dir / "0001.txt").write_text(text)

        # Create existing cache
        from clerk.utils import hash_text_content
        cache_file = meeting_dir / "0001.txt.extracted.json"
        cache_file.write_text(json.dumps({
            "content_hash": hash_text_content(text),
            "entities": {"persons": [{"name": "Old"}], "orgs": [], "locations": []},
            "votes": {"votes": []},
        }))

        with patch("clerk.extract_cli.EXTRACTION_ENABLED", True), \
             patch("clerk.extract_cli.extract_entities") as mock_extract, \
             patch("clerk.extract_cli.get_nlp") as mock_nlp:
            mock_nlp.return_value = MagicMock()
            mock_nlp.return_value.pipe = MagicMock(return_value=[MagicMock()])
            mock_extract.return_value = {"persons": [{"name": "New"}], "orgs": [], "locations": []}

            _run_extraction_for_site(
                subdomain="test-site",
                txt_dir=str(tmp_path / "txt"),
                mode="entities",
                rebuild=True,
            )

        cache_data = json.loads(cache_file.read_text())
        assert cache_data["entities"]["persons"][0]["name"] == "New"

    def test_run_extraction_preserves_other_section_in_cache(self, tmp_path):
        """Extracting entities only should preserve existing votes in cache."""
        from clerk.extract_cli import _run_extraction_for_site

        meeting_dir = tmp_path / "txt" / "city-council" / "2024-01-15"
        meeting_dir.mkdir(parents=True)
        text = "Mayor Smith called the meeting to order."
        (meeting_dir / "0001.txt").write_text(text)

        # Create existing cache with votes
        from clerk.utils import hash_text_content
        cache_file = meeting_dir / "0001.txt.extracted.json"
        cache_file.write_text(json.dumps({
            "content_hash": hash_text_content(text),
            "entities": {"persons": [], "orgs": [], "locations": []},
            "votes": {"votes": [{"result": "passed"}]},
        }))

        with patch("clerk.extract_cli.EXTRACTION_ENABLED", True), \
             patch("clerk.extract_cli.extract_entities") as mock_extract, \
             patch("clerk.extract_cli.get_nlp") as mock_nlp:
            mock_nlp.return_value = MagicMock()
            mock_nlp.return_value.pipe = MagicMock(return_value=[MagicMock()])
            mock_extract.return_value = {"persons": [{"name": "Smith"}], "orgs": [], "locations": []}

            _run_extraction_for_site(
                subdomain="test-site",
                txt_dir=str(tmp_path / "txt"),
                mode="entities",
                rebuild=False,
            )

        cache_data = json.loads(cache_file.read_text())
        # Entities should be updated
        assert cache_data["entities"]["persons"][0]["name"] == "Smith"
        # Votes should be preserved from existing cache
        assert cache_data["votes"]["votes"][0]["result"] == "passed"
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/phildini/code/civicband/clerk && python -m pytest tests/test_extract_cli.py::TestRunExtraction -v`
Expected: FAIL with `ImportError` (no `_run_extraction_for_site`)

**Step 3: Implement `_run_extraction_for_site` in extract_cli.py**

Add to `src/clerk/extract_cli.py`:

```python
import datetime
import json
import os

import click

from .extraction import (
    EXTRACTION_ENABLED,
    extract_entities as _extract_entities,
    extract_votes as _extract_votes,
    get_nlp,
)
from .output import log
from .utils import (
    collect_page_files,
    hash_text_content,
    load_extraction_cache,
    save_extraction_cache,
)

STORAGE_DIR = os.environ.get("STORAGE_DIR", "../sites")


def _resolve_subdomain(subdomain, next_site):
    """Resolve subdomain from --subdomain or --next-site flag."""
    if next_site:
        from sqlalchemy import text as sql_text
        from .utils import assert_db_exists

        engine = assert_db_exists()
        with engine.connect() as conn:
            row = conn.execute(
                sql_text("""
                    SELECT subdomain FROM sites
                    WHERE extraction_status IN ('pending', 'failed')
                    ORDER BY last_extracted ASC NULLS FIRST
                    LIMIT 1
                """)
            ).fetchone()

            if not row:
                log("No sites need extraction")
                return None
            subdomain = row[0]
            log(f"Selected next site: {subdomain}")

    return subdomain


def _run_extraction_for_site(subdomain, txt_dir, mode, rebuild):
    """Run extraction on all text files for a site.

    Args:
        subdomain: Site subdomain
        txt_dir: Path to text directory
        mode: "entities", "votes", or "all"
        rebuild: If True, ignore existing cache
    """
    if not EXTRACTION_ENABLED:
        log("Extraction disabled (set ENABLE_EXTRACTION=1)", level="warning")
        return

    page_files = collect_page_files(txt_dir)
    if not page_files:
        log("No text files found", subdomain=subdomain)
        return

    # Determine which pages need extraction
    pages_to_extract = []
    existing_caches = {}

    for pf in page_files:
        cache_file = os.path.join(
            txt_dir, pf.meeting, pf.date, f"{pf.page_num:04d}.txt.extracted.json"
        )
        content_hash = hash_text_content(pf.text)

        if not rebuild:
            cached = load_extraction_cache(cache_file, content_hash)
            if cached:
                # Check if the specific mode section already exists
                if mode == "entities" and cached.get("entities", {}).get("persons") is not None:
                    existing_caches[cache_file] = cached
                    continue
                elif mode == "votes" and cached.get("votes", {}).get("votes") is not None:
                    existing_caches[cache_file] = cached
                    continue
                elif mode == "all" and cached.get("entities") and cached.get("votes"):
                    existing_caches[cache_file] = cached
                    continue
                else:
                    existing_caches[cache_file] = cached

        pages_to_extract.append((pf, cache_file, content_hash))

    if not pages_to_extract:
        log("All pages already cached", subdomain=subdomain)
        return

    log(
        f"Extracting {len(pages_to_extract)} pages ({len(existing_caches)} cached)",
        subdomain=subdomain,
    )

    # Batch parse with spaCy
    nlp = get_nlp()
    texts = [pf.text for pf, _, _ in pages_to_extract]

    if nlp:
        n_process = int(os.environ.get("SPACY_N_PROCESS", "1"))
        pipe_kwargs = {"batch_size": 500}
        if n_process > 1:
            pipe_kwargs["n_process"] = n_process
        docs = list(nlp.pipe(texts, **pipe_kwargs))
    else:
        docs = [None] * len(texts)

    # Extract and cache
    for i, (pf, cache_file, content_hash) in enumerate(pages_to_extract):
        doc = docs[i]
        existing = existing_caches.get(cache_file, {})

        # Extract based on mode
        entities = existing.get("entities", {"persons": [], "orgs": [], "locations": []})
        votes_data = existing.get("votes", {"votes": []})

        if mode in ("entities", "all"):
            try:
                entities = _extract_entities(pf.text, doc=doc)
            except Exception as e:
                log(f"Entity extraction failed: {e}", subdomain=subdomain, level="warning")
                entities = {"persons": [], "orgs": [], "locations": []}

        if mode in ("votes", "all"):
            try:
                votes_data = _extract_votes(pf.text, doc=doc)
            except Exception as e:
                log(f"Vote extraction failed: {e}", subdomain=subdomain, level="warning")
                votes_data = {"votes": []}

        cache_data = {
            "content_hash": content_hash,
            "extracted_at": datetime.datetime.now().isoformat(),
            "entities": entities,
            "votes": votes_data,
        }
        save_extraction_cache(cache_file, cache_data)

    log(f"Extraction complete: {len(pages_to_extract)} pages processed", subdomain=subdomain)
```

Then update the subcommand implementations to call `_run_extraction_for_site`:

```python
@extract.command()
@click.option("-s", "--subdomain", help="Site subdomain to extract from")
@click.option("-n", "--next-site", is_flag=True, help="Auto-select next site needing extraction")
@click.option("--rebuild", is_flag=True, help="Ignore cache and re-extract everything")
def entities(subdomain, next_site, rebuild):
    """Extract entities (persons, orgs, locations) from site text files."""
    _validate_site_args(subdomain, next_site)
    subdomain = _resolve_subdomain(subdomain, next_site)
    if not subdomain:
        return

    txt_dir = f"{STORAGE_DIR}/{subdomain}/txt"
    _run_extraction_for_site(subdomain, txt_dir, mode="entities", rebuild=rebuild)


@extract.command()
@click.option("-s", "--subdomain", help="Site subdomain to extract from")
@click.option("-n", "--next-site", is_flag=True, help="Auto-select next site needing extraction")
@click.option("--rebuild", is_flag=True, help="Ignore cache and re-extract everything")
def votes(subdomain, next_site, rebuild):
    """Extract vote records from site text files."""
    _validate_site_args(subdomain, next_site)
    subdomain = _resolve_subdomain(subdomain, next_site)
    if not subdomain:
        return

    txt_dir = f"{STORAGE_DIR}/{subdomain}/txt"
    _run_extraction_for_site(subdomain, txt_dir, mode="votes", rebuild=rebuild)


@extract.command(name="all")
@click.option("-s", "--subdomain", help="Site subdomain to extract from")
@click.option("-n", "--next-site", is_flag=True, help="Auto-select next site needing extraction")
@click.option("--rebuild", is_flag=True, help="Ignore cache and re-extract everything")
def all_(subdomain, next_site, rebuild):
    """Extract both entities and votes from site text files."""
    _validate_site_args(subdomain, next_site)
    subdomain = _resolve_subdomain(subdomain, next_site)
    if not subdomain:
        return

    txt_dir = f"{STORAGE_DIR}/{subdomain}/txt"
    _run_extraction_for_site(subdomain, txt_dir, mode="all", rebuild=rebuild)
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/phildini/code/civicband/clerk && python -m pytest tests/test_extract_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/extract_cli.py tests/test_extract_cli.py
git commit -m "Implement extraction orchestration in extract_cli.py"
```

---

### Task 4: Simplify `build_table_from_text` in utils.py

**Files:**
- Modify: `src/clerk/utils.py`
- Test: `tests/test_utils_refactor.py` (or add to existing `tests/test_utils.py`)

**Step 1: Write test for simplified build_table_from_text**

Add to `tests/test_utils.py`:

```python
class TestBuildTableFromTextSimplified:
    """Tests for simplified build_table_from_text (no inline extraction)."""

    def test_includes_cached_entities_when_available(self, tmp_path):
        """build_table_from_text should include cached extraction data."""
        from clerk.utils import build_table_from_text, hash_text_content

        # Set up text file
        meeting_dir = tmp_path / "txt" / "city-council" / "2024-01-15"
        meeting_dir.mkdir(parents=True)
        text = "Mayor Smith called the meeting to order."
        (meeting_dir / "0001.txt").write_text(text)

        # Set up cache file
        cache_data = {
            "content_hash": hash_text_content(text),
            "entities": {"persons": [{"name": "Smith"}], "orgs": [], "locations": []},
            "votes": {"votes": [{"result": "passed"}]},
        }
        (meeting_dir / "0001.txt.extracted.json").write_text(json.dumps(cache_data))

        # Build table
        db = sqlite_utils.Database(":memory:")
        db["minutes"].create({"id": str, "meeting": str, "date": str, "page": int, "text": str, "page_image": str, "entities_json": str, "votes_json": str}, pk="id")

        import os
        old_storage = os.environ.get("STORAGE_DIR")
        os.environ["STORAGE_DIR"] = str(tmp_path.parent)

        build_table_from_text(
            subdomain=tmp_path.name,
            txt_dir=str(tmp_path / "txt"),
            db=db,
            table_name="minutes",
        )

        if old_storage:
            os.environ["STORAGE_DIR"] = old_storage

        rows = list(db["minutes"].rows)
        assert len(rows) == 1
        entities = json.loads(rows[0]["entities_json"])
        assert entities["persons"][0]["name"] == "Smith"

    def test_empty_entities_when_no_cache(self, tmp_path):
        """build_table_from_text should use empty entities when no cache exists."""
        from clerk.utils import build_table_from_text

        meeting_dir = tmp_path / "txt" / "city-council" / "2024-01-15"
        meeting_dir.mkdir(parents=True)
        (meeting_dir / "0001.txt").write_text("Some meeting text.")

        db = sqlite_utils.Database(":memory:")
        db["minutes"].create({"id": str, "meeting": str, "date": str, "page": int, "text": str, "page_image": str, "entities_json": str, "votes_json": str}, pk="id")

        import os
        old_storage = os.environ.get("STORAGE_DIR")
        os.environ["STORAGE_DIR"] = str(tmp_path.parent)

        build_table_from_text(
            subdomain=tmp_path.name,
            txt_dir=str(tmp_path / "txt"),
            db=db,
            table_name="minutes",
        )

        if old_storage:
            os.environ["STORAGE_DIR"] = old_storage

        rows = list(db["minutes"].rows)
        assert len(rows) == 1
        entities = json.loads(rows[0]["entities_json"])
        assert entities == {"persons": [], "orgs": [], "locations": []}
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/phildini/code/civicband/clerk && python -m pytest tests/test_utils.py::TestBuildTableFromTextSimplified -v`
Expected: FAIL (signature mismatch or wrong behavior)

**Step 3: Simplify `build_table_from_text` and `build_db_from_text_internal`**

In `src/clerk/utils.py`:

1. Remove `extract_entities` and `ignore_cache` params from `build_table_from_text` signature
2. Remove Phase 2 (batch spaCy parsing) entirely
3. Simplify Phase 3: if cached, use cached data; otherwise empty entities/votes (no extraction path)
4. Remove `extract_entities` and `ignore_cache` params from `build_db_from_text_internal`
5. Remove the import of `extract_entities`, `extract_votes`, `get_nlp`, `update_context`, `detect_roll_call` from extraction module (keep `EXTRACTION_ENABLED` if needed, or remove too)
6. Remove `batch_parse_with_spacy`, `process_page_for_db`, `extract_and_cache` functions (no longer used by utils.py)
7. Keep `collect_page_files`, `hash_text_content`, `load_extraction_cache`, `save_extraction_cache`, `group_pages_by_meeting_date`, `PageFile`, `MeetingDateGroup`, `PageData` dataclasses

The simplified `build_table_from_text` should look like:

```python
def build_table_from_text(subdomain, txt_dir, db, table_name, municipality=None):
    """Build database table from text files, including cached extraction data.

    Reads .extracted.json cache files if they exist alongside text files.
    Does NOT run extraction - use `clerk extract` commands for that.
    """
    st = time.time()
    log(f"Building table from text table_name={table_name}", subdomain=subdomain)

    page_files = collect_page_files(txt_dir)
    if not page_files:
        return

    if table_name == "agendas":
        for pf in page_files:
            pf.page_image_path = f"/_agendas{pf.page_image_path}"

    # Check cache for all pages
    storage_dir = os.environ.get("STORAGE_DIR", "../sites")
    base_txt_dir = f"{storage_dir}/{subdomain}"
    if table_name == "agendas":
        base_txt_dir = f"{base_txt_dir}/_agendas"
    base_txt_dir = f"{base_txt_dir}/txt"

    entries = []
    cache_hits = 0

    for meeting_group in group_pages_by_meeting_date(page_files):
        if meeting_group.meeting != getattr(build_table_from_text, "_last_meeting", None):
            click.echo(click.style(subdomain, fg="cyan") + f": Processing {meeting_group.meeting}")
            build_table_from_text._last_meeting = meeting_group.meeting

        for idx in meeting_group.page_indices:
            pf = page_files[idx]

            # Check for cached extraction data
            cache_file = f"{base_txt_dir}/{pf.meeting}/{pf.date}/{pf.page_num:04d}.txt.extracted.json"
            content_hash = hash_text_content(pf.text)
            cached = load_extraction_cache(cache_file, content_hash)

            if cached:
                cache_hits += 1
                entities_json = json.dumps(cached["entities"])
                votes_json = json.dumps(cached["votes"])
            else:
                entities_json = json.dumps({"persons": [], "orgs": [], "locations": []})
                votes_json = json.dumps({"votes": []})

            # Build database entry
            key_hash = {
                "kind": "minutes" if table_name != "agendas" else "agenda",
                "meeting": pf.meeting,
                "date": pf.date,
                "page": pf.page_num,
                "text": pf.text,
            }
            if municipality:
                key_hash.update({"subdomain": subdomain, "municipality": municipality})

            key = sha256(json.dumps(key_hash, sort_keys=True).encode("utf-8")).hexdigest()[:12]

            entry = {
                "id": key,
                "meeting": pf.meeting,
                "date": pf.date,
                "page": pf.page_num,
                "text": pf.text,
                "page_image": pf.page_image_path,
                "entities_json": entities_json,
                "votes_json": votes_json,
            }
            if municipality:
                entry["subdomain"] = subdomain
                entry["municipality"] = municipality

            entries.append(entry)

    db[table_name].insert_all(entries)

    et = time.time()
    log(
        f"Build completed in {et - st:.2f}s ({cache_hits} cached extractions included)",
        subdomain=subdomain,
        total_pages=len(page_files),
        cache_hits=cache_hits,
    )
```

And simplified `build_db_from_text_internal`:

```python
def build_db_from_text_internal(subdomain):
    st = time.time()
    log("Building database from text", subdomain=subdomain)
    minutes_txt_dir = f"{STORAGE_DIR}/{subdomain}/txt"
    agendas_txt_dir = f"{STORAGE_DIR}/{subdomain}/_agendas/txt"
    database = f"{STORAGE_DIR}/{subdomain}/meetings.db"
    db_backup = f"{STORAGE_DIR}/{subdomain}/meetings.db.bk"
    shutil.copy(database, db_backup)
    os.remove(database)
    db = sqlite_utils.Database(database)
    create_meetings_schema(db)
    if os.path.exists(minutes_txt_dir):
        build_table_from_text(subdomain, minutes_txt_dir, db, "minutes")
    if os.path.exists(agendas_txt_dir):
        build_table_from_text(subdomain, agendas_txt_dir, db, "agendas")
    db.close()

    et = time.time()
    log(f"Database build completed elapsed_time={et - st:.2f}", subdomain=subdomain)
    click.echo(f"Execution time: {et - st} seconds")
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/phildini/code/civicband/clerk && python -m pytest tests/test_utils.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/utils.py tests/test_utils.py
git commit -m "Simplify build_table_from_text to read-only cache, remove inline extraction"
```

---

### Task 5: Clean up workers.py

**Files:**
- Modify: `src/clerk/workers.py`

**Step 1: Remove extraction_job function**

Remove the `extraction_job` function (lines 966-1049+).

**Step 2: Clean up ocr_complete_coordinator**

Remove the commented-out extraction queue code (lines 694, 718-736). Remove `extraction_total=1` from the progress update (line 670).

**Step 3: Update db_compilation_job signature**

Remove `extract_entities` and `ignore_cache` params from `db_compilation_job` (line 763). Update the call to `build_db_from_text_internal` to not pass those args. Update the logging that references those params.

**Step 4: Clean up references**

Search for any remaining references to `extract_entities_internal`, `extraction_job`, `get_extraction_queue` in workers.py and remove them.

**Step 5: Run tests**

Run: `cd /Users/phildini/code/civicband/clerk && python -m pytest tests/ -v -k "not test_spacy" --timeout=30`
Expected: PASS

**Step 6: Commit**

```bash
git add src/clerk/workers.py
git commit -m "Remove dormant extraction pipeline code from workers.py"
```

---

### Task 6: Final integration test and cleanup

**Files:**
- All modified files

**Step 1: Run full test suite**

Run: `cd /Users/phildini/code/civicband/clerk && python -m pytest tests/ -v --timeout=60`
Expected: PASS

**Step 2: Verify CLI help output**

Run: `cd /Users/phildini/code/civicband/clerk && python -m clerk --help`
Verify: `extract` group appears, old `extract-entities` and `fix-extraction-stage` do not.

Run: `cd /Users/phildini/code/civicband/clerk && python -m clerk extract --help`
Verify: Shows `entities`, `votes`, `all` subcommands.

Run: `cd /Users/phildini/code/civicband/clerk && python -m clerk extract entities --help`
Verify: Shows `--subdomain`, `--next-site`, `--rebuild` options.

Run: `cd /Users/phildini/code/civicband/clerk && python -m clerk build-db-from-text --help`
Verify: No `--extract-entities` or `--ignore-cache` flags.

**Step 3: Check for any remaining references to removed code**

Run: `grep -r "extract_entities_internal\|extraction_job\|fix.extraction.stage\|--extract-entities\|--ignore-cache" src/clerk/ --include="*.py"`
Expected: No matches (or only in comments that should be cleaned up).

**Step 4: Commit any final cleanup**

```bash
git add -A
git commit -m "Final cleanup: remove stale references to old extraction pipeline"
```
