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
