# Clerk ETL Architecture Design

**Status:** Proposed

## Overview

Transform clerk into a civic-data optimized ETL tool with flexible Extract → Transform → Load pipelines, supporting both document-based workflows (PDFs → text → database) and structured data workflows (spreadsheets → tables).

## Current State

Clerk uses a single `fetcher_class` hook that returns a class implementing three methods:
- `fetch_events()` - Download documents
- `ocr()` - Extract text from documents
- `transform()` - Build database from text files

This works well for document-heavy workflows but doesn't accommodate structured data like spreadsheets, where OCR doesn't apply and the output schema differs.

## Desired State

A flexible ETL architecture where:
- Clerk orchestrates the pipeline
- Plugins provide interchangeable components (extractors, transformers, loaders)
- Components can be mixed and matched per site
- Existing fetcher-based plugins continue to work

## Architecture

### ETL Model

```
┌─────────────┐     ┌──────────────┐     ┌────────────┐
│  Extractor  │ ──► │  Transformer │ ──► │   Loader   │
│             │     │              │     │            │
│ fetch data  │     │ process data │     │ write to   │
│ write files │     │ write files  │     │ database   │
└─────────────┘     └──────────────┘     └────────────┘
      │                    │                    │
      ▼                    ▼                    ▼
   files on             files on            database
    disk                 disk               tables
```

**Key decisions:**
- **Clerk orchestrates** - calls each stage in sequence
- **Plugins provide components** - separate hooks for each stage
- **Files on disk** - data flows between stages via filesystem (for caching, resumability)
- **Loader owns schema** - each loader creates whatever tables it needs

### New Hook Specifications

```python
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
        transform(self) -> None  # reads extracted files, writes to STORAGE_DIR/{subdomain}/transformed/
    """

@hookspec
def loader_class(self, label):
    """Returns a loader class for the given label.

    Loader interface:
        __init__(self, site: dict, config: dict)
        load(self) -> None  # reads transformed files, creates tables, writes to DB
    """
```

### Site Schema Changes

Add a `pipeline` JSON column to the sites table:

```sql
ALTER TABLE sites ADD COLUMN pipeline TEXT;  -- JSON, nullable
```

Example configurations:

```json
// Full pipeline - explicit components
{"extractor": "socrata_api", "transformer": "budget_normalize", "loader": "budget_tables"}

// Partial pipeline - uses defaults for missing components
{"extractor": "socrata_api"}

// Legacy - no pipeline column, uses scraper field with adapter
// scraper: "legistar"
```

### Component Dispatch

When processing a site:

1. If `pipeline` JSON is set:
   - Look up each component by its label
   - Use defaults for missing components
2. If only `scraper` is set:
   - Use backward compatibility adapter (wraps old fetcher)

### Default Components

Clerk ships with default implementations:

**IdentityTransformer** - Passes files through unchanged:
```python
class IdentityTransformer:
    """Default transformer that does nothing."""

    def __init__(self, site: dict, config: dict):
        self.site = site

    def transform(self) -> None:
        pass  # Files pass through unchanged
```

**GenericLoader** - Loads CSV/JSON files to tables:
```python
class GenericLoader:
    """Default loader that creates tables from structured files."""

    def __init__(self, site: dict, config: dict):
        self.site = site
        self.config = config

    def load(self) -> None:
        # Reads files from transformed/ directory
        # Creates tables based on filename (e.g., budgets.csv -> budgets table)
        # Inserts data
```

### Backward Compatibility

Old-style fetchers work through an adapter:

```python
class FetcherAdapter:
    """Adapts old-style fetcher to new ETL interface."""

    def __init__(self, fetcher):
        self.fetcher = fetcher

    def extract(self):
        """Maps to fetch_events()."""
        self.fetcher.fetch_events()

    def transform(self):
        """Maps to ocr() + transform()."""
        self.fetcher.ocr()
        self.fetcher.transform()

    def load(self):
        """No-op - old transform() wrote directly to DB."""
        pass
```

Detection logic:
```python
def get_pipeline_components(site):
    if site.get("pipeline"):
        pipeline = json.loads(site["pipeline"])
        return {
            "extractor": lookup_extractor(pipeline.get("extractor")),
            "transformer": lookup_transformer(pipeline.get("transformer")) or IdentityTransformer,
            "loader": lookup_loader(pipeline.get("loader")) or GenericLoader,
        }
    elif site.get("scraper"):
        fetcher = get_fetcher(site)  # existing logic
        return FetcherAdapter(fetcher)
    else:
        raise ValueError("Site must have pipeline or scraper configured")
```

## Example: Budget Spreadsheet Pipeline

```python
# plugins/budget_pipeline.py
from clerk import hookimpl
import csv
import sqlite_utils
from pathlib import Path

STORAGE_DIR = os.environ.get("STORAGE_DIR", "../sites")


class SocrataExtractor:
    """Extract budget data from Socrata open data portal."""

    def __init__(self, site: dict, config: dict):
        self.site = site
        self.api_endpoint = site.get("extra", {}).get("socrata_endpoint")

    def extract(self) -> None:
        # Download CSV from Socrata API
        response = requests.get(self.api_endpoint)

        output_dir = Path(STORAGE_DIR) / self.site["subdomain"] / "extracted"
        output_dir.mkdir(parents=True, exist_ok=True)

        (output_dir / "budget.csv").write_text(response.text)


class BudgetTransformer:
    """Normalize budget data to standard schema."""

    def __init__(self, site: dict, config: dict):
        self.site = site

    def transform(self) -> None:
        input_file = Path(STORAGE_DIR) / self.site["subdomain"] / "extracted" / "budget.csv"
        output_dir = Path(STORAGE_DIR) / self.site["subdomain"] / "transformed"
        output_dir.mkdir(parents=True, exist_ok=True)

        with open(input_file) as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # Normalize to standard schema
                rows.append({
                    "fiscal_year": row.get("FY") or row.get("fiscal_year"),
                    "department": row.get("Dept") or row.get("department"),
                    "category": row.get("Category") or row.get("expense_type"),
                    "amount": float(row.get("Amount") or row.get("budget_amount") or 0),
                })

        with open(output_dir / "budget_lines.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["fiscal_year", "department", "category", "amount"])
            writer.writeheader()
            writer.writerows(rows)


class BudgetLoader:
    """Load budget data into database."""

    def __init__(self, site: dict, config: dict):
        self.site = site

    def load(self) -> None:
        input_file = Path(STORAGE_DIR) / self.site["subdomain"] / "transformed" / "budget_lines.csv"
        db_path = Path(STORAGE_DIR) / self.site["subdomain"] / "data.db"

        db = sqlite_utils.Database(db_path)

        # Loader owns schema - create table as needed
        db["budget_lines"].insert_all(
            csv.DictReader(open(input_file)),
            pk="id",
            alter=True,
        )

        # Enable FTS on relevant columns
        db["budget_lines"].enable_fts(["department", "category"])


class BudgetPipelinePlugin:
    """Plugin providing budget data pipeline components."""

    @hookimpl
    def extractor_class(self, label):
        if label == "socrata_api":
            return SocrataExtractor
        return None

    @hookimpl
    def transformer_class(self, label):
        if label == "budget_normalize":
            return BudgetTransformer
        return None

    @hookimpl
    def loader_class(self, label):
        if label == "budget_tables":
            return BudgetLoader
        return None
```

Site configuration:
```json
{
  "subdomain": "oakland-budget.civic.band",
  "name": "Oakland Budget",
  "pipeline": "{\"extractor\": \"socrata_api\", \"transformer\": \"budget_normalize\", \"loader\": \"budget_tables\"}",
  "extra": "{\"socrata_endpoint\": \"https://data.oaklandca.gov/resource/xyz.csv\"}"
}
```

## CLI Changes

The `update` command workflow becomes:

```python
def update_site_internal(subdomain, ...):
    site = db["sites"].get(subdomain)

    if site.get("pipeline"):
        # New ETL path
        pipeline = json.loads(site["pipeline"])
        config = json.loads(site.get("extra") or "{}")

        # Get components
        ExtractorClass = lookup_extractor(pipeline.get("extractor"))
        TransformerClass = lookup_transformer(pipeline.get("transformer")) or IdentityTransformer
        LoaderClass = lookup_loader(pipeline.get("loader")) or GenericLoader

        # Run pipeline
        extractor = ExtractorClass(site, config)
        extractor.extract()

        transformer = TransformerClass(site, config)
        transformer.transform()

        loader = LoaderClass(site, config)
        loader.load()
    else:
        # Legacy fetcher path (unchanged)
        fetcher = get_fetcher(site, all_years, all_agendas)
        fetcher.fetch_events()
        fetcher.ocr()
        fetcher.transform()

    # Common post-processing
    update_page_count(subdomain)
    pm.hook.deploy_municipality(subdomain=subdomain)
    pm.hook.post_deploy(site=site)
```

## Future Considerations

Not in scope for initial implementation:

- **Pipeline composition UI** - CLI command to build pipeline config interactively
- **Pipeline validation** - Check that extractor output matches transformer input expectations
- **Parallel execution** - Run independent pipeline stages concurrently
- **Incremental extraction** - Track what's been extracted to avoid re-downloading

---

## Migration Checklist

### For Clerk Maintainers (Core Changes)

- [ ] **Add new hooks to `hookspecs.py`**
  - [ ] Add `extractor_class(label)` hookspec
  - [ ] Add `transformer_class(label)` hookspec
  - [ ] Add `loader_class(label)` hookspec

- [ ] **Update site schema in `utils.py`**
  - [ ] Add `pipeline` column (TEXT, nullable) to sites table
  - [ ] Add migration in `assert_db_exists()` to add column to existing DBs

- [ ] **Create default components in `src/clerk/defaults.py`**
  - [ ] Implement `IdentityTransformer` class
  - [ ] Implement `GenericLoader` class
  - [ ] Register defaults with plugin manager

- [ ] **Create adapter in `src/clerk/adapter.py`**
  - [ ] Implement `FetcherAdapter` class
  - [ ] Add logic to wrap fetcher when `pipeline` is empty

- [ ] **Update CLI orchestration in `cli.py`**
  - [ ] Modify `update_site_internal()` to detect pipeline vs scraper
  - [ ] Add new orchestration path: extractor.extract() → transformer.transform() → loader.load()
  - [ ] Keep old path for scraper-only sites (via adapter)

- [ ] **Update `new` command**
  - [ ] Add prompts for pipeline components (optional)
  - [ ] Store in `pipeline` JSON column if provided
  - [ ] Fall back to `scraper` for backward compat

- [ ] **Add tests**
  - [ ] Test new hooks are called correctly
  - [ ] Test adapter wraps old fetchers
  - [ ] Test default components work
  - [ ] Test pipeline JSON parsing
  - [ ] Test mixed scenarios (some sites old, some new)

- [ ] **Update documentation**
  - [ ] Update `docs/plugin-development.md` with new interfaces
  - [ ] Add migration guide section
  - [ ] Document default components

### For Plugin Authors (Existing Plugins)

- [ ] **Option A: Do nothing (adapter handles it)**
  - Your existing `fetcher_class` hook continues to work
  - Sites using `scraper` field are automatically adapted
  - No code changes required

- [ ] **Option B: Migrate to new ETL hooks (optional)**
  - [ ] Split fetcher into separate classes:
    - [ ] `MyExtractor` with `extract()` method (was `fetch_events()`)
    - [ ] `MyTransformer` with `transform()` method (was `ocr()` + part of `transform()`)
    - [ ] `MyLoader` with `load()` method (was DB-writing part of `transform()`)
  - [ ] Register new hooks:
    ```python
    @hookimpl
    def extractor_class(self, label):
        if label == "my_source":
            return MyExtractor
        return None

    @hookimpl
    def transformer_class(self, label):
        if label == "my_format":
            return MyTransformer
        return None

    @hookimpl
    def loader_class(self, label):
        if label == "my_tables":
            return MyLoader
        return None
    ```
  - [ ] Update site config from `scraper: "my_source"` to:
    ```json
    {"extractor": "my_source", "transformer": "my_format", "loader": "my_tables"}
    ```

### For Clerk Users (Existing Deployments)

- [ ] **Upgrade clerk**
  - [ ] `pip install --upgrade clerk` (or `uv pip install --upgrade clerk`)

- [ ] **Database auto-migrates**
  - [ ] `pipeline` column added automatically on first run
  - [ ] Existing sites with `scraper` continue to work unchanged

- [ ] **No action required for existing sites**
  - Sites with `scraper` field use adapter automatically
  - Migrate sites to `pipeline` when convenient (optional)

- [ ] **To migrate a site to new system (optional)**
  - [ ] Update site record:
    ```sql
    UPDATE sites
    SET pipeline = '{"extractor": "...", "transformer": "...", "loader": "..."}'
    WHERE subdomain = 'mysite.civic.band';
    ```
  - [ ] Or use clerk command (when available):
    ```bash
    clerk migrate-site -s mysite.civic.band --extractor X --transformer Y --loader Z
    ```
