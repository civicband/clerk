# clerk-fetchers Package Design

## Overview

A separate Python package (`clerk-fetchers`) that provides community-contributed fetchers to clerk via its existing pluggy-based plugin system. Installing clerk-scrapers alongside clerk makes its fetchers available automatically — no configuration required.

This package serves two roles:

1. A **curated shared package** where vetted community fetchers live (PRs reviewed by CivicBand maintainers)
2. A **reference implementation** for anyone who wants to publish their own independent fetcher package

## Integration Mechanism

clerk already has entry-point-based plugin discovery via `load_plugins_from_entry_points()` in `plugin_loader.py`. It scans the `clerk.plugins` entry point group and registers any discovered plugin classes with the pluggy plugin manager.

clerk-scrapers declares itself as a `clerk.plugins` entry point. When installed, clerk discovers it on startup and registers it. The plugin class implements two existing hooks:

- **`fetcher_class(label)`** — returns the fetcher class for a given scraper label
- **`fetcher_extra(label)`** — returns default extra config for a given scraper label

**Zero changes to clerk are required.**

Independent third-party fetcher packages work identically — any package that declares a `clerk.plugins` entry point and implements the same hooks is discovered the same way.

## Package Structure

```text
clerk-fetchers/
├── pyproject.toml
├── README.md
├── CONTRIBUTING.md
├── src/
│   └── clerk_fetchers/
│       ├── __init__.py          # ClerkFetchersPlugin with @hookimpl methods
│       ├── _registry.py         # Label-to-class and label-to-extra mappings
│       └── fetchers/
│           ├── __init__.py
│           └── example_city/
│               ├── __init__.py  # ExampleCityFetcher(Fetcher) class
│               └── README.md    # Site-specific docs: target URL, extra keys, quirks
└── tests/
    └── fetchers/
        └── example_city/
            ├── test_fetcher.py
            └── fixtures/        # Mocked HTML/JSON responses
```

Each fetcher lives in its own subdirectory under `fetchers/`. Naming uses "fetcher" consistently with clerk's `Fetcher` base class.

## Plugin Class & Registry

The plugin class delegates to simple dictionaries, keeping it stable across fetcher additions:

```python
# src/clerk_fetchers/__init__.py
from clerk import hookimpl
from clerk_fetchers._registry import FETCHER_REGISTRY, EXTRA_REGISTRY

class ClerkFetchersPlugin:
    @hookimpl
    def fetcher_class(self, label):
        return FETCHER_REGISTRY.get(label)

    @hookimpl
    def fetcher_extra(self, label):
        return EXTRA_REGISTRY.get(label)
```

```python
# src/clerk_fetchers/_registry.py
from clerk_fetchers.fetchers.example_city import ExampleCityFetcher

FETCHER_REGISTRY = {
    "example_city": ExampleCityFetcher,
}

EXTRA_REGISTRY = {
    "example_city": {"base_url": "https://example-city.gov/meetings"},
}
```

Contributors add their fetcher import and registry entries to `_registry.py` as part of their PR. The plugin class never changes when fetchers are added.

## Extra Config Pattern

Fetchers can declare default extra config via `EXTRA_REGISTRY` and read it at runtime from the site dict:

```python
class ExampleCityFetcher(Fetcher):
    def child_init(self):
        self.base_url = self.site.get("extra", {}).get("base_url")

    def fetch_events(self):
        # Use self.base_url to scrape
        ...
```

`fetcher_extra` provides defaults. The site's `extra` JSON field in the database can override them. Each fetcher's README documents what extra keys it supports.

## Dependencies & Build

```toml
[project]
name = "clerk-fetchers"
requires-python = ">=3.12"
dependencies = [
    "clerk>=<current_version>",
]

[project.entry-points."clerk.plugins"]
clerk-fetchers = "clerk_scrapers:ClerkFetchersPlugin"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- **Hatchling** build system, matching clerk
- **Loose lower bound** on clerk dependency — the plugin API (hookspecs + Fetcher base class) is the contract; clerk-fetchers doesn't need to track every clerk release
- **Python 3.12+**, matching clerk

## Contributor Workflow

### Adding a fetcher to clerk-fetchers (shared package)

1. Fork clerk-fetchers, create a branch
2. Create `src/clerk_fetchers/fetchers/<municipality_name>/`
3. Implement a `Fetcher` subclass with at minimum `fetch_events()`
4. Add the label-to-class mapping in `_registry.py`
5. If the fetcher uses extra config, add the defaults to `EXTRA_REGISTRY`
6. Write a fetcher-level `README.md` documenting: target site URL, extra config keys, known quirks
7. Write tests with mocked HTTP responses in `tests/fetchers/<municipality_name>/`
8. Open a PR — CI runs tests, a CivicBand maintainer reviews

### Publishing an independent fetcher package

Same pattern, different packaging. Create a standalone package with a `clerk.plugins` entry point that implements the `fetcher_class` hook (and optionally `fetcher_extra`). The clerk-fetchers repo serves as a reference implementation. `CONTRIBUTING.md` documents both paths.

## Testing Strategy

Each fetcher must include:

- **Mocked HTTP fixtures** — saved HTML/JSON responses from the target site, stored in `tests/fetchers/<name>/fixtures/`
- **Tests that verify `fetch_events()`** produces the expected events from those fixtures
- **pytest** as the test runner, **respx** (or similar) for HTTP mocking

CI runs the full test suite on every PR. Tests plus maintainer review is the quality bar for acceptance.

## Scope

- **Fetchers only** for now. The plugin hook system supports other extension points (compilation, extraction, deployment), but clerk-fetchers is scoped to fetchers.
- **Any municipality worldwide** — no geographic restrictions on what fetchers can be contributed.
- **Community-contributed** — this is separate from both clerk core and the internal CivicBand fetchers.
