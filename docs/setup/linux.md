# Linux Setup

Complete installation guide for Clerk on Linux.

## Prerequisites

Before starting, complete [Prerequisites](prerequisites.md) to install:
- Redis
- PostgreSQL
- Tesseract
- Poppler
- Python 3.12+

## Installation

### 1. Install Python 3.12+

**Ubuntu 22.04+:**

```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3-pip
```

**Ubuntu 20.04 (requires PPA):**

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.12 python3.12-venv python3-pip
```

**RHEL/CentOS 8+:**

```bash
sudo dnf install python3.12 python3-pip
```

### 2. Install Clerk

Using pip:

```bash
python3.12 -m pip install --user "clerk[pdf,extraction] @ git+https://github.com/civicband/clerk.git"
```

Or using uv (faster):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv pip install "clerk[pdf,extraction] @ git+https://github.com/civicband/clerk.git"
```

**Extras explained:**
- `pdf` - PDF processing (pdfkit, pdf2image, pypdf)
- `extraction` - Entity extraction with spaCy

### 3. Install spaCy Model

For entity extraction:

```bash
python3.12 -m spacy download en_core_web_md
```

### 4. Configure Environment

Create `.env` file:

```bash
cat > .env <<'EOF'
STORAGE_DIR=../sites
DATABASE_URL=postgresql://localhost/clerk_civic
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

### 5. Add Clerk to PATH

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### 6. Initialize Database

```bash
clerk db upgrade
```

Expected output:
```
INFO  [alembic.runtime.migration] Running upgrade -> 45db71312424, initial schema
INFO  [alembic.runtime.migration] Running upgrade 45db71312424 -> c27bd77144ce, add queue tables
```

### 7. Verify Installation

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

## Next Steps

Configure workers:
- [Single-Machine Setup](single-machine.md) - Run all workers on one machine
- [Distributed Setup](distributed.md) - Scale across multiple machines

## Troubleshooting

See [Setup Troubleshooting](troubleshooting.md) for common issues.

### Common Issues

**Command not found: clerk**

Fix: Ensure `~/.local/bin` is in PATH:

```bash
echo $PATH | grep ".local/bin"
# If not found, add to ~/.bashrc:
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

**Database connection failed**

Fix: Ensure PostgreSQL is running:

```bash
sudo systemctl status postgresql
sudo systemctl start postgresql
psql clerk_civic -c "SELECT 1;"
```

**Redis connection failed**

Fix: Ensure Redis is running:

```bash
sudo systemctl status redis-server
sudo systemctl start redis-server
redis-cli ping
```

**Permission denied errors**

Fix: Ensure storage directory is writable:

```bash
mkdir -p ../sites
chmod 755 ../sites
```
