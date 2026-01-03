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

### update_site

React to or extend site updates in civic.db.

```python
@hookimpl
def update_site(self, subdomain: str, updates: dict):
    """Called when a site is updated in civic.db.

    Args:
        subdomain: The site subdomain (e.g., 'berkeleyca.civic.band')
        updates: Dictionary of fields being updated (e.g., {'status': 'deployed'})
    """
    # Your plugin logic here
    import logfire
    logfire.info("Site updated", subdomain=subdomain, updates=updates)
```

**Use cases:**
- Log all database changes for auditing
- Send webhooks on status changes
- Invalidate caches when data changes
- Update external systems when sites are modified

**Example: Status Change Webhook**

```python
@hookimpl
def update_site(self, subdomain: str, updates: dict):
    """Send webhook when site status changes."""
    if 'status' in updates:
        import requests
        requests.post(
            "https://example.com/webhook",
            json={
                "event": "status_change",
                "subdomain": subdomain,
                "new_status": updates['status'],
            }
        )
```

### create_site

React to new site creation.

```python
@hookimpl
def create_site(self, subdomain: str, site_data: dict):
    """Called when a new site is created in civic.db.

    Args:
        subdomain: The new site subdomain
        site_data: Complete site record being created
    """
    # Your plugin logic here
    import logfire
    logfire.info("Site created", subdomain=subdomain, site_data=site_data)
```

**Use cases:**
- Log new site creation for auditing
- Initialize external resources (DNS, hosting, etc.)
- Send notifications to admins
- Set up monitoring for new sites

**Example: Setup External Resources**

```python
@hookimpl
def create_site(self, subdomain: str, site_data: dict):
    """Initialize hosting and DNS for new site."""
    # Create DNS record
    create_dns_record(subdomain)

    # Initialize hosting directory
    setup_hosting_directory(subdomain)

    # Send notification
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

## Examples

See the `examples/` directory for complete working examples:
- `examples/basic_plugin.py`: Minimal plugin
- `examples/custom_fetcher.py`: Custom fetcher implementation
