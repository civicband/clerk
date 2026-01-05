# ReadTheDocs Setup Design

**Date:** 2026-01-04
**Status:** Approved

## Overview

Add comprehensive ReadTheDocs documentation for clerk with a five-section structure: Getting Started, User Guide, Developer Guide, API Reference, and Design Documents. Use Sphinx with MyST parser to keep existing Markdown files while gaining autodoc and other Sphinx features.

## Goals

1. **Comprehensive documentation site** with tutorials, API docs, and guides
2. **Auto-generated API reference** from docstrings
3. **Reuse existing Markdown** documentation without conversion
4. **Quick initial launch** with essentials, expand over time
5. **Transparent design history** by including plans/ directory

## Documentation Structure

### Five Main Sections

1. **Getting Started** - Installation & tutorials (hybrid: README overview + detailed tutorials)
2. **User Guide** - Features & workflows (placeholder initially)
3. **Developer Guide** - Architecture, plugins, testing (existing docs)
4. **API Reference** - Auto-generated module documentation
5. **Design Documents** - Project evolution (plans/ directory)

### Directory Layout

```
docs/
├── conf.py                    # Sphinx configuration
├── index.md                   # Main landing page
├── requirements.txt           # Build dependencies
├── _static/                   # Custom CSS/images
├── getting-started/
│   ├── index.md              # Overview (from README)
│   ├── installation.md       # Detailed install
│   ├── quickstart.md         # First site tutorial
│   └── basic-usage.md        # Common workflows
├── user-guide/
│   ├── index.md              # Placeholder with links
│   └── (future: features, workflows, CLI reference)
├── developer-guide/
│   ├── index.md              # Overview
│   ├── architecture.md       # ← existing file
│   ├── plugin-development.md # ← existing file
│   ├── testing.md            # ← existing file
│   ├── DEVELOPMENT.md        # ← existing file
│   └── ocr-logging.md        # ← existing file
├── api/
│   ├── index.md              # API overview
│   ├── cli.md                # clerk.cli reference
│   ├── fetcher.md            # clerk.fetcher reference
│   ├── db.md                 # clerk.db reference
│   └── hookspecs.md          # clerk.hookspecs reference
└── design-docs/
    ├── index.md              # Design doc catalog
    └── plans/                # ← existing directory
```

## Technical Architecture

### Sphinx with MyST Parser

**Why this approach:**
- Keep existing Markdown files (no conversion needed)
- Full Sphinx capabilities (autodoc, cross-references, themes)
- Easy to write new docs in Markdown

### Dependencies (docs/requirements.txt)

```txt
sphinx>=7.0
myst-parser>=2.0              # Markdown support
sphinx-autodoc-typehints>=1.24
sphinx-rtd-theme>=2.0         # Read the Docs theme
```

### Sphinx Configuration (docs/conf.py)

**Key configuration:**

```python
# Project info
project = 'clerk'
author = 'Philip James'

# Extensions
extensions = [
    'myst_parser',                  # Markdown support
    'sphinx.ext.autodoc',           # Auto API docs
    'sphinx.ext.napoleon',          # Google/NumPy docstrings
    'sphinx.ext.viewcode',          # Source code links
    'sphinx_autodoc_typehints',     # Type hint support
]

# MyST parser config
myst_enable_extensions = [
    "colon_fence",    # ::: fences
    "deflist",        # Definition lists
    "linkify",        # Auto-link URLs
]

# Autodoc config
autodoc_default_options = {
    'members': True,
    'show-inheritance': True,
}
```

### ReadTheDocs Build Configuration (.readthedocs.yaml)

Already provided by ReadTheDocs:

```yaml
version: 2

build:
  os: ubuntu-24.04
  tools:
    python: "3.13"

sphinx:
   configuration: docs/conf.py

python:
   install:
   - requirements: docs/requirements.txt
```

## Content Organization

### Main Landing Page (docs/index.md)

- Brief introduction from README
- Navigation to all five sections
- `toctree` for Sphinx navigation

### Getting Started Section

**Content:**
- `index.md` - Overview from README (features, why clerk)
- `installation.md` - Detailed installation instructions
  - Base installation
  - Optional dependencies (PDF, extraction, Vision)
  - System requirements
- `quickstart.md` - Tutorial: Create first site, run pipeline
- `basic-usage.md` - Common CLI commands and workflows

**Approach:** Hybrid - reuse README for overview, add detailed tutorials

### User Guide Section

**Initial state:** Placeholder with links

**Content:**
- `index.md` - Brief intro + links to:
  - Most useful current docs
  - GitHub README
  - List of planned topics

**Future expansion:**
- Features guide
- Workflow examples
- CLI command reference
- Configuration guide

### Developer Guide Section

**Content:** All existing top-level docs organized here

- `index.md` - Overview of contributing, testing, architecture
- `architecture.md` - System design and component overview
- `plugin-development.md` - Writing custom fetchers and deployers
- `testing.md` - Test strategy and guidelines
- `DEVELOPMENT.md` - Development environment setup
- `ocr-logging.md` - OCR implementation details

**Approach:** Move existing files into this section, add overview index

### API Reference Section

**Scope:** Core user-facing modules only

**Modules documented:**
- `clerk.cli` - CLI commands and helpers
- `clerk.fetcher` - Fetcher base class and utilities
- `clerk.db` - Database functions
- `clerk.hookspecs` - ClerkSpec with all plugin hooks

**Generation approach:**

Each module gets auto-generated page using Sphinx autodoc:

```markdown
# docs/api/cli.md
```{eval-rst}
.. automodule:: clerk.cli
   :members:
   :undoc-members:
   :show-inheritance:
```
```

**Why these modules:**
- Focus on what users and plugin developers actually interact with
- Excludes internal utilities
- Provides complete interface documentation

### Design Documents Section

**Purpose:** Show project evolution and design decisions

**Organization:**

```markdown
# docs/design-docs/index.md

Introduction explaining these are historical design docs.

Organized by topic:
- Architecture Decisions
- Feature Designs (OCR, extraction, caching)
- Implementation Plans

Auto-generated list from plans/ with:
- Date (from filename)
- Title (from first heading)
- Brief description
```

**Approach:** Keep plans/ as-is, add catalog index that links to all docs

## Build Process

1. ReadTheDocs pulls from main branch
2. Installs Python 3.13 on Ubuntu 24.04
3. Installs dependencies from `docs/requirements.txt`
4. Runs `sphinx-build` using `docs/conf.py`
5. Autodoc imports `clerk.*` modules and generates API docs from docstrings
6. Publishes to `clerk.readthedocs.io`

## Implementation Strategy

### New Content to Write

- `docs/conf.py` - Sphinx configuration
- `docs/requirements.txt` - Build dependencies
- `docs/index.md` - Main landing page
- `docs/getting-started/index.md` - Overview from README
- `docs/getting-started/installation.md` - Detailed installation
- `docs/getting-started/quickstart.md` - First site tutorial
- `docs/getting-started/basic-usage.md` - Common workflows
- `docs/user-guide/index.md` - Placeholder with future plans
- `docs/developer-guide/index.md` - Developer overview
- `docs/api/index.md` - API overview
- `docs/api/cli.md` - clerk.cli autodoc template
- `docs/api/fetcher.md` - clerk.fetcher autodoc template
- `docs/api/db.md` - clerk.db autodoc template
- `docs/api/hookspecs.md` - clerk.hookspecs autodoc template
- `docs/design-docs/index.md` - Design doc catalog

### Existing Content to Move/Organize

- `docs/architecture.md` → `docs/developer-guide/architecture.md`
- `docs/plugin-development.md` → `docs/developer-guide/plugin-development.md`
- `docs/testing.md` → `docs/developer-guide/testing.md`
- `docs/DEVELOPMENT.md` → `docs/developer-guide/DEVELOPMENT.md`
- `docs/ocr-logging.md` → `docs/developer-guide/ocr-logging.md`
- `docs/plans/*` → Referenced from `docs/design-docs/index.md`

### Phased Approach

**Phase 1: Initial Launch** (this implementation)
- Complete Getting Started with tutorials
- Auto-generated API Reference
- Placeholder User Guide
- Organized Developer Guide (existing docs)
- Design Documents catalog

**Phase 2: Expansion** (future)
- Comprehensive User Guide (features, workflows, CLI reference)
- More tutorials and examples
- Enhanced API documentation with examples
- Contribution guide

## Success Criteria

- Documentation builds successfully on ReadTheDocs
- All five sections accessible and navigable
- API reference auto-generates from docstrings
- Existing docs integrated without conversion
- Getting Started tutorials guide new users effectively
- Design documents searchable and browsable

## Technical Considerations

### MyST Parser Features

Using MyST allows:
- Standard Markdown syntax
- Sphinx directives via ` ```{directive} ` syntax
- Cross-references between docs
- Auto-linking to API docs

### Autodoc Requirements

- Modules must be importable during build
- May need to mock heavy dependencies (weasyprint, etc.)
- Docstrings should follow Google or NumPy style
- Type hints will be automatically documented

### Theme

Using `sphinx-rtd-theme` (Read the Docs theme) for:
- Familiar documentation look
- Mobile responsive
- Search functionality
- Easy navigation

## Future Enhancements

- Version selector (when releasing stable versions)
- Examples gallery
- Tutorial videos/GIFs
- Interactive API examples
- Downloadable PDF version
- Localization (if needed)

## Related Documents

- README.md - Current project overview
- docs/architecture.md - System architecture
- docs/plugin-development.md - Plugin development guide
- All files in docs/plans/ - Design history
