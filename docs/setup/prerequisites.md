# Prerequisites

System requirements for running Clerk.

## System Requirements

### Operating System

- **macOS** 11.0 (Big Sur) or later
- **Linux** with systemd (Ubuntu 20.04+, Debian 11+, RHEL 8+, etc.)

### Python

- **Python 3.12+** required
- Check version: `python3 --version`

### Memory

- **Minimum:** 4 GB RAM
- **Recommended:** 8 GB RAM (for OCR and extraction)
- **Production:** 16 GB+ RAM for distributed setups

### Disk Space

- **Minimum:** 10 GB free space
- **Recommended:** 50 GB+ for production (PDFs, databases, logs)

## Required Services

### Redis

Task queue backend.

**macOS:**
```bash
brew install redis
brew services start redis
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

**Verify:**
```bash
redis-cli ping
```

Expected: `PONG`

### PostgreSQL

Central database for site metadata and job tracking.

**macOS:**
```bash
brew install postgresql@15
brew services start postgresql@15
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install postgresql postgresql-contrib
sudo systemctl enable postgresql
sudo systemctl start postgresql
```

**Create database:**
```bash
sudo -u postgres createuser -s $USER
createdb clerk_civic
```

**Verify:**
```bash
psql clerk_civic -c "SELECT version();"
```

Expected: PostgreSQL version info

## System Dependencies

### Tesseract OCR

PDF text extraction.

**macOS:**
```bash
brew install tesseract
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install tesseract-ocr
```

**Verify:**
```bash
tesseract --version
```

### Poppler (pdf2image)

PDF to image conversion.

**macOS:**
```bash
brew install poppler
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install poppler-utils
```

**Verify:**
```bash
pdftoppm -v
```

### WeasyPrint Dependencies

HTML to PDF conversion (used by some fetchers).

**macOS:**
```bash
brew install pango cairo glib gobject-introspection
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev
```

**Note:** On macOS, the `clerk install-workers` command automatically configures the library path for these dependencies. If running clerk manually, you may need to set:

```bash
export DYLD_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_LIBRARY_PATH"  # Apple Silicon
# or
export DYLD_LIBRARY_PATH="/usr/local/lib:$DYLD_LIBRARY_PATH"     # Intel Mac
```

### spaCy Language Model

Entity extraction (optional).

```bash
python -m spacy download en_core_web_md
```

## Environment Variables

Create `.env` file in your working directory:

```bash
# Storage directory for site data
STORAGE_DIR=../sites

# Database connection
DATABASE_URL=postgresql://localhost/clerk_civic

# Redis connection
REDIS_URL=redis://localhost:6379

# OCR backend (tesseract or vision)
DEFAULT_OCR_BACKEND=tesseract

# Entity extraction (optional, requires spaCy)
ENABLE_EXTRACTION=0

# Worker counts (set in worker setup)
FETCH_WORKERS=2
OCR_WORKERS=4
COMPILATION_WORKERS=2
EXTRACTION_WORKERS=0
DEPLOY_WORKERS=1
```

## Next Steps

- [macOS Setup](macos.md) - Install Clerk on macOS
- [Linux Setup](linux.md) - Install Clerk on Linux
