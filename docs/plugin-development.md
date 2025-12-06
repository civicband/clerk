# Plugin Development Guide

This guide explains how to create plugins for Clerk to extend its functionality.

## Overview

Clerk uses [pluggy](https://pluggy.readthedocs.io/) for its plugin system. Plugins can provide:
- Custom data fetchers for different municipal systems
- Deployment strategies for various hosting platforms
- File upload handlers for CDN/storage
- Custom post-processing hooks

## Quick Start

### Basic Plugin Structure

```python
from clerk import hookimpl

class MyPlugin:
    """My custom Clerk plugin."""

    @hookimpl
    def fetcher_class(self, label: str):
        """Provide a custom fetcher class."""
        if label == "my_system":
            return MyCustomFetcher
        return None

    @hookimpl
    def deploy_municipality(self, subdomain: str):
        """Handle deployment for this municipality."""
        print(f"Deploying {subdomain}")
        # Your deployment logic here
```

### Registering Your Plugin

**Option 1: Direct Registration**

```python
from clerk.utils import pm
from my_plugin import MyPlugin

pm.register(MyPlugin())
```

**Option 2: Package Entry Points**

In your plugin package's `pyproject.toml`:

```toml
[project.entry-points."civicband.clerk"]
my_plugin = "my_plugin_package:MyPlugin"
```

Then users can discover and load your plugin automatically.

## Available Hooks

### fetcher_class

Provide a custom fetcher class for a specific scraper type.

```python
@hookimpl
def fetcher_class(self, label: str):
    """Return a fetcher class for the given scraper type.

    Args:
        label: The scraper type from site['scraper']

    Returns:
        A fetcher class or None
    """
    if label == "legistar":
        return LegistarFetcher
    elif label == "granicus":
        return GranicusFetcher
    return None
```

**Fetcher Interface:**

Your fetcher class must implement:

```python
class MyFetcher:
    def __init__(self, site: dict, start_year: int, all_agendas: bool):
        """Initialize the fetcher.

        Args:
            site: Site configuration from civic.db
            start_year: Year to start fetching from
            all_agendas: Whether to fetch all agendas
        """
        self.site = site
        self.start_year = start_year
        self.all_agendas = all_agendas

    def fetch_events(self):
        """Download meeting data (PDFs, HTML, etc.)."""
        # Download files to:
        # {STORAGE_DIR}/{subdomain}/pdfs/
        pass

    def ocr(self):
        """Extract text from downloaded documents."""
        # Save text files to:
        # {STORAGE_DIR}/{subdomain}/txt/{meeting}/{date}/{page}.txt
        # {STORAGE_DIR}/{subdomain}/_agendas/txt/{meeting}/{date}/{page}.txt
        pass

    def transform(self):
        """Build database from extracted text."""
        from clerk.cli import build_db_from_text_internal
        build_db_from_text_internal(self.site['subdomain'])
```

### fetcher_extra

Provide additional configuration for fetchers.

```python
@hookimpl
def fetcher_extra(self, label: str):
    """Return extra configuration for a fetcher.

    Args:
        label: The scraper type

    Returns:
        Dictionary of extra config or None
    """
    if label == "legistar":
        return {
            "base_url": "https://api.legistar.com",
            "api_key": os.environ.get("LEGISTAR_API_KEY"),
        }
    return None
```

### deploy_municipality

Handle deployment of municipality files.

```python
@hookimpl
def deploy_municipality(self, subdomain: str):
    """Deploy municipality files to hosting.

    Args:
        subdomain: The municipality subdomain (e.g., 'berkeleyca.civic.band')
    """
    import shutil
    from pathlib import Path

    # Example: Copy to web server directory
    source = Path(f"../sites/{subdomain}")
    dest = Path(f"/var/www/{subdomain}")

    if dest.exists():
        shutil.rmtree(dest)

    shutil.copytree(source, dest)
    print(f"Deployed {subdomain} to {dest}")
```

### post_deploy

Run actions after successful deployment.

```python
@hookimpl
def post_deploy(self, site: dict):
    """Actions to run after deployment.

    Args:
        site: Complete site record from civic.db
    """
    import requests

    # Example: Ping a webhook
    requests.post("https://example.com/webhook", json={
        "event": "deployment",
        "subdomain": site['subdomain'],
        "timestamp": site['last_updated'],
    })

    # Example: Update an RSS feed
    update_rss_feed(site)

    # Example: Clear CDN cache
    clear_cdn_cache(site['subdomain'])
```

### upload_static_file

Upload files to CDN or cloud storage.

```python
@hookimpl
def upload_static_file(self, file_path: str, storage_path: str):
    """Upload a static file to CDN/storage.

    Args:
        file_path: Local path to the file
        storage_path: Destination path in storage
    """
    import boto3

    s3 = boto3.client('s3')
    bucket = 'my-civic-data-bucket'

    with open(file_path, 'rb') as f:
        s3.upload_fileobj(f, bucket, storage_path)

    print(f"Uploaded {file_path} to s3://{bucket}/{storage_path}")
```

### post_create

Run actions after creating a new site.

```python
@hookimpl
def post_create(self, subdomain: str):
    """Actions to run after site creation.

    Args:
        subdomain: The newly created subdomain
    """
    # Example: Create DNS record
    create_dns_record(subdomain)

    # Example: Initialize hosting
    setup_hosting(subdomain)

    # Example: Send notification
    notify_admin(f"New site created: {subdomain}")
```

## Complete Example: Legistar Plugin

Here's a complete plugin for Legistar-based municipalities:

```python
"""Legistar plugin for Clerk."""

import os
import requests
from pathlib import Path
from clerk import hookimpl


class LegistarFetcher:
    """Fetcher for Legistar API."""

    def __init__(self, site: dict, start_year: int, all_agendas: bool):
        self.site = site
        self.start_year = start_year
        self.all_agendas = all_agendas
        self.base_url = f"https://webapi.legistar.com/v1/{site['extra']['client']}"

    def fetch_events(self):
        """Fetch events from Legistar API."""
        # Get all events since start_year
        events = requests.get(
            f"{self.base_url}/events",
            params={"$filter": f"EventDate ge {self.start_year}-01-01"}
        ).json()

        # Download minutes PDFs
        for event in events:
            self.download_minutes(event)

            if self.all_agendas:
                self.download_agenda(event)

    def download_minutes(self, event):
        """Download minutes PDF for an event."""
        # Implementation details...
        pass

    def download_agenda(self, event):
        """Download agenda PDF for an event."""
        # Implementation details...
        pass

    def ocr(self):
        """Run OCR on downloaded PDFs."""
        # Use pdf2text or similar
        pass

    def transform(self):
        """Build database from text."""
        from clerk.cli import build_db_from_text_internal
        build_db_from_text_internal(self.site['subdomain'])


class LegistarPlugin:
    """Plugin for Legistar-based municipalities."""

    @hookimpl
    def fetcher_class(self, label: str):
        if label == "legistar":
            return LegistarFetcher
        return None

    @hookimpl
    def fetcher_extra(self, label: str):
        if label == "legistar":
            return {
                "base_url": "https://webapi.legistar.com/v1",
            }
        return None


# Auto-register if imported
from clerk.utils import pm
pm.register(LegistarPlugin())
```

## Testing Your Plugin

Create tests for your plugin:

```python
"""Tests for my plugin."""

import pytest
from clerk.utils import pm
from my_plugin import MyPlugin


def test_plugin_registration():
    """Test that plugin can be registered."""
    plugin = MyPlugin()
    pm.register(plugin)

    # Verify plugin is registered
    assert plugin in pm.get_plugins()


def test_fetcher_class_hook(mock_site):
    """Test fetcher_class hook."""
    plugin = MyPlugin()
    mock_site['scraper'] = 'my_system'

    fetcher_class = plugin.fetcher_class('my_system')
    assert fetcher_class is not None

    fetcher = fetcher_class(mock_site, 2020, False)
    assert hasattr(fetcher, 'fetch_events')
    assert hasattr(fetcher, 'ocr')
    assert hasattr(fetcher, 'transform')
```

## Best Practices

1. **Error Handling**: Catch and log errors gracefully
   ```python
   @hookimpl
   def deploy_municipality(self, subdomain: str):
       try:
           # Deployment logic
           pass
       except Exception as e:
           import logfire
           logfire.error(f"Deployment failed for {subdomain}", error=str(e))
           raise
   ```

2. **Configuration**: Use environment variables or external config
   ```python
   @hookimpl
   def fetcher_extra(self, label: str):
       return {
           "api_key": os.environ.get("MY_API_KEY"),
           "base_url": os.environ.get("MY_BASE_URL", "https://default.com"),
       }
   ```

3. **Logging**: Use Logfire for observability
   ```python
   import logfire

   @hookimpl
   def deploy_municipality(self, subdomain: str):
       logfire.info("Starting deployment", subdomain=subdomain)
       # ... deployment logic ...
       logfire.info("Deployment complete", subdomain=subdomain)
   ```

4. **Idempotency**: Make operations idempotent when possible
   ```python
   def fetch_events(self):
       # Check if already fetched
       if self.already_fetched():
           return

       # Fetch new events
       self.download_events()
   ```

5. **Return None**: Always return `None` if your plugin doesn't handle a label
   ```python
   @hookimpl
   def fetcher_class(self, label: str):
       if label == "my_type":
           return MyFetcher
       return None  # Important!
   ```

## Publishing Your Plugin

1. **Create a package:**
   ```
   my-clerk-plugin/
   ├── pyproject.toml
   ├── README.md
   └── my_clerk_plugin/
       ├── __init__.py
       └── plugin.py
   ```

2. **Configure entry points in `pyproject.toml`:**
   ```toml
   [project]
   name = "my-clerk-plugin"
   version = "0.1.0"
   dependencies = ["clerk"]

   [project.entry-points."civicband.clerk"]
   my_plugin = "my_clerk_plugin:MyPlugin"
   ```

3. **Publish to PyPI:**
   ```bash
   pip install build twine
   python -m build
   twine upload dist/*
   ```

## Plugin Discovery

Clerk automatically discovers plugins from a `./plugins/` directory in the current working directory.

### Directory Structure

```
my-project/
├── civic.db
├── plugins/
│   ├── my_fetcher.py
│   └── my_deploy.py
└── sites/
```

### Creating a Plugin

Create a Python file in the `./plugins/` directory with a class that uses the `@hookimpl` decorator:

```python
# plugins/my_fetcher.py
from clerk import hookimpl

class MyFetcherPlugin:
    @hookimpl
    def fetcher_class(self, label):
        if label == "my_fetcher":
            from .my_fetcher_impl import MyFetcher
            return MyFetcher
        return None
```

Clerk will automatically:
1. Scan `./plugins/` for `.py` files
2. Import each file
3. Find classes with `@hookimpl` methods
4. Instantiate and register them

### Custom Plugins Directory

Use `--plugins-dir` to load plugins from a different location:

```bash
clerk --plugins-dir ./my-plugins update -s foo.civic.band
```

### Error Handling

Clerk fails fast on plugin errors. If a plugin file has:
- Syntax errors
- Import errors
- Instantiation errors

Clerk will exit with a clear error message rather than silently skipping the plugin.

## ETL Pipeline Architecture

Clerk supports a flexible Extract-Transform-Load (ETL) pipeline for handling different data formats. While the old-style `fetcher_class` approach works well for document-heavy workflows (PDFs → text → database), the ETL pipeline supports structured data like spreadsheets.

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

Data flows between stages via the filesystem for caching and resumability.

### ETL Hooks

#### extractor_class

Provide a custom extractor for a data source.

```python
@hookimpl
def extractor_class(self, label: str):
    """Return an extractor class for the given label.

    Args:
        label: The extractor type from site['pipeline']['extractor']

    Returns:
        An extractor class or None
    """
    if label == "socrata_api":
        return SocrataExtractor
    return None
```

**Extractor Interface:**

```python
class MyExtractor:
    def __init__(self, site: dict, config: dict):
        """Initialize the extractor.

        Args:
            site: Site configuration from civic.db
            config: Extra config from site['extra'] parsed as JSON
        """
        self.site = site
        self.config = config

    def extract(self) -> None:
        """Download/extract data.

        Write files to:
        {STORAGE_DIR}/{subdomain}/extracted/
        """
        pass
```

#### transformer_class

Provide a custom transformer for data processing.

```python
@hookimpl
def transformer_class(self, label: str):
    """Return a transformer class for the given label.

    Args:
        label: The transformer type from site['pipeline']['transformer']

    Returns:
        A transformer class or None
    """
    if label == "budget_normalize":
        return BudgetTransformer
    return None
```

**Transformer Interface:**

```python
class MyTransformer:
    def __init__(self, site: dict, config: dict):
        """Initialize the transformer.

        Args:
            site: Site configuration from civic.db
            config: Extra config from site['extra'] parsed as JSON
        """
        self.site = site
        self.config = config

    def transform(self) -> None:
        """Transform extracted data.

        Read from: {STORAGE_DIR}/{subdomain}/extracted/
        Write to: {STORAGE_DIR}/{subdomain}/transformed/
        """
        pass
```

#### loader_class

Provide a custom loader for database operations.

```python
@hookimpl
def loader_class(self, label: str):
    """Return a loader class for the given label.

    Args:
        label: The loader type from site['pipeline']['loader']

    Returns:
        A loader class or None
    """
    if label == "budget_tables":
        return BudgetLoader
    return None
```

**Loader Interface:**

```python
class MyLoader:
    def __init__(self, site: dict, config: dict):
        """Initialize the loader.

        Args:
            site: Site configuration from civic.db
            config: Extra config from site['extra'] parsed as JSON
        """
        self.site = site
        self.config = config

    def load(self) -> None:
        """Load transformed data into database.

        Read from: {STORAGE_DIR}/{subdomain}/transformed/
        Write to: {STORAGE_DIR}/{subdomain}/data.db (or meetings.db)
        """
        pass
```

### Default Components

Clerk provides default implementations:

- **IdentityTransformer**: No-op transformer (files pass through unchanged)
- **GenericLoader**: Loads CSV/JSON files from `transformed/` into database tables

Import these if you need them:

```python
from clerk import IdentityTransformer, GenericLoader
```

### Site Configuration

Sites use the new ETL pipeline when they have a `pipeline` JSON column:

```sql
UPDATE sites SET pipeline = '{"extractor": "socrata_api", "transformer": "budget_normalize", "loader": "budget_tables"}'
WHERE subdomain = 'oakland-budget.civic.band';
```

The pipeline JSON supports:
- `extractor`: Required label for the extractor
- `transformer`: Optional (defaults to IdentityTransformer)
- `loader`: Optional (defaults to GenericLoader)

### Complete ETL Plugin Example

```python
"""Budget data pipeline plugin."""

import csv
import os
from pathlib import Path

import requests
import sqlite_utils
from clerk import hookimpl

STORAGE_DIR = os.environ.get("STORAGE_DIR", "../sites")


class SocrataExtractor:
    """Extract budget data from Socrata open data portal."""

    def __init__(self, site: dict, config: dict):
        self.site = site
        self.api_endpoint = config.get("socrata_endpoint")

    def extract(self) -> None:
        response = requests.get(self.api_endpoint)

        output_dir = Path(STORAGE_DIR) / self.site["subdomain"] / "extracted"
        output_dir.mkdir(parents=True, exist_ok=True)

        (output_dir / "budget.csv").write_text(response.text)


class BudgetTransformer:
    """Normalize budget data to standard schema."""

    def __init__(self, site: dict, config: dict):
        self.site = site

    def transform(self) -> None:
        subdomain = self.site["subdomain"]
        input_file = Path(STORAGE_DIR) / subdomain / "extracted" / "budget.csv"
        output_dir = Path(STORAGE_DIR) / subdomain / "transformed"
        output_dir.mkdir(parents=True, exist_ok=True)

        with open(input_file) as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({
                    "fiscal_year": row.get("FY") or row.get("fiscal_year"),
                    "department": row.get("Dept") or row.get("department"),
                    "category": row.get("Category") or row.get("expense_type"),
                    "amount": float(row.get("Amount") or row.get("budget_amount") or 0),
                })

        with open(output_dir / "budget_lines.csv", "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["fiscal_year", "department", "category", "amount"]
            )
            writer.writeheader()
            writer.writerows(rows)


class BudgetLoader:
    """Load budget data into database."""

    def __init__(self, site: dict, config: dict):
        self.site = site

    def load(self) -> None:
        subdomain = self.site["subdomain"]
        input_file = Path(STORAGE_DIR) / subdomain / "transformed" / "budget_lines.csv"
        db_path = Path(STORAGE_DIR) / subdomain / "data.db"

        db = sqlite_utils.Database(db_path)

        db["budget_lines"].insert_all(
            csv.DictReader(open(input_file)),
            pk="id",
            alter=True,
        )

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

### Backward Compatibility

Existing plugins using `fetcher_class` continue to work unchanged. Sites with a `scraper` field but no `pipeline` field automatically use the old-style fetcher path.

To migrate an existing fetcher to the new ETL system:

1. Split your fetcher into separate extractor, transformer, and loader classes
2. Register them with the appropriate hooks
3. Update site configuration from `scraper: "my_source"` to:
   ```json
   {"extractor": "my_source", "transformer": "my_format", "loader": "my_tables"}
   ```

## Examples

See the `examples/` directory for complete working examples:
- `examples/basic_plugin.py`: Minimal plugin
- `examples/custom_fetcher.py`: Custom fetcher implementation
