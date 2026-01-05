# clerk

A Python library for managing civic data pipelines for civic.band. Clerk handles the complete workflow of fetching, processing, and deploying civic meeting data including minutes and agendas.

[![Tests](https://github.com/civicband/clerk/actions/workflows/test.yml/badge.svg)](https://github.com/civicband/clerk/actions/workflows/test.yml)
[![Lint](https://github.com/civicband/clerk/actions/workflows/lint.yml/badge.svg)](https://github.com/civicband/clerk/actions/workflows/lint.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

## Features

- **Site Management**: Create and manage civic sites with metadata
- **Data Pipeline**: Automated fetch → OCR → transform → deploy workflow
- **Plugin System**: Extensible architecture using pluggy for custom fetchers and deployers
- **Full-Text Search**: Automatic FTS index generation for searchable meeting data
- **Database Management**: SQLite-based storage with per-site and aggregate databases
- **Observability**: Built-in tracing and monitoring with Pydantic Logfire

## Installation

### For Users

```bash
uv pip install clerk
```

### Optional Features

Clerk has optional dependencies for PDF processing and text extraction:

```bash
# PDF processing (weasyprint, pdfkit, pdf2image, pypdf)
uv pip install clerk[pdf]

# Text extraction with spaCy NER
uv pip install clerk[extraction]

# Both
uv pip install clerk[pdf,extraction]

# From git
pip install "clerk[pdf,extraction] @ git+https://github.com/civicband/clerk.git"
```

**For extraction**, you also need to download the spaCy model and enable the feature:

```bash
python -m spacy download en_core_web_md
export ENABLE_EXTRACTION=1
```

### For Development

1. Clone the repository:
```bash
git clone https://github.com/civicband/clerk.git
cd clerk
```

2. Install with development dependencies:
```bash
just install
```

3. Set up pre-commit hooks (optional but recommended):
```bash
just pre-commit
```

## Quick Start

### Create a New Site

```bash
clerk new
```

You'll be prompted for:
- Subdomain (e.g., `berkeleyca.civic.band`)
- Municipality name
- State and country
- Site type (city-council, planning-commission, etc.)
- Scraper type
- Start year
- Geographic coordinates

### Update a Site

```bash
# Update a specific site
clerk update --subdomain example.civic.band

# Update the next site that needs updating
clerk update --next-site

# Update with all historical data
clerk update --subdomain example.civic.band --all-years
```

### Build Database from Text Files

```bash
# Fast build (skips entity/vote extraction)
clerk build-db-from-text --subdomain example.civic.band

# Include extraction during build (slower, ~20 minutes per site)
clerk build-db-from-text --subdomain example.civic.band --with-extraction
```

### Extract Entities and Votes

Entity and vote extraction runs as a separate background job for optimal memory usage:

```bash
# Extract entities for a specific site
clerk extract-entities --subdomain example.civic.band

# Process next site needing extraction (for cron jobs)
clerk extract-entities --next-site
```

For most workflows, run `build-db-from-text` first (fast), then `extract-entities` separately. This allows databases to be deployed immediately while extraction runs in the background.

### Build Aggregate Database

Combine all sites into a single searchable database:

```bash
clerk build-full-db
```

## OCR Processing

### Progress Tracking

OCR jobs display real-time progress and timing:

```bash
uv run clerk ocr --subdomain=example.ca.civic.band
```

Output:
```
OCR Progress: [25/100] 25.0% complete, 1 failed | ETA: 180s
OCR Progress: [50/100] 50.0% complete, 2 failed | ETA: 90s
...
OCR job ocr_1234567890 completed: 98 succeeded, 2 failed, 0 skipped (total: 100 documents in 120.5s)
Failure manifest written to: ../sites/example.ca.civic.band/ocr_failures_1234567890.jsonl
```

### Error Handling

Failed documents are logged with full context and recorded in a failure manifest for later retry. See [OCR Logging Documentation](docs/ocr-logging.md) for details.

## OCR Backends

Clerk supports two OCR backends:

### Tesseract (Default)

- **Cross-platform:** Linux, macOS, Windows
- **Languages:** 100+ languages supported
- **Setup:** Requires tesseract binary installed
- **Usage:** `clerk update example.com` (default) or `clerk update example.com --ocr-backend=tesseract`

### Vision Framework (macOS only)

- **Platform:** macOS 10.15+ (M1+ recommended)
- **Performance:** 3-5x faster than Tesseract on Apple Silicon
- **Languages:** Automatic language detection
- **Setup:** `pip install pyobjc-framework-Vision pyobjc-framework-Quartz`
- **Usage:** `clerk update example.com --ocr-backend=vision`

### Automatic Fallback

If Vision Framework is selected but fails (missing dependencies, errors), clerk automatically falls back to Tesseract and logs a warning.

```bash
# Try Vision, fall back to Tesseract if needed
clerk update example.com --ocr-backend=vision
```

## Architecture

Clerk uses a multi-database architecture:

- **civic.db**: Central database tracking all sites and their metadata
- **Per-site databases**: Individual `meetings.db` files containing minutes and agendas
- **Aggregate database**: Optional combined database at `STORAGE_DIR/meetings.db`

### Data Flow

```
1. Fetch → Download meeting data (via plugins)
2. OCR → Extract text from PDFs
3. Transform → Process text into structured data
4. Deploy → Publish to hosting (via plugins)
```

### Database Schema

**civic.db - sites table:**
- subdomain, name, state, country
- kind, scraper, pages, start_year
- status, last_updated
- lat, lng, extra
- extraction_status, last_extracted (entity extraction tracking)

**meetings.db - minutes/agendas tables:**
- id, meeting, date, page
- text, page_image
- entities_json, votes_json (extracted entities and votes)

### Sequential Extraction Workflow

Entity and vote extraction is designed to run as an independent background job, separating it from database building for better performance and resource management.

**Migration (one-time setup):**
```bash
clerk migrate-extraction-schema
```

This adds `extraction_status` and `last_extracted` columns to track extraction progress.

**Workflow:**

1. **Build database** (fast, seconds/minutes):
   ```bash
   clerk build-db-from-text --subdomain site.civic.band
   ```
   Creates database with text content, deploys immediately with searchable text.

2. **Extract entities** (slow, ~20 minutes, runs separately):
   ```bash
   clerk extract-entities --subdomain site.civic.band
   ```
   Processes entities and votes, updates database, redeploys with extracted data.

**For production (cron-based processing):**
```bash
# Run every 30 minutes to process sites sequentially
*/30 * * * * clerk extract-entities --next-site
```

**Extraction Status:**
- `pending`: Site needs extraction
- `in_progress`: Currently being processed
- `completed`: Extraction finished
- `failed`: Extraction failed, will retry

**Benefits:**
- Fast database builds (deploy sites immediately)
- Memory-efficient (~5GB per extraction vs ~10-20GB for parallel)
- Automatic retry for failed extractions
- Clear visibility into extraction progress

## Plugin System

Clerk uses [pluggy](https://pluggy.readthedocs.io/) for its plugin system. Plugins can implement:

- **fetcher_class**: Provide custom data fetchers
- **fetcher_extra**: Add extra configuration for fetchers
- **deploy_municipality**: Handle deployment
- **post_deploy**: Post-deployment actions
- **upload_static_file**: Upload files to CDN/storage
- **post_create**: Actions after site creation

See [docs/plugin-development.md](docs/plugin-development.md) for details.

## Configuration

### Environment Variables

- `STORAGE_DIR`: Base directory for site data (default: `../sites`)
- `ENABLE_EXTRACTION`: Set to `1` to enable spaCy-based entity and vote extraction
- `ENTITY_CONFIDENCE_THRESHOLD`: Minimum confidence for entity extraction (default: `0.7`)
- `SPACY_N_PROCESS`: Number of CPU cores for parallel spaCy processing (default: `2`).
  Set to `1` to minimize memory usage (~5GB) or `4` for maximum speed (~20GB memory).

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

### Logfire Configuration

Clerk includes Pydantic Logfire for observability:

```bash
# First time setup
logfire auth

# View traces at https://logfire.pydantic.dev
```

## Development

### Running Tests

```bash
# Run all tests
just test

# Run unit tests only
just test-unit

# Run integration tests only
just test-integration

# Run with verbose output
just test-v
```

### Code Quality

```bash
# Format code
just format

# Lint code (with auto-fix)
just lint-fix

# Type check
just typecheck

# Run all checks
just check
```

### Pre-commit Hooks

```bash
# Run pre-commit hooks manually
just pre-commit
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## License

BSD 3-Clause License - See [LICENSE](LICENSE) for details.

## Links

- **Documentation**: https://clerk.readthedocs.io (or [local docs](docs/))
- **Issues**: https://github.com/civicband/clerk/issues
- **civic.band**: https://civic.band
