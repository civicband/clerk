# macOS Setup

Complete installation guide for Clerk on macOS.

## Prerequisites

Before starting, complete [Prerequisites](prerequisites.md) to install:
- Redis (required)
- Tesseract (required)
- Poppler (required)
- Python 3.12+ (required)
- SQLite (required)

## Installation

### 1. Install Clerk

Using pip:

```bash
pip install "civicband-clerk[pdf,extraction] @ git+https://github.com/civicband/clerk.git"
```

Or using uv (faster):

```bash
uv pip install "civicband-clerk[pdf,extraction] @ git+https://github.com/civicband/clerk.git"
```

**Extras explained:**
- `pdf` - PDF processing (pdfkit, pdf2image, pypdf)
- `extraction` - Entity extraction with spaCy

### 2. Install spaCy Model

For entity extraction:

```bash
python -m spacy download en_core_web_md
```

### 3. Configure Environment

Create `.env` file (using SQLite by default):

```bash
cat > .env <<'EOF'
STORAGE_DIR=../sites
DATABASE_URL=sqlite:///civic.db
REDIS_URL=redis://localhost:6379
DEFAULT_OCR_BACKEND=tesseract
ENABLE_EXTRACTION=0
FETCH_WORKERS=2
OCR_WORKERS=4
COMPILATION_WORKERS=2
EXTRACTION_WORKERS=0
DEPLOY_WORKERS=1
EOF
```

**For PostgreSQL (production)**, use instead:
```bash
DATABASE_URL=postgresql://localhost/clerk_civic
```

### 4. Initialize Database

```bash
clerk db upgrade
```

Expected output:
```
INFO  [alembic.runtime.migration] Running upgrade -> 45db71312424, initial schema
INFO  [alembic.runtime.migration] Running upgrade 45db71312424 -> c27bd77144ce, add queue tables
```

### 5. Verify Installation

Check Clerk version:

```bash
clerk --version
```

Check database connection (SQLite):

```bash
sqlite3 civic.db "SELECT COUNT(*) FROM sites;"
```

Expected: `0` (empty table)

**If using PostgreSQL**, check with:
```bash
psql $DATABASE_URL -c "SELECT COUNT(*) FROM sites;"
```

Check Redis connection:

```bash
redis-cli ping
```

Expected: `PONG`

## Next Steps

Configure workers:
- [Single-Machine Setup](single-machine.md) - Run all workers on one machine
- [Distributed Setup](distributed.md) - Scale across multiple machines

## Troubleshooting

See [Setup Troubleshooting](troubleshooting.md) for common issues.

### Common Issues

**Command not found: clerk**

Fix: Add Python bin to PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
# Add to ~/.zshrc or ~/.bashrc for persistence
```

**Database connection failed**

If using SQLite (default), ensure the file is writable:

```bash
touch civic.db
chmod 644 civic.db
```

If using PostgreSQL (production), ensure it's running:

```bash
brew services start postgresql@15
psql clerk_civic -c "SELECT 1;"
```

**Redis connection failed**

Fix: Ensure Redis is running:

```bash
brew services start redis
redis-cli ping
```
