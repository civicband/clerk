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
