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
clerk build-db-from-text --subdomain example.civic.band
```

### Build Aggregate Database

Combine all sites into a single searchable database:

```bash
clerk build-full-db
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

**meetings.db - minutes/agendas tables:**
- id, meeting, date, page
- text, page_image

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

- **Documentation**: [docs/](docs/)
- **Issues**: https://github.com/civicband/clerk/issues
- **civic.band**: https://civic.band
