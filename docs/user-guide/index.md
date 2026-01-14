# User Guide

The User Guide provides comprehensive information about clerk's features and workflows.

```{toctree}
:maxdepth: 2
:caption: User Guide

task-queue
troubleshooting-workers
```

## Available Documentation

### Task Queue System

The [Task Queue System](task-queue.md) provides distributed processing capabilities for clerk, allowing you to:

- Scale workers horizontally across multiple machines
- Process hundreds of PDFs in parallel using OCR
- Monitor site progress through the pipeline in real-time
- Manage job priorities and handle failures

See the [complete task queue documentation](task-queue.md) for installation, configuration, and usage.

## Additional Topics

For other documentation, please refer to:

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
