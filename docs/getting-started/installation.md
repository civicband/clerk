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
```

## Verification

Verify installation:

```bash
clerk --version
```

## Next Steps

Once installed, proceed to the [Quick Start](quickstart.md) tutorial.
