# clerk

A Python library for managing civic data pipelines for civic.band. Clerk handles the complete workflow of fetching, processing, and deploying civic meeting data including minutes and agendas.

[![Tests](https://github.com/civicband/clerk/actions/workflows/test.yml/badge.svg)](https://github.com/civicband/clerk/actions/workflows/test.yml)
[![Lint](https://github.com/civicband/clerk/actions/workflows/lint.yml/badge.svg)](https://github.com/civicband/clerk/actions/workflows/lint.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

## Features

- **Distributed Task Queue**: RQ-based distributed processing with parallel OCR and horizontal scaling
- **Site Management**: Create and manage civic sites with metadata
- **Data Pipeline**: Automated fetch → OCR → compilation → deploy workflow
- **Plugin System**: Extensible architecture using pluggy for custom fetchers and deployers
- **Full-Text Search**: Automatic FTS index generation for searchable meeting data
- **Database Management**: SQLite-based storage with per-site and aggregate databases
- **Observability**: Structured logging with Loki integration

## Quick Install

```bash
pip install "clerk[pdf,extraction] @ git+https://github.com/civicband/clerk.git"
```

## Documentation

### Setup

- **[macOS Setup](docs/setup/macos.md)** - Complete installation guide for macOS
- **[Linux Setup](docs/setup/linux.md)** - Complete installation guide for Linux
- **[Single-Machine Workers](docs/setup/single-machine.md)** - Configure workers on one machine
- **[Distributed Workers](docs/setup/distributed.md)** - Scale across multiple machines
- **[Verification](docs/setup/verification.md)** - Test your setup

### Operations

- **[Daily Tasks](docs/operations/daily-tasks.md)** - Common operational tasks
- **[Monitoring](docs/operations/monitoring.md)** - Health checks and metrics
- **[Troubleshooting](docs/operations/troubleshooting.md)** - Fix common issues
- **[Scaling](docs/operations/scaling.md)** - Add workers and scale horizontally

### Reference

- **[CLI Reference](docs/reference/cli/index.md)** - Complete command-line reference
- **[Python API](docs/reference/python-api/index.md)** - Python library reference
- **[Plugin API](docs/reference/plugin-api/index.md)** - Plugin development guide

### Guides

- **[Your First Site](docs/guides/first-site.md)** - Complete beginner tutorial
- **[Worker Architecture](docs/guides/worker-architecture.md)** - Understanding task queues
- **[Custom Fetcher](docs/guides/custom-fetcher.md)** - Build a fetcher plugin
- **[Production Checklist](docs/guides/production-checklist.md)** - Pre-launch validation

## Quick Start

```bash
# Create a new site
clerk new

# Update a site (enqueues fetch → OCR → compilation → deploy)
clerk update --subdomain example.civic.band

# Check status
clerk status
```

See [Your First Site Tutorial](docs/guides/first-site.md) for a complete walkthrough.

## Architecture

Clerk uses a distributed task queue (RQ) with specialized worker types:

- **fetch** - Download meeting data from city websites
- **ocr** - Extract text from PDFs (parallel, CPU-intensive)
- **compilation** - Build databases and coordinate pipeline
- **extraction** - Entity and vote extraction (optional, memory-intensive)
- **deploy** - Upload to storage/CDN

Workers can run on a single machine or distributed across multiple machines for better performance.

See [Worker Architecture Guide](docs/guides/worker-architecture.md) for details.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

BSD 3-Clause License - See [LICENSE](LICENSE) for details.

## Links

- **Documentation**: [docs/](docs/)
- **Issues**: https://github.com/civicband/clerk/issues
- **civic.band**: https://civic.band
