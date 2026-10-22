# macOS Setup

Complete installation guide for Clerk on macOS.

## Prerequisites

Before starting, complete [Prerequisites](prerequisites.md) to install:
- Redis
- PostgreSQL
- Tesseract
- Poppler
- Python 3.12+

## Installation

### 1. Install Clerk

Using pip:

```bash
pip install "civicband-clerk[pdf] @ git+https://github.com/civicband/clerk.git"
```

Or using uv (faster):

```bash
uv pip install "civicband-clerk[pdf] @ git+https://github.com/civicband/clerk.git"
```

**Extras explained:**
- `pdf` - PDF processing (pdfkit, pdf2image, pypdf)

### 2. Configure Environment

Create `.env` file:

```bash
cat > .env <<'EOF'
STORAGE_DIR=../sites
DATABASE_URL=postgresql://localhost/clerk_civic
REDIS_URL=redis://localhost:6379
DEFAULT_OCR_BACKEND=tesseract
FETCH_WORKERS=2
OCR_WORKERS=4
COMPILATION_WORKERS=2
DEPLOY_WORKERS=1
EOF
```

### 3. Initialize Database

```bash
clerk db upgrade
```

Expected output:
```
INFO  [alembic.runtime.migration] Running upgrade -> 45db71312424, initial schema
INFO  [alembic.runtime.migration] Running upgrade 45db71312424 -> c27bd77144ce, add queue tables
```

### 4. Verify Installation

Check Clerk version:

```bash
clerk --version
```

Check database connection:

```bash
psql $DATABASE_URL -c "SELECT COUNT(*) FROM sites;"
```

Expected: `0` (empty table)

Check Redis connection:

```bash
redis-cli ping
```

Expected: `PONG`

## Optional: Vision Framework OCR

For faster OCR on Apple Silicon:

```bash
pip install pyobjc-framework-Vision pyobjc-framework-Quartz
```

Update `.env`:

```bash
DEFAULT_OCR_BACKEND=vision
```

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

Fix: Ensure PostgreSQL is running:

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
