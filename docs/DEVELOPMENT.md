# Development Setup

## System Dependencies

### macOS

For PDF processing with weasyprint, install required system libraries:

```bash
brew install gobject-introspection cairo pango glib
```

**Note:** On Apple Silicon Macs, ensure you're using ARM64 Homebrew (`/opt/homebrew/bin/brew`), not Intel Homebrew (`/usr/local/bin/brew`).

### Vision Framework (macOS only)

To use the Vision Framework OCR backend:

```bash
# Install Python dependencies
pip install pyobjc-framework-Vision pyobjc-framework-Quartz

# Or with uv
uv sync --extra vision
```

**Requirements:**
- macOS 10.15 (Catalina) or later
- Apple Silicon (M1+) recommended for best performance

## Installation

```bash
# Clone repository
git clone https://github.com/civicband/clerk.git
cd clerk

# Install dependencies
uv sync --extra dev --extra pdf --extra vision

# Run tests
PYTHONPATH=src pytest
```

## Running Tests

```bash
# All tests
PYTHONPATH=src pytest

# Specific test file
PYTHONPATH=src pytest tests/test_fetcher.py

# Vision Framework tests (macOS only)
PYTHONPATH=src pytest tests/test_fetcher.py -k vision
```
