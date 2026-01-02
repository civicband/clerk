# Sequential Extraction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Separate entity/vote extraction from database building into an independent sequential background job that processes sites one at a time with minimal memory footprint.

**Architecture:** Split `build-db-from-text` into fast database build (text only) + async `extract-entities` command. Add extraction_status/last_extracted columns to sites table for tracking. Support --subdomain and --next-site modes with CIVIC_DEV_MODE for testing.

**Tech Stack:** Python, Click, sqlite-utils, spaCy, pluggy hooks

---

### Task 1: Database Schema Migration Command

**Files:**
- Modify: `src/clerk/cli.py` (add new command)
- Test: `tests/test_cli.py` (add migration tests)

**Step 1: Write failing test for migration command**

```python
# Add to tests/test_cli.py
def test_migrate_extraction_schema_adds_columns(tmp_path, monkeypatch):
    """Migration adds extraction_status and last_extracted columns"""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    from clerk.cli import cli
    from clerk.utils import assert_db_exists

    # Create database without extraction columns
    db = assert_db_exists()

    # Run migration
    runner = CliRunner()
    result = runner.invoke(cli, ['migrate-extraction-schema'])

    assert result.exit_code == 0
    assert "Migration complete" in result.output

    # Verify columns exist
    columns = {col.name for col in db["sites"].columns}
    assert "extraction_status" in columns
    assert "last_extracted" in columns
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_migrate_extraction_schema_adds_columns -v`
Expected: FAIL with "AttributeError: module 'clerk.cli' has no attribute 'migrate_extraction_schema'"

**Step 3: Implement migrate-extraction-schema command**

```python
# Add to src/clerk/cli.py after other commands
@cli.command()
def migrate_extraction_schema():
    """Add extraction tracking columns to sites table"""
    db = assert_db_exists()

    # Add columns if they don't exist
    existing_columns = {col.name for col in db["sites"].columns}

    if "extraction_status" not in existing_columns:
        db.execute("ALTER TABLE sites ADD COLUMN extraction_status TEXT DEFAULT 'pending'")

    if "last_extracted" not in existing_columns:
        db.execute("ALTER TABLE sites ADD COLUMN last_extracted TEXT")

    # Set pending for all sites that don't have a status
    db.execute("UPDATE sites SET extraction_status = 'pending' WHERE extraction_status IS NULL")

    click.echo("Migration complete: extraction_status and last_extracted columns added")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_migrate_extraction_schema_adds_columns -v`
Expected: PASS

**Step 5: Write test for idempotency**

```python
# Add to tests/test_cli.py
def test_migrate_extraction_schema_is_idempotent(tmp_path, monkeypatch):
    """Running migration multiple times is safe"""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    from clerk.cli import cli
    from clerk.utils import assert_db_exists

    runner = CliRunner()

    # Run migration twice
    result1 = runner.invoke(cli, ['migrate-extraction-schema'])
    result2 = runner.invoke(cli, ['migrate-extraction-schema'])

    assert result1.exit_code == 0
    assert result2.exit_code == 0

    # Verify no errors and columns still exist
    db = assert_db_exists()
    columns = {col.name for col in db["sites"].columns}
    assert "extraction_status" in columns
    assert "last_extracted" in columns
```

**Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_migrate_extraction_schema_is_idempotent -v`
Expected: PASS

**Step 7: Commit**

```bash
git add src/clerk/cli.py tests/test_cli.py
git commit -m "feat: add migrate-extraction-schema command"
```

---

### Task 2: Core Extraction Function

**Files:**
- Modify: `src/clerk/utils.py` (add extract_entities_for_site function)
- Test: `tests/test_utils.py` (add extraction function tests)

**Step 1: Write failing test for extraction function**

```python
# Add to tests/test_utils.py
def test_extract_entities_for_site_updates_database(tmp_path, monkeypatch):
    """Extract entities reads text files and updates database"""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("ENABLE_EXTRACTION", "0")  # Disable actual spaCy

    from clerk.utils import extract_entities_for_site
    import sqlite_utils

    # Create site structure with text files and database
    subdomain = "test.civic.band"
    site_dir = tmp_path / subdomain
    txt_dir = site_dir / "txt"
    meeting_dir = txt_dir / "2024-01-01_Meeting"
    meeting_date_dir = meeting_dir / "2024-01-01"
    meeting_date_dir.mkdir(parents=True)

    # Write text file
    (meeting_date_dir / "0001.txt").write_text("Test meeting text")

    # Create database with empty entities_json
    db = sqlite_utils.Database(str(site_dir / "meetings.db"))
    db["minutes"].insert({
        "id": "test123",
        "meeting": "2024-01-01_Meeting",
        "date": "2024-01-01",
        "page": 1,
        "text": "Test meeting text",
        "page_image": "/path/to/image.png",
        "entities_json": "{}",
        "votes_json": "{}"
    })

    # Run extraction
    extract_entities_for_site(subdomain, force_extraction=False)

    # Verify database was updated (entities_json should still be {} since extraction disabled)
    page = list(db["minutes"].rows)[0]
    assert page["id"] == "test123"
    assert page["entities_json"] == "{}"  # Empty when ENABLE_EXTRACTION=0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_utils.py::test_extract_entities_for_site_updates_database -v`
Expected: FAIL with "NameError: name 'extract_entities_for_site' is not defined"

**Step 3: Implement extract_entities_for_site function**

```python
# Add to src/clerk/utils.py
def extract_entities_for_site(subdomain, force_extraction=False):
    """Extract entities for all pages in a site's database

    Reads existing database records, processes uncached pages with spaCy,
    and updates entities_json/votes_json columns.

    Args:
        subdomain: Site subdomain (e.g., "alameda.ca.civic.band")
        force_extraction: If True, bypass cache and re-extract all pages
    """
    from .output import log
    import sqlite_utils

    st = time.time()
    logger.info("Extracting entities subdomain=%s force_extraction=%s", subdomain, force_extraction)

    site_db_path = f"{STORAGE_DIR}/{subdomain}/meetings.db"
    db = sqlite_utils.Database(site_db_path)

    # Process both minutes and agendas
    for table_name in ["minutes", "agendas"]:
        if not db[table_name].exists():
            continue

        txt_subdir = "txt" if table_name == "minutes" else "_agendas/txt"
        txt_dir = f"{STORAGE_DIR}/{subdomain}/{txt_subdir}"

        if not os.path.exists(txt_dir):
            continue

        # Read all pages from database
        pages = list(db[table_name].rows)
        log(f"Found {len(pages)} pages in {table_name}", subdomain=subdomain)

        cache_hits = 0
        cache_misses = 0

        # For each page, check cache and extract if needed
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
                    entities = cached_extraction["entities"]
                    votes = cached_extraction["votes"]
                else:
                    cache_misses += 1
            else:
                cache_misses += 1

            # Extract if not cached
            if not cached_extraction:
                if not EXTRACTION_ENABLED:
                    # Skip extraction if disabled
                    continue

                # Extract entities and votes (would use spaCy here)
                try:
                    entities = extract_entities(text)
                    votes = extract_votes(text, meeting_context={})
                except Exception as e:
                    logger.warning(f"Extraction failed for {page_file_path}: {e}")
                    entities = {"persons": [], "orgs": [], "locations": []}
                    votes = {"votes": []}

                # Write cache
                if content_hash is None:
                    content_hash = hash_text_content(text)
                cache_file = f"{page_file_path}.extracted.json"
                cache_data = {
                    "content_hash": content_hash,
                    "extracted_at": datetime.datetime.now().isoformat(),
                    "entities": entities,
                    "votes": votes,
                }
                save_extraction_cache(cache_file, cache_data)

            # Update database
            db[table_name].update(
                page["id"],
                {
                    "entities_json": json.dumps(entities),
                    "votes_json": json.dumps(votes)
                }
            )

        log(
            f"Extraction complete for {table_name}: {cache_hits} from cache, {cache_misses} extracted",
            subdomain=subdomain,
            cache_hits=cache_hits,
            cache_misses=cache_misses
        )

    et = time.time()
    elapsed = et - st
    log(f"Total extraction time: {elapsed:.2f}s", subdomain=subdomain, elapsed_time=f"{elapsed:.2f}")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_utils.py::test_extract_entities_for_site_updates_database -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/utils.py tests/test_utils.py
git commit -m "feat: add extract_entities_for_site function"
```

---

### Task 3: Extract-Entities Command (--subdomain mode)

**Files:**
- Modify: `src/clerk/cli.py` (add extract-entities command)
- Test: `tests/test_cli.py` (add command tests)

**Step 1: Write failing test for extract-entities command**

```python
# Add to tests/test_cli.py
def test_extract_entities_with_subdomain(tmp_path, monkeypatch, test_site):
    """extract-entities --subdomain processes a specific site"""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("ENABLE_EXTRACTION", "0")

    from clerk.cli import cli
    from clerk.utils import assert_db_exists
    import sqlite_utils

    # Create test site
    subdomain = "test.civic.band"
    test_site(subdomain)

    # Run migration to add extraction columns
    runner = CliRunner()
    runner.invoke(cli, ['migrate-extraction-schema'])

    # Mark site as pending extraction
    db = assert_db_exists()
    db["sites"].update(subdomain, {"extraction_status": "pending"})

    # Run extract-entities
    result = runner.invoke(cli, ['extract-entities', '--subdomain', subdomain])

    assert result.exit_code == 0

    # Verify site status updated to completed
    site = db["sites"].get(subdomain)
    assert site["extraction_status"] == "completed"
    assert site["last_extracted"] is not None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_extract_entities_with_subdomain -v`
Expected: FAIL with "No such command 'extract-entities'"

**Step 3: Implement extract-entities command**

```python
# Add to src/clerk/cli.py
@cli.command()
@click.option("-s", "--subdomain")
@click.option("-n", "--next-site", is_flag=True)
def extract_entities(subdomain, next_site=False):
    """Extract entities from site text files and update database"""
    extract_entities_internal(subdomain, next_site)


def extract_entities_internal(subdomain, next_site=False):
    """Internal implementation of extract-entities command"""
    from .utils import extract_entities_for_site

    db = assert_db_exists()

    # Get site to process
    if next_site:
        # Will implement in Task 4
        log("--next-site mode not yet implemented")
        return

    if not subdomain:
        log("Must specify --subdomain or --next-site", level="error")
        return

    # Check if extraction already in progress
    num_in_progress = db.execute(
        "SELECT COUNT(*) FROM sites WHERE extraction_status = 'in_progress'"
    ).fetchone()[0]

    if num_in_progress > 0:
        log("Extraction already in progress, exiting")
        return

    # Mark as in_progress
    db["sites"].update(subdomain, {"extraction_status": "in_progress"})

    try:
        # Run extraction
        extract_entities_for_site(subdomain, force_extraction=False)

        # Get site info for deployment
        site = db["sites"].get(subdomain)
        site_name = site["name"]

        # Deploy unless in dev mode
        if not os.environ.get("CIVIC_DEV_MODE"):
            site_db = sqlite_utils.Database(f"{STORAGE_DIR}/{subdomain}/meetings.db")
            pm.hook.deploy_municipality(
                subdomain=subdomain,
                municipality=site_name,
                db=site_db
            )
            pm.hook.post_deploy(
                subdomain=subdomain,
                municipality=site_name
            )
            log("Deployed updated database", subdomain=subdomain)
        else:
            log("DEV MODE: Skipping deployment", subdomain=subdomain)

        # Mark as completed
        db["sites"].update(subdomain, {
            "extraction_status": "completed",
            "last_extracted": datetime.datetime.now().isoformat()
        })

        log("Extraction completed successfully", subdomain=subdomain)

    except Exception as e:
        # Mark as failed
        db["sites"].update(subdomain, {"extraction_status": "failed"})
        log(f"Extraction failed: {e}", subdomain=subdomain, level="error")
        raise
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_extract_entities_with_subdomain -v`
Expected: PASS

**Step 5: Add missing datetime import**

```python
# Add to top of src/clerk/cli.py if not already present
import datetime
```

**Step 6: Run test again to verify**

Run: `uv run pytest tests/test_cli.py::test_extract_entities_with_subdomain -v`
Expected: PASS

**Step 7: Commit**

```bash
git add src/clerk/cli.py tests/test_cli.py
git commit -m "feat: add extract-entities command with --subdomain mode"
```

---

### Task 4: Extract-Entities Command (--next-site mode)

**Files:**
- Modify: `src/clerk/cli.py` (implement --next-site logic)
- Test: `tests/test_cli.py` (add next-site tests)

**Step 1: Write failing test for --next-site selection**

```python
# Add to tests/test_cli.py
def test_extract_entities_next_site_selects_pending(tmp_path, monkeypatch, test_site):
    """extract-entities --next-site selects next pending site"""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("ENABLE_EXTRACTION", "0")

    from clerk.cli import cli
    from clerk.utils import assert_db_exists

    # Create multiple test sites
    site1 = "site1.civic.band"
    site2 = "site2.civic.band"
    site3 = "site3.civic.band"

    test_site(site1)
    test_site(site2)
    test_site(site3)

    # Run migration
    runner = CliRunner()
    runner.invoke(cli, ['migrate-extraction-schema'])

    db = assert_db_exists()

    # Set different statuses and extraction times
    db["sites"].update(site1, {
        "extraction_status": "completed",
        "last_extracted": "2024-01-01T00:00:00"
    })
    db["sites"].update(site2, {
        "extraction_status": "pending",
        "last_extracted": None  # Never extracted
    })
    db["sites"].update(site3, {
        "extraction_status": "pending",
        "last_extracted": "2024-01-02T00:00:00"  # Extracted but pending again
    })

    # Run extract-entities --next-site
    result = runner.invoke(cli, ['extract-entities', '--next-site'])

    assert result.exit_code == 0

    # Should process site2 (pending, never extracted)
    site2_data = db["sites"].get(site2)
    assert site2_data["extraction_status"] == "completed"
    assert site2_data["last_extracted"] is not None

    # Site1 and site3 should be unchanged
    assert db["sites"].get(site1)["extraction_status"] == "completed"
    assert db["sites"].get(site3)["extraction_status"] == "pending"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_extract_entities_next_site_selects_pending -v`
Expected: FAIL with assertion error (site2 not processed)

**Step 3: Implement --next-site logic**

```python
# Modify extract_entities_internal in src/clerk/cli.py
def extract_entities_internal(subdomain, next_site=False):
    """Internal implementation of extract-entities command"""
    from .utils import extract_entities_for_site

    db = assert_db_exists()

    # Get site to process
    if next_site:
        # Check for sites already in progress
        num_in_progress = db.execute(
            "SELECT COUNT(*) FROM sites WHERE extraction_status = 'in_progress'"
        ).fetchone()[0]

        if num_in_progress > 0:
            log("Extraction already in progress, exiting")
            return

        # Select next site needing extraction
        query = """
            SELECT subdomain FROM sites
            WHERE extraction_status IN ('pending', 'failed')
            ORDER BY last_extracted ASC NULLS FIRST
            LIMIT 1
        """
        result = db.execute(query).fetchone()

        if not result:
            log("No sites need extraction")
            return

        subdomain = result[0]
        log(f"Selected site for extraction: {subdomain}")

    if not subdomain:
        log("Must specify --subdomain or --next-site", level="error")
        return

    # Check if extraction already in progress (for --subdomain mode)
    if not next_site:
        num_in_progress = db.execute(
            "SELECT COUNT(*) FROM sites WHERE extraction_status = 'in_progress'"
        ).fetchone()[0]

        if num_in_progress > 0:
            log("Extraction already in progress, exiting")
            return

    # Mark as in_progress
    db["sites"].update(subdomain, {"extraction_status": "in_progress"})

    # ... rest of implementation stays the same
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_extract_entities_next_site_selects_pending -v`
Expected: PASS

**Step 5: Write test for "no sites need extraction" case**

```python
# Add to tests/test_cli.py
def test_extract_entities_next_site_no_pending(tmp_path, monkeypatch, test_site):
    """extract-entities --next-site exits gracefully when no sites pending"""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    from clerk.cli import cli
    from clerk.utils import assert_db_exists

    # Create site that's already completed
    site = "test.civic.band"
    test_site(site)

    # Run migration
    runner = CliRunner()
    runner.invoke(cli, ['migrate-extraction-schema'])

    db = assert_db_exists()
    db["sites"].update(site, {"extraction_status": "completed"})

    # Run extract-entities --next-site
    result = runner.invoke(cli, ['extract-entities', '--next-site'])

    assert result.exit_code == 0
    assert "No sites need extraction" in result.output
```

**Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_extract_entities_next_site_no_pending -v`
Expected: PASS

**Step 7: Commit**

```bash
git add src/clerk/cli.py tests/test_cli.py
git commit -m "feat: implement --next-site mode for extract-entities"
```

---

### Task 5: CIVIC_DEV_MODE Testing

**Files:**
- Test: `tests/test_cli.py` (add dev mode test)

**Step 1: Write test for CIVIC_DEV_MODE**

```python
# Add to tests/test_cli.py
def test_extract_entities_dev_mode_skips_deploy(tmp_path, monkeypatch, test_site):
    """CIVIC_DEV_MODE=1 skips deployment after extraction"""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("ENABLE_EXTRACTION", "0")
    monkeypatch.setenv("CIVIC_DEV_MODE", "1")

    from clerk.cli import cli
    from clerk.utils import assert_db_exists

    # Create test site
    subdomain = "test.civic.band"
    test_site(subdomain)

    # Run migration
    runner = CliRunner()
    runner.invoke(cli, ['migrate-extraction-schema'])

    # Run extract-entities
    result = runner.invoke(cli, ['extract-entities', '--subdomain', subdomain])

    assert result.exit_code == 0
    assert "DEV MODE: Skipping deployment" in result.output
    assert "Deployed updated database" not in result.output

    # Verify extraction still marked as completed
    db = assert_db_exists()
    site = db["sites"].get(subdomain)
    assert site["extraction_status"] == "completed"
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_extract_entities_dev_mode_skips_deploy -v`
Expected: PASS (implementation already handles this)

**Step 3: Commit**

```bash
git add tests/test_cli.py
git commit -m "test: add CIVIC_DEV_MODE verification for extract-entities"
```

---

### Task 6: Error Handling and Failed Status

**Files:**
- Test: `tests/test_cli.py` (add error handling tests)

**Step 1: Write test for extraction failure**

```python
# Add to tests/test_cli.py
def test_extract_entities_marks_failed_on_error(tmp_path, monkeypatch, test_site):
    """Extraction errors mark site as failed"""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    from clerk.cli import cli
    from clerk.utils import assert_db_exists

    # Create test site with missing text directory
    subdomain = "test.civic.band"
    test_site(subdomain)

    # Delete text directory to cause error
    import shutil
    txt_dir = tmp_path / subdomain / "txt"
    if txt_dir.exists():
        shutil.rmtree(txt_dir)

    # Run migration
    runner = CliRunner()
    runner.invoke(cli, ['migrate-extraction-schema'])

    # Run extract-entities (will fail)
    result = runner.invoke(cli, ['extract-entities', '--subdomain', subdomain])

    # Should exit with error
    assert result.exit_code != 0

    # Verify status marked as failed
    db = assert_db_exists()
    site = db["sites"].get(subdomain)
    assert site["extraction_status"] == "failed"
    assert site["last_extracted"] is None  # Not updated on failure
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_extract_entities_marks_failed_on_error -v`
Expected: PASS (implementation already handles this)

**Step 3: Write test for retry of failed sites**

```python
# Add to tests/test_cli.py
def test_extract_entities_next_site_retries_failed(tmp_path, monkeypatch, test_site):
    """--next-site retries failed extractions"""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("ENABLE_EXTRACTION", "0")

    from clerk.cli import cli
    from clerk.utils import assert_db_exists

    # Create sites
    site1 = "site1.civic.band"
    site2 = "site2.civic.band"

    test_site(site1)
    test_site(site2)

    # Run migration
    runner = CliRunner()
    runner.invoke(cli, ['migrate-extraction-schema'])

    db = assert_db_exists()

    # Mark site1 as failed, site2 as pending
    db["sites"].update(site1, {
        "extraction_status": "failed",
        "last_extracted": None
    })
    db["sites"].update(site2, {
        "extraction_status": "pending",
        "last_extracted": "2024-01-01T00:00:00"
    })

    # Run --next-site, should pick site1 (failed with NULL last_extracted)
    result = runner.invoke(cli, ['extract-entities', '--next-site'])

    assert result.exit_code == 0

    # Site1 should now be completed
    site1_data = db["sites"].get(site1)
    assert site1_data["extraction_status"] == "completed"
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_extract_entities_next_site_retries_failed -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_cli.py
git commit -m "test: add error handling and retry tests for extract-entities"
```

---

### Task 7: Integration Test

**Files:**
- Test: `tests/test_integration.py` (add end-to-end test)

**Step 1: Write integration test**

```python
# Add to tests/test_integration.py
def test_sequential_extraction_workflow(tmp_path, monkeypatch):
    """End-to-end: migration → extract → deploy → status tracking"""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("ENABLE_EXTRACTION", "0")
    monkeypatch.setenv("CIVIC_DEV_MODE", "1")  # Skip actual deployment

    from clerk.cli import cli
    from clerk.utils import assert_db_exists
    import sqlite_utils

    runner = CliRunner()

    # 1. Create test site
    subdomain = "test.civic.band"
    site_dir = tmp_path / subdomain
    txt_dir = site_dir / "txt"
    meeting_dir = txt_dir / "2024-01-01_Meeting"
    meeting_date_dir = meeting_dir / "2024-01-01"
    meeting_date_dir.mkdir(parents=True)

    # Write text file
    (meeting_date_dir / "0001.txt").write_text("Test meeting minutes")

    # Create database with empty entities
    site_db = sqlite_utils.Database(str(site_dir / "meetings.db"))
    site_db["minutes"].insert({
        "id": "test123",
        "meeting": "2024-01-01_Meeting",
        "date": "2024-01-01",
        "page": 1,
        "text": "Test meeting minutes",
        "page_image": "/path/to/image.png",
        "entities_json": "{}",
        "votes_json": "{}"
    })

    # Register site
    db = assert_db_exists()
    db["sites"].insert({
        "subdomain": subdomain,
        "name": "Test City",
        "state": "CA",
        "country": "USA",
        "kind": "city-council",
        "scraper": "test",
        "pages": 1,
        "start_year": 2024,
        "status": "deployed"
    })

    # 2. Run migration
    result = runner.invoke(cli, ['migrate-extraction-schema'])
    assert result.exit_code == 0

    # 3. Verify site marked as pending
    site = db["sites"].get(subdomain)
    assert site["extraction_status"] == "pending"
    assert site["last_extracted"] is None

    # 4. Run extraction
    result = runner.invoke(cli, ['extract-entities', '--subdomain', subdomain])
    assert result.exit_code == 0

    # 5. Verify status updated
    site = db["sites"].get(subdomain)
    assert site["extraction_status"] == "completed"
    assert site["last_extracted"] is not None

    # 6. Verify dev mode skipped deployment
    assert "DEV MODE: Skipping deployment" in result.output
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_integration.py::test_sequential_extraction_workflow -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration test for sequential extraction workflow"
```

---

### Task 8: Update build-db-from-text to skip extraction

**Files:**
- Modify: `src/clerk/utils.py` (add skip_extraction parameter)
- Modify: `src/clerk/cli.py` (add --skip-extraction flag)
- Test: `tests/test_utils.py` (add skip extraction test)

**Step 1: Write failing test for skip extraction**

```python
# Add to tests/test_utils.py
def test_build_table_from_text_skip_extraction(tmp_path, monkeypatch):
    """build_table_from_text with skip_extraction leaves entities empty"""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("ENABLE_EXTRACTION", "1")  # Would normally extract

    from clerk.utils import build_table_from_text
    import sqlite_utils

    subdomain = "test.civic.band"
    txt_dir = tmp_path / subdomain / "txt"
    meeting_dir = txt_dir / "2024-01-01_Meeting"
    meeting_date_dir = meeting_dir / "2024-01-01"
    meeting_date_dir.mkdir(parents=True)

    (meeting_date_dir / "0001.txt").write_text("Test meeting text")

    db = sqlite_utils.Database(":memory:")
    db["minutes"].create({
        "id": str,
        "meeting": str,
        "date": str,
        "page": int,
        "text": str,
        "page_image": str,
        "entities_json": str,
        "votes_json": str
    }, pk="id")

    # Build with skip_extraction=True
    build_table_from_text(subdomain, str(txt_dir), db, "minutes", skip_extraction=True)

    # Verify entities_json is empty
    page = list(db["minutes"].rows)[0]
    assert page["entities_json"] == "{}"
    assert page["votes_json"] == "{}"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_utils.py::test_build_table_from_text_skip_extraction -v`
Expected: FAIL with "TypeError: build_table_from_text() got an unexpected keyword argument 'skip_extraction'"

**Step 3: Add skip_extraction parameter to build_table_from_text**

```python
# Modify build_table_from_text signature in src/clerk/utils.py
def build_table_from_text(
    subdomain, txt_dir, db, table_name, municipality=None, force_extraction=False, skip_extraction=False
):
    # ... existing code ...

    # In the extraction section, wrap with skip_extraction check:
    if uncached_indices and EXTRACTION_ENABLED and not skip_extraction:
        # ... existing extraction code ...
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_utils.py::test_build_table_from_text_skip_extraction -v`
Expected: PASS

**Step 5: Add --skip-extraction flag to build-db-from-text command**

```python
# Modify build_db_from_text command in src/clerk/cli.py
@cli.command()
@click.option("-s", "--subdomain")
@click.option("--force-extraction", is_flag=True, help="Ignore cache and re-extract all pages")
@click.option("--skip-extraction", is_flag=True, help="Skip entity/vote extraction (fast database build)")
def build_db_from_text(subdomain, force_extraction=False, skip_extraction=False):
    """Build database from text files"""
    build_db_from_text_internal(subdomain, force_extraction=force_extraction, skip_extraction=skip_extraction)
    rebuild_site_fts_internal(subdomain)


# Update build_db_from_text_internal and build_table_from_text calls
def build_db_from_text_internal(subdomain, force_extraction=False, skip_extraction=False):
    # ... existing code ...

    if os.path.exists(minutes_txt_dir):
        build_table_from_text(
            subdomain, minutes_txt_dir, db, "minutes",
            force_extraction=force_extraction, skip_extraction=skip_extraction
        )
    if os.path.exists(agendas_txt_dir):
        build_table_from_text(
            subdomain, agendas_txt_dir, db, "agendas",
            force_extraction=force_extraction, skip_extraction=skip_extraction
        )
```

**Step 6: Run all tests to verify**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add src/clerk/utils.py src/clerk/cli.py tests/test_utils.py
git commit -m "feat: add --skip-extraction flag to build-db-from-text"
```

---

### Task 9: Documentation and README Update

**Files:**
- Modify: `README.md` (document new commands and workflow)

**Step 1: Update README with sequential extraction documentation**

Add section after "Build Database from Text Files":

```markdown
### Sequential Extraction (Recommended for Large Operations)

For better memory efficiency and operational flexibility, you can separate database building from entity extraction:

**1. Fast database build** (skips extraction):
```bash
clerk build-db-from-text --subdomain example.civic.band --skip-extraction
```

**2. Run migration** (one-time setup):
```bash
clerk migrate-extraction-schema
```

**3. Extract entities** for a specific site:
```bash
ENABLE_EXTRACTION=1 clerk extract-entities --subdomain example.civic.band
```

**4. Or extract next pending site** (for cron jobs):
```bash
ENABLE_EXTRACTION=1 clerk extract-entities --next-site
```

#### Cron Setup for Sequential Extraction

```cron
# Extract entities for one site every 30 minutes
*/30 * * * * cd /path/to/clerk && ENABLE_EXTRACTION=1 clerk extract-entities --next-site >> /var/log/clerk-extraction.log 2>&1
```

#### Testing Without Deployment

```bash
# Extract entities without deploying (for testing)
CIVIC_DEV_MODE=1 ENABLE_EXTRACTION=1 clerk extract-entities --subdomain test.civic.band
```
```

**Step 2: Update environment variables section**

Add to Configuration > Environment Variables:

```markdown
- `CIVIC_DEV_MODE`: Set to `1` to skip deployment after extraction (for testing)
```

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add sequential extraction documentation to README"
```

---

## Summary

This implementation plan creates a sequential extraction system that:

1. **Adds database schema** with extraction_status and last_extracted columns
2. **Provides migration command** (migrate-extraction-schema) for safe schema updates
3. **Implements core extraction function** that reads text files, uses cache, updates database
4. **Creates extract-entities command** with --subdomain and --next-site modes
5. **Supports CIVIC_DEV_MODE** for testing without deployment
6. **Handles errors gracefully** with failed status and retry logic
7. **Enables cron workflows** for processing 900 sites sequentially
8. **Maintains fast database builds** with --skip-extraction flag

**Benefits:**
- ~5GB memory footprint (vs ~10GB with inline extraction)
- Sites go live immediately (database builds in seconds/minutes)
- Failed extractions don't block deployments
- Clear status tracking and retry logic
- Flexible scheduling for large batch operations

**Testing coverage:**
- Unit tests for all new functions
- Integration test for end-to-end workflow
- Error handling and edge cases
- Dev mode verification
