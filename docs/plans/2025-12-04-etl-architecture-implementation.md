# ETL Architecture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add flexible ETL pipeline support to clerk, enabling both document workflows and structured data workflows while maintaining backward compatibility.

**Architecture:** Add three new hooks (`extractor_class`, `transformer_class`, `loader_class`), a `pipeline` JSON column for site configuration, default components (IdentityTransformer, GenericLoader), and a FetcherAdapter for backward compatibility with existing plugins.

**Tech Stack:** Python, pluggy, sqlite-utils, Click, pytest

---

### Task 1: Add new ETL hooks to hookspecs

**Files:**
- Modify: `src/clerk/hookspecs.py`
- Create: `tests/test_etl_hooks.py`

**Step 1: Write the failing test for new hooks**

Create `tests/test_etl_hooks.py`:

```python
"""Tests for ETL hook specifications."""

import pytest
import pluggy

from clerk.hookspecs import ClerkSpec


class TestETLHookSpecs:
    """Tests for ETL-related hook specifications."""

    def test_extractor_class_hook_exists(self):
        """Test that extractor_class hookspec is defined."""
        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)

        # Should not raise - hook exists
        assert hasattr(pm.hook, "extractor_class")

    def test_transformer_class_hook_exists(self):
        """Test that transformer_class hookspec is defined."""
        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)

        assert hasattr(pm.hook, "transformer_class")

    def test_loader_class_hook_exists(self):
        """Test that loader_class hookspec is defined."""
        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)

        assert hasattr(pm.hook, "loader_class")

    def test_extractor_class_hook_callable(self):
        """Test that extractor_class hook can be called."""
        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)

        # Should return empty list when no plugins registered
        result = pm.hook.extractor_class(label="test")
        assert result == []

    def test_transformer_class_hook_callable(self):
        """Test that transformer_class hook can be called."""
        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)

        result = pm.hook.transformer_class(label="test")
        assert result == []

    def test_loader_class_hook_callable(self):
        """Test that loader_class hook can be called."""
        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)

        result = pm.hook.loader_class(label="test")
        assert result == []
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_etl_hooks.py -v`

Expected: FAIL with `AttributeError: 'HookRelay' object has no attribute 'extractor_class'`

**Step 3: Add new hooks to hookspecs.py**

Modify `src/clerk/hookspecs.py` to add the three new hooks after the existing hooks:

```python
from pluggy import HookimplMarker, HookspecMarker

hookspec = HookspecMarker("civicband.clerk")
hookimpl = HookimplMarker("civicband.clerk")


class ClerkSpec:
    @hookspec
    def fetcher_extra(self, label):
        """Gets the necessary extra bits for setting up a fetcher"""

    @hookspec
    def fetcher_class(self, label):
        """Gets the fetcher class for label"""

    @hookspec
    def deploy_municipality(self, subdomain):
        """Deploys the necessary files for serving a municipality"""

    @hookspec
    def post_deploy(self, site):
        """Runs actions after the deploy of a municipality"""

    @hookspec
    def upload_static_file(self, file_path, storage_path):
        """Uploads a file to static storage, like S3 or a CDN"""

    @hookspec
    def post_create(self, subdomain):
        """Runs actions actions after the creation of a site"""

    # ETL Pipeline Hooks

    @hookspec
    def extractor_class(self, label):
        """Returns an extractor class for the given label.

        Extractor interface:
            __init__(self, site: dict, config: dict)
            extract(self) -> None  # writes files to STORAGE_DIR/{subdomain}/extracted/
        """

    @hookspec
    def transformer_class(self, label):
        """Returns a transformer class for the given label.

        Transformer interface:
            __init__(self, site: dict, config: dict)
            transform(self) -> None  # reads extracted files, writes transformed files
        """

    @hookspec
    def loader_class(self, label):
        """Returns a loader class for the given label.

        Loader interface:
            __init__(self, site: dict, config: dict)
            load(self) -> None  # reads transformed files, creates tables, writes to DB
        """
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_etl_hooks.py -v`

Expected: All tests PASS

**Step 5: Run full test suite to ensure no regressions**

Run: `uv run pytest tests/ -v`

Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/clerk/hookspecs.py tests/test_etl_hooks.py
git commit -m "feat: add ETL pipeline hooks (extractor, transformer, loader)

Add three new hookspecs for the ETL architecture:
- extractor_class(label): returns class to extract/fetch data
- transformer_class(label): returns class to transform data
- loader_class(label): returns class to load data into database"
```

---

### Task 2: Add pipeline column to sites schema

**Files:**
- Modify: `src/clerk/utils.py`
- Modify: `tests/test_utils.py`

**Step 1: Write the failing test for pipeline column**

Add to `tests/test_utils.py`:

```python
class TestPipelineColumn:
    """Tests for pipeline column in sites table."""

    def test_pipeline_column_exists(self, tmp_path, monkeypatch):
        """Test that pipeline column is created in new databases."""
        monkeypatch.chdir(tmp_path)

        from clerk.utils import assert_db_exists

        db = assert_db_exists()

        # Check column exists
        columns = {col.name for col in db["sites"].columns}
        assert "pipeline" in columns

    def test_pipeline_column_added_to_existing_db(self, tmp_path, monkeypatch):
        """Test that pipeline column is added to existing databases."""
        monkeypatch.chdir(tmp_path)

        import sqlite_utils

        # Create old-style database without pipeline column
        db = sqlite_utils.Database("civic.db")
        db["sites"].create(
            {
                "subdomain": str,
                "name": str,
                "state": str,
                "country": str,
                "kind": str,
                "scraper": str,
                "pages": int,
                "start_year": int,
                "extra": str,
                "status": str,
                "last_updated": str,
                "lat": str,
                "lng": str,
            },
            pk="subdomain",
        )

        # Now call assert_db_exists which should add the column
        from clerk.utils import assert_db_exists

        db = assert_db_exists()

        columns = {col.name for col in db["sites"].columns}
        assert "pipeline" in columns

    def test_pipeline_column_nullable(self, tmp_path, monkeypatch):
        """Test that pipeline column allows NULL values."""
        monkeypatch.chdir(tmp_path)

        from clerk.utils import assert_db_exists

        db = assert_db_exists()

        # Insert row without pipeline
        db["sites"].insert(
            {
                "subdomain": "test.civic.band",
                "name": "Test",
                "state": "CA",
                "country": "US",
                "kind": "council",
                "scraper": "test",
                "pages": 0,
                "start_year": 2020,
                "extra": None,
                "status": "new",
                "last_updated": None,
                "lat": "0",
                "lng": "0",
            }
        )

        site = db["sites"].get("test.civic.band")
        assert site["pipeline"] is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_utils.py::TestPipelineColumn -v`

Expected: FAIL with `AssertionError: assert 'pipeline' in columns`

**Step 3: Add pipeline column to schema**

Modify `src/clerk/utils.py`:

```python
import os

import logfire
import pluggy
import sqlite_utils

from .hookspecs import ClerkSpec

pm = pluggy.PluginManager("civicband.clerk")
pm.add_hookspecs(ClerkSpec)

STORAGE_DIR = os.environ.get("STORAGE_DIR", "../sites")


@logfire.instrument("assert_db_exists")
def assert_db_exists():
    db = sqlite_utils.Database("civic.db")
    if not db["sites"].exists():
        db["sites"].create(  # pyright: ignore[reportAttributeAccessIssue]
            {
                "subdomain": str,
                "name": str,
                "state": str,
                "country": str,
                "kind": str,
                "scraper": str,
                "pages": int,
                "start_year": int,
                "extra": str,
                "status": str,
                "last_updated": str,
                "lat": str,
                "lng": str,
                "pipeline": str,  # JSON column for ETL pipeline config
            },
            pk="subdomain",
        )
    if not db["feed_entries"].exists():
        db["feed_entries"].create(  # pyright: ignore[reportAttributeAccessIssue]
            {"subdomain": str, "date": str, "kind": str, "name": str},
        )
    # Drop deprecated columns
    db["sites"].transform(drop={"ocr_class"})  # pyright: ignore[reportAttributeAccessIssue]
    db["sites"].transform(drop={"docker_port"})  # pyright: ignore[reportAttributeAccessIssue]
    db["sites"].transform(drop={"save_agendas"})  # pyright: ignore[reportAttributeAccessIssue]
    db["sites"].transform(drop={"site_db"})  # pyright: ignore[reportAttributeAccessIssue]

    # Add pipeline column if it doesn't exist (migration for existing DBs)
    columns = {col.name for col in db["sites"].columns}
    if "pipeline" not in columns:
        db.execute("ALTER TABLE sites ADD COLUMN pipeline TEXT")

    return db
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_utils.py::TestPipelineColumn -v`

Expected: All tests PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`

Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/clerk/utils.py tests/test_utils.py
git commit -m "feat: add pipeline column to sites schema

Add pipeline TEXT column for JSON ETL pipeline configuration.
Includes migration to add column to existing databases."
```

---

### Task 3: Create default ETL components

**Files:**
- Create: `src/clerk/defaults.py`
- Create: `tests/test_defaults.py`

**Step 1: Write the failing test for IdentityTransformer**

Create `tests/test_defaults.py`:

```python
"""Tests for default ETL components."""

import csv
import json
import pytest
from pathlib import Path


class TestIdentityTransformer:
    """Tests for IdentityTransformer default component."""

    def test_identity_transformer_exists(self):
        """Test that IdentityTransformer can be imported."""
        from clerk.defaults import IdentityTransformer

        assert IdentityTransformer is not None

    def test_identity_transformer_interface(self):
        """Test that IdentityTransformer has correct interface."""
        from clerk.defaults import IdentityTransformer

        site = {"subdomain": "test.civic.band"}
        config = {}

        transformer = IdentityTransformer(site, config)

        assert hasattr(transformer, "transform")
        assert callable(transformer.transform)

    def test_identity_transformer_does_nothing(self, tmp_path):
        """Test that IdentityTransformer is a no-op."""
        from clerk.defaults import IdentityTransformer

        site = {"subdomain": "test.civic.band"}
        config = {}

        transformer = IdentityTransformer(site, config)

        # Should not raise
        transformer.transform()


class TestGenericLoader:
    """Tests for GenericLoader default component."""

    def test_generic_loader_exists(self):
        """Test that GenericLoader can be imported."""
        from clerk.defaults import GenericLoader

        assert GenericLoader is not None

    def test_generic_loader_interface(self):
        """Test that GenericLoader has correct interface."""
        from clerk.defaults import GenericLoader

        site = {"subdomain": "test.civic.band"}
        config = {}

        loader = GenericLoader(site, config)

        assert hasattr(loader, "load")
        assert callable(loader.load)

    def test_generic_loader_loads_csv(self, tmp_path, monkeypatch):
        """Test that GenericLoader loads CSV files to tables."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        from clerk.defaults import GenericLoader

        subdomain = "test.civic.band"
        site = {"subdomain": subdomain}
        config = {}

        # Create transformed directory with CSV file
        transformed_dir = tmp_path / subdomain / "transformed"
        transformed_dir.mkdir(parents=True)

        csv_file = transformed_dir / "budget.csv"
        csv_file.write_text("department,amount\nParks,1000\nFire,2000\n")

        loader = GenericLoader(site, config)
        loader.load()

        # Check database was created with table
        import sqlite_utils

        db_path = tmp_path / subdomain / "data.db"
        assert db_path.exists()

        db = sqlite_utils.Database(db_path)
        assert "budget" in db.table_names()

        rows = list(db["budget"].rows)
        assert len(rows) == 2
        assert rows[0]["department"] == "Parks"

    def test_generic_loader_loads_json(self, tmp_path, monkeypatch):
        """Test that GenericLoader loads JSON files to tables."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        from clerk.defaults import GenericLoader

        subdomain = "test.civic.band"
        site = {"subdomain": subdomain}
        config = {}

        # Create transformed directory with JSON file
        transformed_dir = tmp_path / subdomain / "transformed"
        transformed_dir.mkdir(parents=True)

        json_file = transformed_dir / "items.json"
        json_file.write_text(json.dumps([
            {"name": "Item 1", "value": 100},
            {"name": "Item 2", "value": 200},
        ]))

        loader = GenericLoader(site, config)
        loader.load()

        import sqlite_utils

        db_path = tmp_path / subdomain / "data.db"
        db = sqlite_utils.Database(db_path)

        assert "items" in db.table_names()
        rows = list(db["items"].rows)
        assert len(rows) == 2

    def test_generic_loader_skips_empty_directory(self, tmp_path, monkeypatch):
        """Test that GenericLoader handles missing/empty transformed dir."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        from clerk.defaults import GenericLoader

        subdomain = "test.civic.band"
        site = {"subdomain": subdomain}
        config = {}

        # Don't create transformed directory
        loader = GenericLoader(site, config)

        # Should not raise
        loader.load()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_defaults.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'clerk.defaults'`

**Step 3: Implement default components**

Create `src/clerk/defaults.py`:

```python
"""Default ETL components for clerk."""

import csv
import json
import os
from pathlib import Path

import sqlite_utils

STORAGE_DIR = os.environ.get("STORAGE_DIR", "../sites")


class IdentityTransformer:
    """Default transformer that passes data through unchanged.

    Use this when extracted data is already in the desired format
    and no transformation is needed.
    """

    def __init__(self, site: dict, config: dict):
        """Initialize the transformer.

        Args:
            site: Site configuration dictionary.
            config: Additional configuration from site's extra field.
        """
        self.site = site
        self.config = config

    def transform(self) -> None:
        """No-op transformation - data passes through unchanged."""
        pass


class GenericLoader:
    """Default loader that creates tables from CSV/JSON files.

    Reads files from the transformed/ directory and creates
    database tables based on filename (e.g., budget.csv -> budget table).
    """

    def __init__(self, site: dict, config: dict):
        """Initialize the loader.

        Args:
            site: Site configuration dictionary.
            config: Additional configuration from site's extra field.
        """
        self.site = site
        self.config = config
        self.storage_dir = os.environ.get("STORAGE_DIR", STORAGE_DIR)

    def load(self) -> None:
        """Load all CSV/JSON files from transformed/ directory to database."""
        subdomain = self.site["subdomain"]
        transformed_dir = Path(self.storage_dir) / subdomain / "transformed"

        if not transformed_dir.exists():
            return

        db_path = Path(self.storage_dir) / subdomain / "data.db"
        db = sqlite_utils.Database(db_path)

        # Process CSV files
        for csv_file in transformed_dir.glob("*.csv"):
            table_name = csv_file.stem
            with open(csv_file) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if rows:
                    db[table_name].insert_all(rows, alter=True)

        # Process JSON files
        for json_file in transformed_dir.glob("*.json"):
            table_name = json_file.stem
            with open(json_file) as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    db[table_name].insert_all(data, alter=True)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_defaults.py -v`

Expected: All tests PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`

Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/clerk/defaults.py tests/test_defaults.py
git commit -m "feat: add default ETL components

Add IdentityTransformer (no-op) and GenericLoader (CSV/JSON to tables)
as default components for ETL pipelines."
```

---

### Task 4: Create FetcherAdapter for backward compatibility

**Files:**
- Create: `src/clerk/adapter.py`
- Create: `tests/test_adapter.py`

**Step 1: Write the failing test for FetcherAdapter**

Create `tests/test_adapter.py`:

```python
"""Tests for FetcherAdapter backward compatibility."""

import pytest


class MockOldStyleFetcher:
    """Mock fetcher with old-style interface."""

    def __init__(self):
        self.fetch_events_called = False
        self.ocr_called = False
        self.transform_called = False

    def fetch_events(self):
        self.fetch_events_called = True

    def ocr(self):
        self.ocr_called = True

    def transform(self):
        self.transform_called = True


class TestFetcherAdapter:
    """Tests for FetcherAdapter."""

    def test_adapter_exists(self):
        """Test that FetcherAdapter can be imported."""
        from clerk.adapter import FetcherAdapter

        assert FetcherAdapter is not None

    def test_adapter_wraps_fetcher(self):
        """Test that adapter wraps an old-style fetcher."""
        from clerk.adapter import FetcherAdapter

        old_fetcher = MockOldStyleFetcher()
        adapter = FetcherAdapter(old_fetcher)

        assert adapter.fetcher is old_fetcher

    def test_extract_calls_fetch_events(self):
        """Test that extract() calls the fetcher's fetch_events()."""
        from clerk.adapter import FetcherAdapter

        old_fetcher = MockOldStyleFetcher()
        adapter = FetcherAdapter(old_fetcher)

        adapter.extract()

        assert old_fetcher.fetch_events_called

    def test_transform_calls_ocr_and_transform(self):
        """Test that transform() calls fetcher's ocr() and transform()."""
        from clerk.adapter import FetcherAdapter

        old_fetcher = MockOldStyleFetcher()
        adapter = FetcherAdapter(old_fetcher)

        adapter.transform()

        assert old_fetcher.ocr_called
        assert old_fetcher.transform_called

    def test_load_is_noop(self):
        """Test that load() is a no-op (old transform writes to DB)."""
        from clerk.adapter import FetcherAdapter

        old_fetcher = MockOldStyleFetcher()
        adapter = FetcherAdapter(old_fetcher)

        # Should not raise
        adapter.load()

    def test_full_pipeline_sequence(self):
        """Test running full ETL pipeline through adapter."""
        from clerk.adapter import FetcherAdapter

        old_fetcher = MockOldStyleFetcher()
        adapter = FetcherAdapter(old_fetcher)

        # Simulate ETL pipeline
        adapter.extract()
        adapter.transform()
        adapter.load()

        assert old_fetcher.fetch_events_called
        assert old_fetcher.ocr_called
        assert old_fetcher.transform_called
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_adapter.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'clerk.adapter'`

**Step 3: Implement FetcherAdapter**

Create `src/clerk/adapter.py`:

```python
"""Adapter for backward compatibility with old-style fetchers."""


class FetcherAdapter:
    """Adapts old-style fetchers to the new ETL interface.

    Old fetchers implement:
        - fetch_events() - download data
        - ocr() - extract text from documents
        - transform() - build database

    This adapter maps them to the new ETL interface:
        - extract() -> fetch_events()
        - transform() -> ocr() + transform()
        - load() -> no-op (old transform() writes to DB)
    """

    def __init__(self, fetcher):
        """Initialize the adapter.

        Args:
            fetcher: An old-style fetcher instance with fetch_events(),
                     ocr(), and transform() methods.
        """
        self.fetcher = fetcher

    def extract(self) -> None:
        """Extract data by calling the fetcher's fetch_events()."""
        self.fetcher.fetch_events()

    def transform(self) -> None:
        """Transform data by calling fetcher's ocr() and transform()."""
        self.fetcher.ocr()
        self.fetcher.transform()

    def load(self) -> None:
        """No-op - old-style transform() already writes to database."""
        pass
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_adapter.py -v`

Expected: All tests PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`

Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/clerk/adapter.py tests/test_adapter.py
git commit -m "feat: add FetcherAdapter for backward compatibility

Adapter wraps old-style fetchers (fetch_events/ocr/transform) to work
with the new ETL interface (extract/transform/load)."
```

---

### Task 5: Add pipeline component lookup functions

**Files:**
- Create: `src/clerk/pipeline.py`
- Create: `tests/test_pipeline.py`

**Step 1: Write the failing test for lookup functions**

Create `tests/test_pipeline.py`:

```python
"""Tests for ETL pipeline orchestration."""

import json
import pytest
import pluggy

from clerk.hookspecs import ClerkSpec, hookimpl


class MockExtractor:
    def __init__(self, site, config):
        self.site = site

    def extract(self):
        pass


class MockTransformer:
    def __init__(self, site, config):
        self.site = site

    def transform(self):
        pass


class MockLoader:
    def __init__(self, site, config):
        self.site = site

    def load(self):
        pass


class MockETLPlugin:
    @hookimpl
    def extractor_class(self, label):
        if label == "mock_extractor":
            return MockExtractor
        return None

    @hookimpl
    def transformer_class(self, label):
        if label == "mock_transformer":
            return MockTransformer
        return None

    @hookimpl
    def loader_class(self, label):
        if label == "mock_loader":
            return MockLoader
        return None


@pytest.fixture
def etl_plugin_manager():
    """Create a plugin manager with mock ETL plugin."""
    pm = pluggy.PluginManager("civicband.clerk")
    pm.add_hookspecs(ClerkSpec)
    pm.register(MockETLPlugin())
    return pm


class TestLookupFunctions:
    """Tests for ETL component lookup functions."""

    def test_lookup_extractor_found(self, etl_plugin_manager, monkeypatch):
        """Test looking up an extractor that exists."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        result = pipeline.lookup_extractor("mock_extractor")
        assert result is MockExtractor

    def test_lookup_extractor_not_found(self, etl_plugin_manager, monkeypatch):
        """Test looking up an extractor that doesn't exist."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        result = pipeline.lookup_extractor("nonexistent")
        assert result is None

    def test_lookup_transformer_found(self, etl_plugin_manager, monkeypatch):
        """Test looking up a transformer that exists."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        result = pipeline.lookup_transformer("mock_transformer")
        assert result is MockTransformer

    def test_lookup_transformer_not_found(self, etl_plugin_manager, monkeypatch):
        """Test looking up a transformer that doesn't exist."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        result = pipeline.lookup_transformer("nonexistent")
        assert result is None

    def test_lookup_loader_found(self, etl_plugin_manager, monkeypatch):
        """Test looking up a loader that exists."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        result = pipeline.lookup_loader("mock_loader")
        assert result is MockLoader

    def test_lookup_loader_not_found(self, etl_plugin_manager, monkeypatch):
        """Test looking up a loader that doesn't exist."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        result = pipeline.lookup_loader("nonexistent")
        assert result is None


class TestGetPipelineComponents:
    """Tests for get_pipeline_components function."""

    def test_returns_components_from_pipeline_json(self, etl_plugin_manager, monkeypatch):
        """Test getting components from pipeline JSON."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        site = {
            "subdomain": "test.civic.band",
            "pipeline": json.dumps({
                "extractor": "mock_extractor",
                "transformer": "mock_transformer",
                "loader": "mock_loader",
            }),
        }

        components = pipeline.get_pipeline_components(site)

        assert components["extractor"] is MockExtractor
        assert components["transformer"] is MockTransformer
        assert components["loader"] is MockLoader

    def test_uses_defaults_for_missing_components(self, etl_plugin_manager, monkeypatch):
        """Test that defaults are used when components not specified."""
        from clerk import pipeline
        from clerk.defaults import IdentityTransformer, GenericLoader

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        site = {
            "subdomain": "test.civic.band",
            "pipeline": json.dumps({
                "extractor": "mock_extractor",
                # transformer and loader not specified
            }),
        }

        components = pipeline.get_pipeline_components(site)

        assert components["extractor"] is MockExtractor
        assert components["transformer"] is IdentityTransformer
        assert components["loader"] is GenericLoader

    def test_raises_if_extractor_not_found(self, etl_plugin_manager, monkeypatch):
        """Test that error is raised if extractor not found."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        site = {
            "subdomain": "test.civic.band",
            "pipeline": json.dumps({
                "extractor": "nonexistent",
            }),
        }

        with pytest.raises(ValueError, match="Extractor 'nonexistent' not found"):
            pipeline.get_pipeline_components(site)

    def test_returns_adapter_for_scraper_only(self, etl_plugin_manager, monkeypatch):
        """Test that FetcherAdapter is returned for scraper-only sites."""
        from clerk import pipeline
        from clerk.adapter import FetcherAdapter

        # Create a mock old-style fetcher
        class MockOldFetcher:
            def __init__(self, site, start_year, all_agendas):
                pass

            def fetch_events(self):
                pass

            def ocr(self):
                pass

            def transform(self):
                pass

        class OldStylePlugin:
            @hookimpl
            def fetcher_class(self, label):
                if label == "old_scraper":
                    return MockOldFetcher
                return None

        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)
        pm.register(OldStylePlugin())
        monkeypatch.setattr(pipeline, "pm", pm)

        site = {
            "subdomain": "test.civic.band",
            "scraper": "old_scraper",
            "start_year": 2020,
            "last_updated": None,
            # No pipeline field
        }

        result = pipeline.get_pipeline_components(site)

        assert isinstance(result, FetcherAdapter)

    def test_raises_if_no_pipeline_or_scraper(self, etl_plugin_manager, monkeypatch):
        """Test error when site has neither pipeline nor scraper."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        site = {
            "subdomain": "test.civic.band",
            # No pipeline, no scraper
        }

        with pytest.raises(ValueError, match="must have pipeline or scraper"):
            pipeline.get_pipeline_components(site)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'clerk.pipeline'`

**Step 3: Implement pipeline lookup functions**

Create `src/clerk/pipeline.py`:

```python
"""ETL pipeline orchestration and component lookup."""

import datetime
import json
from typing import Any

from .adapter import FetcherAdapter
from .defaults import GenericLoader, IdentityTransformer
from .utils import pm


def lookup_extractor(label: str) -> type | None:
    """Look up an extractor class by label.

    Args:
        label: The extractor label to look up.

    Returns:
        The extractor class, or None if not found.
    """
    results = pm.hook.extractor_class(label=label)
    results = [r for r in results if r is not None]
    return results[0] if results else None


def lookup_transformer(label: str) -> type | None:
    """Look up a transformer class by label.

    Args:
        label: The transformer label to look up.

    Returns:
        The transformer class, or None if not found.
    """
    results = pm.hook.transformer_class(label=label)
    results = [r for r in results if r is not None]
    return results[0] if results else None


def lookup_loader(label: str) -> type | None:
    """Look up a loader class by label.

    Args:
        label: The loader label to look up.

    Returns:
        The loader class, or None if not found.
    """
    results = pm.hook.loader_class(label=label)
    results = [r for r in results if r is not None]
    return results[0] if results else None


def get_pipeline_components(site: dict[str, Any]) -> dict[str, type] | FetcherAdapter:
    """Get ETL pipeline components for a site.

    If the site has a pipeline JSON config, looks up each component
    and uses defaults for missing ones.

    If the site only has a scraper field, wraps the old-style fetcher
    in a FetcherAdapter for backward compatibility.

    Args:
        site: Site configuration dictionary.

    Returns:
        Either a dict of component classes (extractor, transformer, loader)
        or a FetcherAdapter wrapping an old-style fetcher.

    Raises:
        ValueError: If required components are not found or site has
                    neither pipeline nor scraper configured.
    """
    pipeline_json = site.get("pipeline")

    if pipeline_json:
        pipeline = json.loads(pipeline_json)

        # Look up extractor (required)
        extractor_label = pipeline.get("extractor")
        if extractor_label:
            extractor_class = lookup_extractor(extractor_label)
            if extractor_class is None:
                raise ValueError(f"Extractor '{extractor_label}' not found")
        else:
            raise ValueError("Pipeline must specify an extractor")

        # Look up transformer (optional, defaults to IdentityTransformer)
        transformer_label = pipeline.get("transformer")
        if transformer_label:
            transformer_class = lookup_transformer(transformer_label)
            if transformer_class is None:
                raise ValueError(f"Transformer '{transformer_label}' not found")
        else:
            transformer_class = IdentityTransformer

        # Look up loader (optional, defaults to GenericLoader)
        loader_label = pipeline.get("loader")
        if loader_label:
            loader_class = lookup_loader(loader_label)
            if loader_class is None:
                raise ValueError(f"Loader '{loader_label}' not found")
        else:
            loader_class = GenericLoader

        return {
            "extractor": extractor_class,
            "transformer": transformer_class,
            "loader": loader_class,
        }

    elif site.get("scraper"):
        # Backward compatibility: wrap old-style fetcher
        fetcher = _get_old_style_fetcher(site)
        return FetcherAdapter(fetcher)

    else:
        raise ValueError("Site must have pipeline or scraper configured")


def _get_old_style_fetcher(site: dict[str, Any]):
    """Get an old-style fetcher for backward compatibility.

    Args:
        site: Site configuration dictionary.

    Returns:
        An instantiated fetcher object.
    """
    start_year = site["start_year"]
    try:
        start_year = datetime.datetime.strptime(
            site["last_updated"], "%Y-%m-%dT%H:%M:%S"
        ).year
    except (TypeError, ValueError):
        start_year = site["start_year"]

    fetcher_class = pm.hook.fetcher_class(label=site["scraper"])
    fetcher_class = [r for r in fetcher_class if r is not None]

    if fetcher_class:
        return fetcher_class[0](site, start_year, False)

    raise ValueError(f"Fetcher '{site['scraper']}' not found")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_pipeline.py -v`

Expected: All tests PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`

Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/clerk/pipeline.py tests/test_pipeline.py
git commit -m "feat: add ETL pipeline component lookup

Add functions to look up extractor/transformer/loader by label,
and get_pipeline_components() to get all components for a site
(with defaults and backward compatibility via FetcherAdapter)."
```

---

### Task 6: Integrate ETL pipeline into CLI update command

**Files:**
- Modify: `src/clerk/cli.py`
- Add to: `tests/test_cli.py`

**Step 1: Write the failing test for pipeline integration**

Add to `tests/test_cli.py`:

```python
class TestETLPipelineIntegration:
    """Tests for ETL pipeline integration in update command."""

    def test_update_uses_pipeline_when_configured(
        self, tmp_path, tmp_storage_dir, monkeypatch, cli_module
    ):
        """Test that update uses ETL pipeline when site has pipeline config."""
        import json

        import sqlite_utils
        from click.testing import CliRunner

        from clerk.cli import cli

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))

        # Track what gets called
        calls = []

        class TrackingExtractor:
            def __init__(self, site, config):
                self.site = site

            def extract(self):
                calls.append("extract")

        class TrackingTransformer:
            def __init__(self, site, config):
                self.site = site

            def transform(self):
                calls.append("transform")

        class TrackingLoader:
            def __init__(self, site, config):
                self.site = site

            def load(self):
                calls.append("load")

        class TrackingPlugin:
            from clerk import hookimpl

            @hookimpl
            def extractor_class(self, label):
                if label == "tracking":
                    return TrackingExtractor
                return None

            @hookimpl
            def transformer_class(self, label):
                if label == "tracking":
                    return TrackingTransformer
                return None

            @hookimpl
            def loader_class(self, label):
                if label == "tracking":
                    return TrackingLoader
                return None

        # Register plugin
        from clerk.utils import pm

        pm.register(TrackingPlugin())

        # Create civic.db with pipeline-configured site
        civic_db = sqlite_utils.Database("civic.db")
        civic_db["sites"].insert(
            {
                "subdomain": "pipeline-test.civic.band",
                "name": "Pipeline Test",
                "state": "CA",
                "country": "US",
                "kind": "council",
                "scraper": None,
                "pages": 0,
                "start_year": 2020,
                "extra": "{}",
                "status": "new",
                "last_updated": None,
                "lat": "0",
                "lng": "0",
                "pipeline": json.dumps({
                    "extractor": "tracking",
                    "transformer": "tracking",
                    "loader": "tracking",
                }),
            },
            pk="subdomain",
        )

        # Create site directory
        site_dir = tmp_storage_dir / "pipeline-test.civic.band"
        site_dir.mkdir()

        runner = CliRunner()
        result = runner.invoke(cli, ["update", "-s", "pipeline-test.civic.band"])

        # Should have called ETL methods in order
        assert "extract" in calls
        assert "transform" in calls
        assert "load" in calls
        assert calls.index("extract") < calls.index("transform") < calls.index("load")

    def test_update_uses_fetcher_when_no_pipeline(
        self, tmp_path, tmp_storage_dir, monkeypatch, mock_plugin_manager, cli_module
    ):
        """Test that update uses old fetcher when site has no pipeline."""
        import sqlite_utils
        from click.testing import CliRunner

        from clerk.cli import cli

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "STORAGE_DIR", str(tmp_storage_dir))
        monkeypatch.setattr(cli_module, "pm", mock_plugin_manager)

        # Create civic.db with scraper-only site (no pipeline)
        civic_db = sqlite_utils.Database("civic.db")
        civic_db["sites"].insert(
            {
                "subdomain": "scraper-test.civic.band",
                "name": "Scraper Test",
                "state": "CA",
                "country": "US",
                "kind": "council",
                "scraper": "test_scraper",
                "pages": 0,
                "start_year": 2020,
                "extra": None,
                "status": "new",
                "last_updated": None,
                "lat": "0",
                "lng": "0",
                "pipeline": None,  # No pipeline
            },
            pk="subdomain",
        )

        # Create site directory
        site_dir = tmp_storage_dir / "scraper-test.civic.band"
        site_dir.mkdir()

        runner = CliRunner()
        result = runner.invoke(cli, ["update", "-s", "scraper-test.civic.band"])

        # Should complete (uses mock fetcher)
        assert result.exit_code == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::TestETLPipelineIntegration -v`

Expected: FAIL (pipeline not integrated yet)

**Step 3: Integrate ETL pipeline into update command**

Modify `src/clerk/cli.py`. Update the imports and `update_site_internal` function:

At the top, add import:
```python
from .pipeline import get_pipeline_components
```

Replace the `update_site_internal` function (around line 108-175) with:

```python
@logfire.instrument("update_site", extract_args=True)
def update_site_internal(
    subdomain,
    next_site=False,
    all_years=False,
    skip_fetch=False,
    all_agendas=False,
    backfill=False,
):
    db = assert_db_exists()
    logfire.info(
        "Starting site update", subdomain=subdomain, all_years=all_years, all_agendas=all_agendas
    )

    query_normal = (
        "select subdomain from sites where status = 'deployed' order by last_updated asc limit 1"
    )
    query_backfill = "select subdomain from sites order by last_updated asc limit 1"

    query = query_normal
    if backfill:
        query = query_backfill

    # Get site to operate on
    if next_site:
        num_sites_in_ocr = db.execute(
            "select count(*) from sites where status = 'needs_ocr'"
        ).fetchone()[0]
        if num_sites_in_ocr >= 5:
            click.echo("Too many sites in progress. Going to sleep.")
            return
        subdomain_query = db.execute(query).fetchone()
        if not subdomain_query:
            click.echo("No more sites to update today")
            return
        subdomain = subdomain_query[0]
    site = db["sites"].get(subdomain)  # type: ignore
    if not site:
        click.echo("No site found matching criteria")
        return

    click.echo(f"Updating site {site['subdomain']}")

    # Get pipeline components (new ETL or old fetcher via adapter)
    from .adapter import FetcherAdapter

    components = get_pipeline_components(site)
    config = json.loads(site.get("extra") or "{}")

    if isinstance(components, FetcherAdapter):
        # Old-style fetcher path
        if not skip_fetch:
            fetch_internal(subdomain, components.fetcher)
        components.transform()
        components.load()
    else:
        # New ETL pipeline path
        ExtractorClass = components["extractor"]
        TransformerClass = components["transformer"]
        LoaderClass = components["loader"]

        if not skip_fetch:
            extractor = ExtractorClass(site, config)
            db["sites"].update(  # type: ignore
                subdomain,
                {
                    "status": "extracting",
                    "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )
            extractor.extract()

        transformer = TransformerClass(site, config)
        db["sites"].update(  # type: ignore
            subdomain,
            {
                "status": "transforming",
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
        transformer.transform()

        loader = LoaderClass(site, config)
        db["sites"].update(  # type: ignore
            subdomain,
            {
                "status": "loading",
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
        loader.load()

    update_page_count(subdomain)
    db["sites"].update(  # type: ignore
        subdomain,
        {
            "status": "needs_deploy",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    site = db["sites"].get(subdomain)  # type: ignore
    rebuild_site_fts_internal(subdomain)
    pm.hook.deploy_municipality(subdomain=subdomain)
    db["sites"].update(  # type: ignore
        subdomain,
        {
            "status": "deployed",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    pm.hook.post_deploy(site=site)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::TestETLPipelineIntegration -v`

Expected: All tests PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`

Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/clerk/cli.py tests/test_cli.py
git commit -m "feat: integrate ETL pipeline into update command

Update command now:
- Uses new ETL pipeline when site has pipeline JSON config
- Falls back to old fetcher via FetcherAdapter for backward compat
- Tracks status through extracting/transforming/loading stages"
```

---

### Task 7: Export new modules from package

**Files:**
- Modify: `src/clerk/__init__.py`

**Step 1: Update package exports**

Modify `src/clerk/__init__.py`:

```python
import logfire

from .adapter import FetcherAdapter as FetcherAdapter
from .cli import cli as cli
from .defaults import GenericLoader as GenericLoader
from .defaults import IdentityTransformer as IdentityTransformer
from .hookspecs import ClerkSpec as ClerkSpec
from .hookspecs import hookimpl as hookimpl
from .hookspecs import hookspec as hookspec
from .pipeline import get_pipeline_components as get_pipeline_components
from .pipeline import lookup_extractor as lookup_extractor
from .pipeline import lookup_loader as lookup_loader
from .pipeline import lookup_transformer as lookup_transformer
from .plugin_loader import load_plugins_from_directory as load_plugins_from_directory
from .utils import pm as pm

# Initialize Logfire
logfire.configure()

# Instrument SQLite
logfire.instrument_sqlite3()


def main() -> None:
    cli()
```

**Step 2: Verify tests still pass**

Run: `uv run pytest tests/ -v`

Expected: All tests PASS

**Step 3: Commit**

```bash
git add src/clerk/__init__.py
git commit -m "feat: export ETL components from package

Export FetcherAdapter, IdentityTransformer, GenericLoader,
and pipeline lookup functions for plugin authors."
```

---

### Task 8: Update documentation

**Files:**
- Modify: `docs/plugin-development.md`
- Modify: `docs/plans/2025-12-04-etl-architecture-design.md`

**Step 1: Update plugin development guide**

Add new section to `docs/plugin-development.md` after the existing "Available Hooks" section:

```markdown
## ETL Pipeline Hooks

Clerk supports a flexible ETL (Extract-Transform-Load) architecture for data pipelines. Instead of using the monolithic `fetcher_class` hook, you can provide separate components for each stage.

### extractor_class

Provide a class to extract/download data.

```python
@hookimpl
def extractor_class(self, label: str):
    """Return an extractor class for the given label.

    Args:
        label: The extractor label from site's pipeline config

    Returns:
        An extractor class or None
    """
    if label == "my_api":
        return MyAPIExtractor
    return None
```

**Extractor Interface:**

```python
class MyExtractor:
    def __init__(self, site: dict, config: dict):
        """Initialize the extractor.

        Args:
            site: Site configuration from civic.db
            config: Extra configuration (parsed from site's extra field)
        """
        self.site = site
        self.config = config

    def extract(self) -> None:
        """Download/extract data.

        Write files to: {STORAGE_DIR}/{subdomain}/extracted/
        """
        pass
```

### transformer_class

Provide a class to transform extracted data.

```python
@hookimpl
def transformer_class(self, label: str):
    """Return a transformer class for the given label."""
    if label == "normalize_budget":
        return BudgetNormalizer
    return None
```

**Transformer Interface:**

```python
class MyTransformer:
    def __init__(self, site: dict, config: dict):
        self.site = site
        self.config = config

    def transform(self) -> None:
        """Transform extracted data.

        Read from: {STORAGE_DIR}/{subdomain}/extracted/
        Write to: {STORAGE_DIR}/{subdomain}/transformed/
        """
        pass
```

### loader_class

Provide a class to load transformed data into the database.

```python
@hookimpl
def loader_class(self, label: str):
    """Return a loader class for the given label."""
    if label == "budget_tables":
        return BudgetLoader
    return None
```

**Loader Interface:**

```python
class MyLoader:
    def __init__(self, site: dict, config: dict):
        self.site = site
        self.config = config

    def load(self) -> None:
        """Load transformed data to database.

        Read from: {STORAGE_DIR}/{subdomain}/transformed/
        Write to: {STORAGE_DIR}/{subdomain}/data.db

        The loader owns the database schema - create whatever
        tables you need.
        """
        pass
```

### Site Configuration

Configure sites to use ETL pipelines via the `pipeline` JSON field:

```json
{
  "subdomain": "oakland-budget.civic.band",
  "pipeline": "{\"extractor\": \"socrata_api\", \"transformer\": \"budget_normalize\", \"loader\": \"budget_tables\"}"
}
```

### Default Components

If you don't specify a transformer or loader, clerk uses defaults:

- **IdentityTransformer**: No-op, data passes through unchanged
- **GenericLoader**: Loads CSV/JSON files from transformed/ to database tables

```json
{
  "pipeline": "{\"extractor\": \"my_api\"}"
}
```

This uses `my_api` extractor with default transformer and loader.

### Backward Compatibility

Existing sites with `scraper` field (no `pipeline`) continue to work. The old fetcher is automatically wrapped in a `FetcherAdapter`.
```

**Step 2: Update design doc status**

Change status in `docs/plans/2025-12-04-etl-architecture-design.md`:

```markdown
**Status:** Implemented
```

**Step 3: Commit**

```bash
git add docs/plugin-development.md docs/plans/2025-12-04-etl-architecture-design.md
git commit -m "docs: document ETL pipeline hooks and update design status"
```

---

### Task 9: Lint and final verification

**Step 1: Run linter**

Run: `uv run ruff check src/clerk/ tests/`

Fix any issues.

**Step 2: Run formatter**

Run: `uv run ruff format src/ tests/`

**Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`

Expected: All tests PASS

**Step 4: Commit if changes**

```bash
git add -A
git commit -m "style: format and lint ETL code"
```

---

## Summary

After completing all tasks:

1. Three new hooks: `extractor_class`, `transformer_class`, `loader_class`
2. `pipeline` JSON column in sites table for ETL configuration
3. Default components: `IdentityTransformer`, `GenericLoader`
4. `FetcherAdapter` for backward compatibility with old fetchers
5. `update` command uses ETL pipeline when site has `pipeline` config
6. Full backward compatibility for existing sites with `scraper` field
7. Documentation updated for plugin authors
