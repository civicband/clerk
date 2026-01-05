# Basic Usage

Common workflows and CLI commands for working with clerk.

## Site Management

### List All Sites

```bash
clerk list
```

Shows all sites in civic.db with their status.

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

## Database Operations

### Build from Text

```bash
# Fast build (no extraction)
clerk build-db-from-text --subdomain example.civic.band

# With extraction
clerk build-db-from-text --subdomain example.civic.band --with-extraction

# Force fresh extraction (ignore cache)
clerk build-db-from-text --subdomain example.civic.band --force-extraction
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

### Rebuild Search Index

```bash
clerk rebuild-site-fts --subdomain example.civic.band
```

## OCR Processing

### OCR with Tesseract (default)

```bash
clerk ocr --subdomain example.civic.band
```

### OCR with Vision Framework (macOS)

```bash
clerk ocr --subdomain example.civic.band --ocr-backend=vision
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
# 1. Rebuild database
clerk build-db-from-text --subdomain example.civic.band

# 2. Rebuild search index
clerk rebuild-site-fts --subdomain example.civic.band

# 3. Build aggregate
clerk build-full-db
```

## Next Steps

- [Plugin Development](../developer-guide/plugin-development.md) - Create custom fetchers
- [Architecture](../developer-guide/architecture.md) - Understand the system
- [API Reference](../api/index.md) - Detailed API documentation
