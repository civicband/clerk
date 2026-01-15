# Basic Usage

Common workflows and CLI commands for working with clerk.

## Site Management

### Create New Site

```bash
clerk new
```

Interactive prompt to create a new site.

### Update Site

```bash
# Specific site
clerk update --subdomain example.civic.band

# Next site needing update
clerk update --next-site

# All historical data
clerk update --subdomain example.civic.band --all-years
```

### Auto-Scheduling Sites

The auto-scheduler ensures all sites update approximately once per day:

```bash
# Run via cron every minute to auto-enqueue oldest site
clerk update --next-site
```

This command:
- Finds the site with the oldest `last_updated` timestamp
- Skips sites updated within the last 23 hours
- Enqueues the oldest eligible site with normal priority
- Exits silently if all sites are recently updated

### Manual vs Auto Priority

**High priority** (processed first):
- New sites: `clerk new <subdomain>`
- Manual updates: `clerk update -s <subdomain>`

**Normal priority** (processed after high queue empty):
- Auto-scheduler: `clerk update --next-site`
- Bulk operations: `clerk enqueue site1 site2 site3`

## Database Operations

### Build from Text

```bash
# Fast build (uses cached entity extractions)
clerk build-db-from-text --subdomain example.civic.band

# Extract entities for uncached pages
clerk build-db-from-text --subdomain example.civic.band --extract-entities

# Re-extract all pages (ignore cache)
clerk build-db-from-text --subdomain example.civic.band --extract-entities --ignore-cache
```

### Entity Extraction

```bash
# Specific site
clerk extract-entities --subdomain example.civic.band

# Next site needing extraction
clerk extract-entities --next-site
```

### Aggregate Database

```bash
clerk build-full-db
```

Builds a combined database from all sites. The FTS (full-text search) index is automatically rebuilt as part of this process.

## OCR Processing

OCR is handled automatically as part of the `update` command. You can choose the OCR backend:

### Update with Tesseract (default)

```bash
clerk update --subdomain example.civic.band
```

### Update with Vision Framework (macOS)

```bash
clerk update --subdomain example.civic.band --ocr-backend vision
```

Vision Framework is 3-5x faster on Apple Silicon and automatically falls back to Tesseract if it fails.

## Configuration

### Environment Variables

Create `.env` file:

```bash
# Storage location
STORAGE_DIR=../sites

# Enable entity extraction
ENABLE_EXTRACTION=1

# Extraction confidence threshold (0.0-1.0)
ENTITY_CONFIDENCE_THRESHOLD=0.7

# Parallel processing (1-4)
SPACY_N_PROCESS=2

# PDF chunk size
PDF_CHUNK_SIZE=20

# Logfire (optional)
LOGFIRE_TOKEN=your_token_here
```

### Plugin Loading

Load custom plugins:

```bash
clerk --plugins-dir=/path/to/plugins update --subdomain example.civic.band
```

## Common Workflows

### Daily Update (Cron)

```bash
# Every 6 hours: update next site
0 */6 * * * clerk update --next-site

# Every 30 minutes: extract entities
*/30 * * * * clerk extract-entities --next-site
```

### Initial Site Setup

```bash
# 1. Create site
clerk new

# 2. Fetch all data
clerk update --subdomain example.civic.band --all-years

# 3. Build database (fast)
clerk build-db-from-text --subdomain example.civic.band

# 4. Extract entities (background)
clerk extract-entities --subdomain example.civic.band
```

### Rebuild After Changes

```bash
# 1. Rebuild database (FTS index is automatically rebuilt)
clerk build-db-from-text --subdomain example.civic.band

# 2. Build aggregate database
clerk build-full-db
```

## Next Steps

- [Plugin Development](../developer-guide/plugin-development.md) - Create custom fetchers
- [Architecture](../developer-guide/architecture.md) - Understand the system
- [API Reference](../api/index.md) - Detailed API documentation
