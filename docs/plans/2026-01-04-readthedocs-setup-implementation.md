# ReadTheDocs Setup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Set up comprehensive ReadTheDocs documentation site with Sphinx, MyST parser, and auto-generated API docs.

**Architecture:** Five-section documentation structure (Getting Started, User Guide, Developer Guide, API Reference, Design Documents) using Sphinx with MyST parser to keep existing Markdown files while gaining autodoc capabilities.

**Tech Stack:** Sphinx 7.0+, MyST parser 2.0+, sphinx-autodoc-typehints, sphinx-rtd-theme

---

## Task 1: Create Sphinx Configuration

**Files:**
- Create: `docs/conf.py`
- Create: `docs/requirements.txt`
- Create: `docs/_static/.gitkeep`

**Step 1: Create docs/requirements.txt**

```txt
sphinx>=7.0
myst-parser>=2.0
sphinx-autodoc-typehints>=1.24
sphinx-rtd-theme>=2.0
```

**Step 2: Create docs/_static/.gitkeep**

```
# Empty file to preserve directory structure
```

**Step 3: Create docs/conf.py**

```python
"""Sphinx configuration for clerk documentation."""

import os
import sys

# Add src directory to path for autodoc
sys.path.insert(0, os.path.abspath("../src"))

# Project information
project = "clerk"
author = "Philip James"
copyright = "2026, Philip James"
release = "0.0.1"

# General configuration
extensions = [
    "myst_parser",  # Markdown support
    "sphinx.ext.autodoc",  # Auto API docs
    "sphinx.ext.napoleon",  # Google/NumPy docstrings
    "sphinx.ext.viewcode",  # Source code links
    "sphinx_autodoc_typehints",  # Type hint support
]

# MyST parser configuration
myst_enable_extensions = [
    "colon_fence",  # ::: fences
    "deflist",  # Definition lists
    "linkify",  # Auto-link URLs
]

# Templates and static files
templates_path = ["_templates"]
html_static_path = ["_static"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# HTML output configuration
html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 4,
    "collapse_navigation": False,
}

# Autodoc configuration
autodoc_default_options = {
    "members": True,
    "show-inheritance": True,
    "undoc-members": True,
}

# Napoleon settings for docstring parsing
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
```

**Step 4: Test Sphinx build**

Run: `cd docs && sphinx-build -b html . _build/html`
Expected: Build should fail with "index.rst not found" or similar (we haven't created index yet)

**Step 5: Commit**

```bash
git add docs/conf.py docs/requirements.txt docs/_static/.gitkeep
git commit -m "Add Sphinx configuration and dependencies"
```

---

## Task 2: Create Main Landing Page

**Files:**
- Create: `docs/index.md`

**Step 1: Create docs/index.md**

```markdown
# clerk Documentation

A Python library for managing civic data pipelines for civic.band. Clerk handles the complete workflow of fetching, processing, and deploying civic meeting data including minutes and agendas.

## Features

- **Site Management**: Create and manage civic sites with metadata
- **Data Pipeline**: Automated fetch → OCR → transform → deploy workflow
- **Plugin System**: Extensible architecture using pluggy for custom fetchers and deployers
- **Full-Text Search**: Automatic FTS index generation for searchable meeting data
- **Database Management**: SQLite-based storage with per-site and aggregate databases
- **Observability**: Built-in tracing and monitoring with Pydantic Logfire

## Documentation Sections

```{toctree}
:maxdepth: 2
:caption: Contents

getting-started/index
user-guide/index
developer-guide/index
api/index
design-docs/index
```

## Quick Links

- [Installation Guide](getting-started/installation.md)
- [Quick Start Tutorial](getting-started/quickstart.md)
- [API Reference](api/index.md)
- [Plugin Development](developer-guide/plugin-development.md)

## Project Links

- **GitHub**: [civicband/clerk](https://github.com/civicband/clerk)
- **Issues**: [Report a bug](https://github.com/civicband/clerk/issues)
- **civic.band**: [https://civic.band](https://civic.band)
```

**Step 2: Test Sphinx build**

Run: `cd docs && sphinx-build -b html . _build/html`
Expected: Build should succeed but warn about missing toctree references

**Step 3: Commit**

```bash
git add docs/index.md
git commit -m "Add main documentation landing page"
```

---

## Task 3: Create Getting Started Section Structure

**Files:**
- Create: `docs/getting-started/index.md`
- Create: `docs/getting-started/installation.md`
- Create: `docs/getting-started/quickstart.md`
- Create: `docs/getting-started/basic-usage.md`

**Step 1: Create docs/getting-started/index.md**

```markdown
# Getting Started

Welcome to clerk! This section will help you get up and running quickly.

## What is clerk?

Clerk is a Python library for managing civic data pipelines. It automates the process of:
- Fetching meeting data from municipal websites
- Processing PDFs with OCR
- Extracting structured data
- Deploying to hosting platforms

## Why clerk?

- **Automated Pipeline**: Complete workflow from fetch to deploy
- **Extensible**: Plugin system for custom fetchers and deployers
- **Searchable**: Built-in full-text search
- **Observable**: Integrated monitoring and logging

## Next Steps

```{toctree}
:maxdepth: 1

installation
quickstart
basic-usage
```

Start with [Installation](installation.md) to set up clerk, then follow the [Quick Start](quickstart.md) tutorial to create your first site.
```

**Step 2: Create docs/getting-started/installation.md**

```markdown
# Installation

## Requirements

- Python 3.12 or higher
- pip or uv package manager

## Basic Installation

Install clerk using pip or uv:

```bash
# Using uv (recommended)
uv pip install clerk

# Using pip
pip install clerk
```

## Optional Dependencies

Clerk has optional features that require additional dependencies:

### PDF Processing

For PDF generation and processing:

```bash
uv pip install clerk[pdf]
```

Includes:
- weasyprint - HTML to PDF conversion
- pdfkit - PDF toolkit
- pdf2image - Convert PDFs to images
- pypdf - PDF manipulation

### Text Extraction

For entity and vote extraction with spaCy:

```bash
uv pip install clerk[extraction]
```

Then download the spaCy language model:

```bash
python -m spacy download en_core_web_md
export ENABLE_EXTRACTION=1
```

### Vision Framework (macOS only)

For faster OCR on Apple Silicon:

```bash
uv pip install clerk[vision]
```

Requires macOS 10.15+ (M1+ recommended for best performance).

### All Features

Install everything:

```bash
uv pip install clerk[pdf,extraction,vision]
```

## Development Installation

For contributing to clerk:

```bash
# Clone repository
git clone https://github.com/civicband/clerk.git
cd clerk

# Install with development dependencies
uv pip install -e ".[dev]"

# Set up pre-commit hooks (optional)
pre-commit install
```

## Verification

Verify installation:

```bash
clerk --version
```

## Next Steps

Once installed, proceed to the [Quick Start](quickstart.md) tutorial.
```

**Step 3: Create docs/getting-started/quickstart.md**

```markdown
# Quick Start Tutorial

This tutorial walks through creating your first site and running the data pipeline.

## Prerequisites

- Clerk installed (see [Installation](installation.md))
- Basic familiarity with command line

## Step 1: Create a New Site

Create a new civic site:

```bash
clerk new
```

You'll be prompted for:

- **Subdomain**: e.g., `berkeleyca.civic.band`
- **Municipality name**: e.g., `Berkeley`
- **State**: e.g., `CA`
- **Country**: e.g., `USA`
- **Site type**: e.g., `city-council`
- **Scraper type**: Name of your fetcher plugin
- **Start year**: e.g., `2020`
- **Coordinates**: Latitude and longitude

This creates a site entry in the civic.db database and a directory structure at `../sites/berkeleyca.civic.band/`.

## Step 2: Fetch Meeting Data

Update the site to fetch data:

```bash
clerk update --subdomain berkeleyca.civic.band
```

This runs the complete pipeline:
1. Fetches meeting data using the configured scraper
2. Processes PDFs with OCR
3. Extracts text content
4. Stores in local database

### Update Options

```bash
# Fetch all historical data
clerk update --subdomain berkeleyca.civic.band --all-years

# Update next site that needs updating (for cron jobs)
clerk update --next-site
```

## Step 3: Build Database

Build the searchable database from extracted text:

```bash
# Fast build (no entity extraction)
clerk build-db-from-text --subdomain berkeleyca.civic.band

# With entity extraction (slower)
clerk build-db-from-text --subdomain berkeleyca.civic.band --with-extraction
```

This creates `meetings.db` with full-text search enabled.

## Step 4: Extract Entities (Optional)

For entity and vote extraction, run separately:

```bash
clerk extract-entities --subdomain berkeleyca.civic.band
```

This is memory-intensive (~5GB) and runs as a background job.

## Step 5: Build Aggregate Database

Combine all sites into one searchable database:

```bash
clerk build-full-db
```

Creates `../sites/meetings.db` with all sites combined.

## What's Next?

- Learn about [Basic Usage](basic-usage.md) patterns
- Explore the [Plugin System](../developer-guide/plugin-development.md)
- Review [Architecture](../developer-guide/architecture.md)
```

**Step 4: Create docs/getting-started/basic-usage.md**

```markdown
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
```

**Step 5: Test Sphinx build**

Run: `cd docs && sphinx-build -b html . _build/html`
Expected: Build succeeds, Getting Started section renders correctly

**Step 6: Commit**

```bash
git add docs/getting-started/
git commit -m "Add Getting Started documentation section"
```

---

## Task 4: Create User Guide Placeholder

**Files:**
- Create: `docs/user-guide/index.md`

**Step 1: Create docs/user-guide/index.md**

```markdown
# User Guide

The User Guide provides comprehensive information about clerk's features and workflows.

## Status

This section is currently being developed. For now, please refer to:

- [Getting Started](../getting-started/index.md) - Installation and tutorials
- [Basic Usage](../getting-started/basic-usage.md) - Common CLI commands
- [README](https://github.com/civicband/clerk/blob/main/README.md) - Project overview

## Planned Topics

The following topics will be added to this section:

### Features
- Site management in detail
- Data pipeline configuration
- OCR backends and options
- Entity and vote extraction
- Full-text search capabilities
- Caching and performance

### Workflows
- Setting up automated updates
- Batch processing multiple sites
- Troubleshooting common issues
- Monitoring and observability
- Backup and recovery

### CLI Reference
- Complete command reference
- Configuration options
- Environment variables
- Plugin system usage

### Advanced Topics
- Database schema and migrations
- Custom extraction rules
- Performance tuning
- Multi-database architecture

## Contributing

If you'd like to help develop this documentation, please see the [contribution guide](https://github.com/civicband/clerk/blob/main/CONTRIBUTING.md).
```

**Step 2: Test Sphinx build**

Run: `cd docs && sphinx-build -b html . _build/html`
Expected: Build succeeds, User Guide placeholder renders

**Step 3: Commit**

```bash
git add docs/user-guide/index.md
git commit -m "Add User Guide placeholder section"
```

---

## Task 5: Reorganize Developer Guide

**Files:**
- Create: `docs/developer-guide/index.md`
- Move: `docs/architecture.md` → `docs/developer-guide/architecture.md`
- Move: `docs/plugin-development.md` → `docs/developer-guide/plugin-development.md`
- Move: `docs/testing.md` → `docs/developer-guide/testing.md`
- Move: `docs/DEVELOPMENT.md` → `docs/developer-guide/DEVELOPMENT.md`
- Move: `docs/ocr-logging.md` → `docs/developer-guide/ocr-logging.md`

**Step 1: Create docs/developer-guide/index.md**

```markdown
# Developer Guide

Guide for contributing to clerk and developing plugins.

## Overview

This section covers clerk's architecture, development workflows, and how to extend clerk with custom plugins.

## Contents

```{toctree}
:maxdepth: 2

DEVELOPMENT
architecture
plugin-development
testing
ocr-logging
```

## Quick Links

- [Development Setup](DEVELOPMENT.md) - Set up your development environment
- [Architecture](architecture.md) - System design and components
- [Plugin Development](plugin-development.md) - Create custom fetchers and deployers
- [Testing](testing.md) - Test strategy and guidelines
- [OCR Logging](ocr-logging.md) - OCR implementation details

## Contributing

Contributions are welcome! Please see our [contribution guidelines](https://github.com/civicband/clerk/blob/main/CONTRIBUTING.md).

### Development Workflow

1. Fork and clone the repository
2. Set up development environment (see [DEVELOPMENT.md](DEVELOPMENT.md))
3. Create a feature branch
4. Make your changes with tests
5. Run tests and linting
6. Submit a pull request

### Code Standards

- Follow PEP 8 style guidelines
- Write tests for new features
- Document public APIs
- Keep commits focused and atomic
```

**Step 2: Move existing documentation files**

Run: `git mv docs/architecture.md docs/developer-guide/architecture.md`
Run: `git mv docs/plugin-development.md docs/developer-guide/plugin-development.md`
Run: `git mv docs/testing.md docs/developer-guide/testing.md`
Run: `git mv docs/DEVELOPMENT.md docs/developer-guide/DEVELOPMENT.md`
Run: `git mv docs/ocr-logging.md docs/developer-guide/ocr-logging.md`

**Step 3: Test Sphinx build**

Run: `cd docs && sphinx-build -b html . _build/html`
Expected: Build succeeds, Developer Guide section with all existing docs renders correctly

**Step 4: Commit**

```bash
git add docs/developer-guide/
git commit -m "Reorganize documentation into Developer Guide section"
```

---

## Task 6: Create API Reference Section

**Files:**
- Create: `docs/api/index.md`
- Create: `docs/api/cli.md`
- Create: `docs/api/fetcher.md`
- Create: `docs/api/db.md`
- Create: `docs/api/hookspecs.md`

**Step 1: Create docs/api/index.md**

```markdown
# API Reference

Auto-generated API documentation for clerk's core modules.

## Overview

This section provides detailed API documentation for clerk's user-facing modules. Documentation is automatically generated from docstrings in the source code.

## Core Modules

```{toctree}
:maxdepth: 2

cli
fetcher
db
hookspecs
```

### [CLI Module](cli.md)

Command-line interface and CLI utilities. Contains all clerk commands and helpers.

### [Fetcher Module](fetcher.md)

Base fetcher class and utilities for creating custom data fetchers.

### [Database Module](db.md)

Database operations and utilities for working with civic.db and site databases.

### [Hookspecs Module](hookspecs.md)

Plugin hook specifications. Defines the ClerkSpec interface for implementing plugins.

## Usage

Each module page includes:
- Class and function signatures
- Parameter types and descriptions
- Return types
- Docstring documentation
- Source code links

## For Plugin Developers

If you're developing plugins, focus on:
- [Fetcher Module](fetcher.md) - Extend `Fetcher` base class
- [Hookspecs Module](hookspecs.md) - Implement `ClerkSpec` hooks
- [Developer Guide](../developer-guide/plugin-development.md) - Complete plugin tutorial
```

**Step 2: Create docs/api/cli.md**

````markdown
# CLI Module

Command-line interface for clerk.

```{eval-rst}
.. automodule:: clerk.cli
   :members:
   :undoc-members:
   :show-inheritance:
```
````

**Step 3: Create docs/api/fetcher.md**

````markdown
# Fetcher Module

Base fetcher class and utilities.

```{eval-rst}
.. automodule:: clerk.fetcher
   :members:
   :undoc-members:
   :show-inheritance:
```
````

**Step 4: Create docs/api/db.md**

````markdown
# Database Module

Database operations and utilities.

```{eval-rst}
.. automodule:: clerk.db
   :members:
   :undoc-members:
   :show-inheritance:
```
````

**Step 5: Create docs/api/hookspecs.md**

````markdown
# Hookspecs Module

Plugin hook specifications.

```{eval-rst}
.. automodule:: clerk.hookspecs
   :members:
   :undoc-members:
   :show-inheritance:
```
````

**Step 6: Test Sphinx build**

Run: `cd docs && sphinx-build -b html . _build/html`
Expected: Build succeeds, API docs auto-generated from source code docstrings

**Step 7: Commit**

```bash
git add docs/api/
git commit -m "Add API Reference section with autodoc templates"
```

---

## Task 7: Create Design Documents Section

**Files:**
- Create: `docs/design-docs/index.md`

**Step 1: Read existing plans to understand content**

Run: `ls docs/plans/ | head -10`
Expected: List of plan files like `2026-01-04-readthedocs-setup-design.md`

**Step 2: Create docs/design-docs/index.md**

```markdown
# Design Documents

Historical design documents showing clerk's evolution and decision-making process.

## Overview

This section contains design documents created during clerk's development. These documents provide insight into:
- Architectural decisions
- Feature designs
- Implementation approaches
- Problem-solving processes

## Purpose

Design documents serve multiple purposes:
- **Transparency**: Show how and why features were built
- **Context**: Provide background for future development
- **Learning**: Demonstrate design thinking and trade-offs
- **History**: Document the project's evolution

## Documents by Category

### Architecture & Infrastructure

Documents covering system design and infrastructure decisions.

### Feature Designs

Designs for specific features like OCR processing, entity extraction, and caching.

### Implementation Plans

Detailed step-by-step plans for implementing features.

## All Design Documents

The following documents are available in the [plans directory](https://github.com/civicband/clerk/tree/main/docs/plans):

```{toctree}
:maxdepth: 1
:glob:

plans/*
```

## Using These Documents

When working on clerk:
1. Review related design docs before starting new features
2. Understand the context and constraints that shaped decisions
3. Build on existing patterns and approaches
4. Create new design docs for significant changes

## Contributing Design Documents

New design documents should:
- Be created during the brainstorming phase
- Include clear goals and success criteria
- Document alternatives considered
- Explain trade-offs and decisions
- Be saved as `docs/plans/YYYY-MM-DD-<topic>-design.md`
```

**Step 3: Test Sphinx build**

Run: `cd docs && sphinx-build -b html . _build/html`
Expected: Build succeeds, Design Documents section includes all plans/ files

**Step 4: Commit**

```bash
git add docs/design-docs/index.md
git commit -m "Add Design Documents catalog section"
```

---

## Task 8: Verify Local Build

**Files:**
- None (verification only)

**Step 1: Install documentation dependencies**

Run: `uv pip install -r docs/requirements.txt`
Expected: Installs sphinx, myst-parser, sphinx-autodoc-typehints, sphinx-rtd-theme

**Step 2: Clean previous builds**

Run: `cd docs && rm -rf _build/`
Expected: Removes any cached builds

**Step 3: Build documentation**

Run: `cd docs && sphinx-build -b html . _build/html`
Expected: Build succeeds with no errors, only warnings for missing docstrings

**Step 4: Verify HTML output**

Run: `ls docs/_build/html/index.html`
Expected: File exists

**Step 5: Check for broken links in main sections**

Run: `ls docs/_build/html/getting-started/index.html`
Run: `ls docs/_build/html/user-guide/index.html`
Run: `ls docs/_build/html/developer-guide/index.html`
Run: `ls docs/_build/html/api/index.html`
Run: `ls docs/_build/html/design-docs/index.html`
Expected: All section index files exist

**Step 6: Open in browser (manual verification)**

Run: `open docs/_build/html/index.html` (macOS) or `xdg-open docs/_build/html/index.html` (Linux)
Expected: Documentation opens in browser, all sections navigable

**Step 7: Document verification steps**

Create a simple verification checklist in commit message:
- [ ] Main landing page loads
- [ ] All 5 sections accessible
- [ ] Getting Started tutorials render
- [ ] API Reference autodoc works
- [ ] Developer Guide includes all moved docs
- [ ] Design Documents catalog shows plans/

---

## Task 9: Update Root README

**Files:**
- Modify: `README.md`

**Step 1: Read current README to find documentation section**

Run: `grep -n "Documentation" README.md`
Expected: Shows line number of documentation section (around line 357-361)

**Step 2: Update README documentation links**

Modify the "Links" section at the end of README.md to include ReadTheDocs:

```markdown
## Links

- **Documentation**: https://clerk.readthedocs.io (or [local docs](docs/))
- **Issues**: https://github.com/civicband/clerk/issues
- **civic.band**: https://civic.band
```

**Step 3: Verify README renders correctly**

Run: `cat README.md | tail -20`
Expected: Shows updated links section

**Step 4: Commit**

```bash
git add README.md
git commit -m "Update README with ReadTheDocs link"
```

---

## Task 10: Add Build Verification to CI (Optional)

**Files:**
- Create: `.github/workflows/docs.yml`

**Step 1: Create docs CI workflow**

```yaml
name: Documentation

on:
  push:
    branches: [main]
    paths:
      - 'docs/**'
      - 'src/clerk/**'
      - '.github/workflows/docs.yml'
  pull_request:
    branches: [main]
    paths:
      - 'docs/**'
      - 'src/clerk/**'
      - '.github/workflows/docs.yml'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.13'

      - name: Install uv
        run: pip install uv

      - name: Install dependencies
        run: |
          uv pip install --system -r docs/requirements.txt
          uv pip install --system -e .

      - name: Build documentation
        run: |
          cd docs
          sphinx-build -W -b html . _build/html

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: documentation
          path: docs/_build/html
```

**Step 2: Test workflow locally (if act is installed)**

Run: `act -j build` (if act is installed)
Expected: Workflow runs successfully or skip if act not available

**Step 3: Commit**

```bash
git add .github/workflows/docs.yml
git commit -m "Add documentation build verification to CI"
```

---

## Task 11: Final Integration Test

**Files:**
- None (verification only)

**Step 1: Run all tests to ensure nothing broke**

Run: `PYTHONPATH=src uv run pytest -v`
Expected: All 193+ tests pass

**Step 2: Rebuild documentation from scratch**

Run: `cd docs && rm -rf _build/ && sphinx-build -b html . _build/html`
Expected: Clean build succeeds

**Step 3: Verify all sections load**

Run: `find docs/_build/html -name "index.html" | sort`
Expected: Shows all section index pages

**Step 4: Check for sphinx warnings**

Run: `cd docs && sphinx-build -W -b html . _build/html 2>&1 | grep -i warning | head -20`
Expected: Only warnings about missing docstrings (acceptable for now)

**Step 5: Create completion summary**

Document what was built:
- ✅ Sphinx configuration with MyST parser
- ✅ Five-section documentation structure
- ✅ Getting Started with tutorials
- ✅ User Guide placeholder
- ✅ Developer Guide (reorganized existing docs)
- ✅ API Reference with autodoc
- ✅ Design Documents catalog
- ✅ Local build verified
- ✅ CI verification (optional)

---

## Post-Implementation

### Testing the ReadTheDocs Build

After merging to main:

1. Push changes to GitHub
2. ReadTheDocs will automatically build from `.readthedocs.yaml`
3. Verify build at https://readthedocs.org/projects/clerk/
4. Check published docs at https://clerk.readthedocs.io

### Potential Issues

**Mock imports needed:**
If autodoc fails because of heavy dependencies (weasyprint, etc.), add to `docs/conf.py`:

```python
autodoc_mock_imports = [
    "weasyprint",
    "pdfkit",
    "pdf2image",
    "pypdf",
    "spacy",
]
```

**Missing docstrings:**
If autodoc generates empty pages, add docstrings to modules:

```python
"""Module docstring describing what this module does."""
```

**Path issues:**
If modules can't be imported, verify `sys.path` in `conf.py` points to `../src`.

### Future Enhancements

- Add more tutorials to Getting Started
- Expand User Guide with comprehensive feature docs
- Add examples to API documentation
- Create contribution guide
- Add architecture diagrams
- Set up doc versioning (when releasing v1.0)
