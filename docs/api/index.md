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
