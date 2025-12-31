# Clerk Architecture

This document describes the architecture and design of the Clerk library.

## Overview

Clerk is a Python library for managing civic data pipelines. It provides a complete workflow for:
1. Fetching meeting data from various sources
2. Processing and OCR of documents
3. Transforming data into structured databases
4. Deploying processed data to hosting platforms

## Core Components

### 1. CLI Layer (`cli.py`)

The CLI layer provides command-line interface using Click:

**Commands:**
- `new`: Create a new site
- `update`: Update site data
- `build-db-from-text`: Build database from processed text files
- `build-full-db`: Create aggregate database from all sites

**Key Functions:**
- `update_site_internal()`: Orchestrates the full pipeline
- `fetch_internal()`: Handles data fetching with status updates
- `build_db_from_text_internal()`: Converts text files to SQLite databases
- `rebuild_site_fts_internal()`: Rebuilds full-text search indexes

### 2. Plugin System (`hookspecs.py`, `plugins.py`)

Built on [pluggy](https://pluggy.readthedocs.io/), the plugin system allows external code to extend Clerk's functionality.

**Hook Specifications (ClerkSpec):**

```python
@hookspec
def fetcher_class(label: str):
    """Return a fetcher class for the given scraper type."""

@hookspec
def fetcher_extra(label: str):
    """Return extra configuration for a fetcher."""

@hookspec
def deploy_municipality(subdomain: str):
    """Deploy municipality files to hosting."""

@hookspec
def post_deploy(site: dict):
    """Actions to run after deployment."""

@hookspec
def upload_static_file(file_path: str, storage_path: str):
    """Upload a static file to CDN/storage."""

@hookspec
def post_create(subdomain: str):
    """Actions to run after site creation."""
```

**Plugin Discovery:**

Plugins register with the global plugin manager:

```python
from clerk.utils import pm
pm.register(MyPlugin())
```

### 3. Database Layer (`utils.py`)

**Database Structure:**

1. **civic.db** (Central database)
   - Location: Repository root
   - Tables:
     - `sites`: Metadata for all civic sites
     - `feed_entries`: RSS feed entries

2. **meetings.db** (Per-site databases)
   - Location: `{STORAGE_DIR}/{subdomain}/meetings.db`
   - Tables:
     - `minutes`: Meeting minutes text and metadata
     - `agendas`: Meeting agendas
     - `pages_*`: FTS virtual tables

3. **meetings.db** (Aggregate database)
   - Location: `{STORAGE_DIR}/meetings.db`
   - Combined data from all sites
   - Includes `subdomain` and `municipality` fields

**Schema Evolution:**

The `assert_db_exists()` function handles schema migrations using `table.transform(drop=...)` to remove deprecated columns.

### 4. Observability (`__init__.py`)

Logfire integration provides:
- Automatic SQLite query tracing
- Function execution tracing
- Performance metrics
- Custom contextual logging

Initialized on import:
```python
logfire.configure()
logfire.instrument_sqlite3()
```

## Data Flow

```
┌─────────────┐
│  CLI Input  │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│  Site Creation  │  ← Creates record in civic.db
│  (new command)  │  ← Calls post_create hook
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│  Fetch Phase    │  ← Gets fetcher from plugins
│  Status: new    │  ← Calls fetcher.fetch_events()
│  → fetching     │  ← Downloads PDFs/documents
│  → needs_ocr    │  ← Updates civic.db status
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│  OCR Phase      │  ← Calls fetcher.ocr()
│                 │  ← Extracts text from PDFs
│                 │  ← Saves to {subdomain}/txt/
│  → needs_extraction  ← Updates civic.db status
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ Transform Phase │  ← Calls fetcher.transform()
│                 │  ← Calls build_db_from_text()
│                 │  ← spaCy entity/vote extraction
│                 │  ← Creates meetings.db
│                 │  ← Generates record IDs (SHA256)
│  → needs_deploy │  ← Updates civic.db status
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│  FTS Indexing   │  ← rebuild_site_fts_internal()
│                 │  ← Creates searchable indexes
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ Deploy Phase    │  ← Calls deploy_municipality hook
│                 │  ← Uploads to hosting
│                 │  ← Calls post_deploy hook
│  → deployed     │  ← Updates civic.db status
└─────────────────┘
```

## Directory Structure

```
STORAGE_DIR/
├── {subdomain}/
│   ├── txt/                          # Minutes text files
│   │   ├── {meeting}/
│   │   │   ├── {date}/
│   │   │   │   ├── 1.txt
│   │   │   │   ├── 2.txt
│   │   │   │   └── ...
│   ├── _agendas/txt/                 # Agenda text files
│   │   ├── {meeting}/
│   │   │   ├── {date}/
│   │   │   │   ├── 1.txt
│   │   │   │   └── ...
│   └── meetings.db                   # Per-site database
├── meetings.db                       # Aggregate database
└── civic.db (in repo root)           # Central database
```

## Fetcher Interface

Custom fetchers must implement:

```python
class MyFetcher:
    def __init__(self, site: dict, start_year: int, all_agendas: bool):
        self.site = site
        self.start_year = start_year
        self.all_agendas = all_agendas

    def fetch_events(self):
        """Download meeting data."""
        pass

    def ocr(self):
        """Extract text from documents."""
        pass

    def transform(self):
        """Build database from extracted text."""
        # Often just calls build_db_from_text_internal()
        pass
```

## Status State Machine

Sites progress through these statuses:

```
new → fetching → needs_ocr → needs_extraction → needs_deploy → deployed
                                ↓
                          (errors/manual intervention)
```

## ID Generation

Record IDs are generated using SHA256 hashing:

```python
key_hash = {
    "kind": "minutes",  # or "agenda"
    "meeting": meeting_name,
    "date": date_string,
    "page": page_number,
    "text": content,
}
id = sha256(json.dumps(key_hash, sort_keys=True)).hexdigest()[:12]
```

This ensures:
- Deterministic IDs
- Deduplication
- Consistent record identification

## Error Handling

- Database operations use SQLite transactions
- Backups created before destructive operations
- FTS rebuild errors are logged but don't halt execution
- Plugin hook failures are caught and logged

## Performance Considerations

- **Bulk Inserts**: Uses `insert_all()` for efficient batch operations
- **FTS Indexes**: Created after all data is inserted
- **Database Backups**: Old databases copied before rebuilding
- **Lazy Plugin Loading**: Fetcher classes only imported when needed

## Extension Points

1. **Custom Fetchers**: Implement fetcher interface and register via plugin
2. **Custom Deployment**: Implement deploy hooks for different hosting
3. **Custom Processing**: Override transform logic in fetchers
4. **Additional Hooks**: Add new hook specifications as needed

## Testing Strategy

See [testing.md](testing.md) for details on:
- Unit tests with mocked dependencies
- Integration tests with real databases
- Fixture data and mock implementations
