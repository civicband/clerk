# Documentation Overhaul Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restructure documentation to eliminate inconsistencies and provide clear paths for setup, operations, and API reference across platforms.

**Architecture:** Task-oriented documentation structure with platform-specific guides, complete API reference, and deep-dive tutorials.

**Tech Stack:** Markdown, Sphinx (existing doc system)

---

## Phase 1: Setup Documentation

### Task 1: Create Setup Directory Structure

**Files:**
- Create: `docs/setup/index.md`
- Create: `docs/setup/prerequisites.md`
- Create: `docs/setup/macos.md`
- Create: `docs/setup/linux.md`
- Create: `docs/setup/single-machine.md`
- Create: `docs/setup/distributed.md`
- Create: `docs/setup/verification.md`
- Create: `docs/setup/troubleshooting.md`

**Step 1: Create setup directory**

```bash
mkdir -p docs/setup
```

**Step 2: Create placeholder files**

```bash
touch docs/setup/index.md
touch docs/setup/prerequisites.md
touch docs/setup/macos.md
touch docs/setup/linux.md
touch docs/setup/single-machine.md
touch docs/setup/distributed.md
touch docs/setup/verification.md
touch docs/setup/troubleshooting.md
```

**Step 3: Verify files created**

```bash
ls -la docs/setup/
```

Expected: 8 files listed

**Step 4: Commit**

```bash
git add docs/setup/
git commit -m "docs: create setup directory structure"
```

### Task 2: Write setup/index.md

**Files:**
- Modify: `docs/setup/index.md`

**Step 1: Write setup overview with platform chooser**

Content for `docs/setup/index.md`:

```markdown
# Setting Up Clerk

Complete guides for installing and configuring Clerk on your platform.

## Quick Navigation

**Choose your platform:**
- [macOS Setup](macos.md) - Complete setup for macOS systems
- [Linux Setup](linux.md) - Complete setup for Linux systems

**Worker Configuration:**
- [Single-Machine Setup](single-machine.md) - Run all workers on one machine
- [Distributed Setup](distributed.md) - Scale across multiple machines

**Additional Resources:**
- [Prerequisites](prerequisites.md) - System requirements
- [Verification](verification.md) - Confirm your setup works
- [Troubleshooting](troubleshooting.md) - Common setup issues

## Setup Flow

1. **Review Prerequisites** - Check system requirements
2. **Platform Installation** - Install Clerk and dependencies for your OS
3. **Worker Configuration** - Configure task queue workers
4. **Verification** - Run end-to-end tests
5. **Troubleshooting** (if needed) - Fix common issues

## Quick Start Decision Tree

```
┌─ Which platform? ───────────────────────────┐
│                                              │
├─ macOS ──> [macOS Setup](macos.md)         │
│                                              │
├─ Linux ──> [Linux Setup](linux.md)         │
│                                              │
└──────────────────────────────────────────────┘

┌─ How many machines? ─────────────────────────┐
│                                              │
├─ One ──> [Single-Machine](single-machine.md)│
│                                              │
├─ Multiple ──> [Distributed](distributed.md) │
│                                              │
└──────────────────────────────────────────────┘
```

## Next Steps

After completing setup, see:
- [Operations Guide](../operations/index.md) - Day-to-day maintenance
- [Your First Site Tutorial](../guides/first-site.md) - Complete walkthrough
```

**Step 2: Verify content**

```bash
cat docs/setup/index.md | grep -E "macOS Setup|Linux Setup|Single-Machine|Distributed"
```

Expected: All four links present

**Step 3: Commit**

```bash
git add docs/setup/index.md
git commit -m "docs: add setup overview and platform chooser"
```

### Task 3: Write setup/prerequisites.md

**Files:**
- Modify: `docs/setup/prerequisites.md`

**Step 1: Write prerequisites guide**

Content for `docs/setup/prerequisites.md`:

```markdown
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
```

**Step 2: Verify content**

```bash
grep -E "Redis|PostgreSQL|Tesseract|Poppler|spaCy" docs/setup/prerequisites.md | wc -l
```

Expected: At least 5 matches

**Step 3: Commit**

```bash
git add docs/setup/prerequisites.md
git commit -m "docs: add prerequisites guide with system requirements"
```

### Task 4: Write setup/macos.md

**Files:**
- Modify: `docs/setup/macos.md`
- Reference: `README.md:20-49` (current installation section)
- Reference: `docs/getting-started/installation.md` (existing content)

**Step 1: Extract key content from existing docs**

```bash
# Review existing installation docs
cat README.md | sed -n '20,49p'
cat docs/getting-started/installation.md
```

**Step 2: Write macOS setup guide**

Content for `docs/setup/macos.md`:

```markdown
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
pip install "clerk[pdf,extraction] @ git+https://github.com/civicband/clerk.git"
```

Or using uv (faster):

```bash
uv pip install "clerk[pdf,extraction] @ git+https://github.com/civicband/clerk.git"
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
```

**Step 3: Verify content**

```bash
grep -E "Install Clerk|Configure Environment|Initialize Database|Verify Installation" docs/setup/macos.md | wc -l
```

Expected: At least 4 section headers

**Step 4: Commit**

```bash
git add docs/setup/macos.md
git commit -m "docs: add complete macOS setup guide"
```

### Task 5: Write setup/linux.md

**Files:**
- Modify: `docs/setup/linux.md`

**Step 1: Write Linux setup guide**

Content for `docs/setup/linux.md`:

```markdown
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
```

**Step 2: Verify content**

```bash
grep -E "Install Python|Install Clerk|Configure Environment|Initialize Database" docs/setup/linux.md | wc -l
```

Expected: At least 4 section headers

**Step 3: Commit**

```bash
git add docs/setup/linux.md
git commit -m "docs: add complete Linux setup guide"
```

### Task 6: Write setup/single-machine.md

**Files:**
- Modify: `docs/setup/single-machine.md`
- Reference: `docs/user-guide/task-queue.md` (existing worker docs)

**Step 1: Review existing worker documentation**

```bash
grep -A 20 "Worker" docs/user-guide/task-queue.md | head -40
```

**Step 2: Write single-machine worker guide**

Content for `docs/setup/single-machine.md`:

```markdown
# Single-Machine Worker Setup

Configure Clerk workers to run on a single machine.

## Overview

Clerk uses a distributed task queue (RQ) with 5 worker types:

1. **fetch** - Download meeting data from city websites
2. **ocr** - Extract text from PDFs (CPU-intensive)
3. **compilation** - Build databases, coordinate jobs
4. **extraction** - Entity and vote extraction (optional, memory-intensive)
5. **deploy** - Upload to CDN/storage

## Architecture

```
┌─────────────────────────────────────────────────┐
│                Single Machine                    │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │  Redis   │  │PostgreSQL│  │  Storage Dir  │ │
│  └────┬─────┘  └─────┬────┘  └───────┬───────┘ │
│       │              │                │         │
│  ┌────┴──────────────┴────────────────┴──────┐ │
│  │           Clerk Workers (5 types)         │ │
│  │  fetch(2) ocr(4) compilation(2)          │ │
│  │  extraction(0) deploy(1)                  │ │
│  └───────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

## Worker Configuration

### 1. Configure Worker Counts

Edit `.env` file:

```bash
# Core pipeline workers (required)
FETCH_WORKERS=2       # Parallel site fetching
OCR_WORKERS=4         # Parallel OCR processing (CPU-bound)
COMPILATION_WORKERS=2 # Database builds, coordination
DEPLOY_WORKERS=1      # Upload to storage

# Optional workers (memory-intensive)
EXTRACTION_WORKERS=0  # Set to 0 if not using extraction
                      # Set to 1-2 if extraction enabled
```

**Memory considerations:**
- Each OCR worker: ~500 MB
- Each extraction worker: ~5 GB (with spaCy)
- Recommended: 8 GB RAM for full pipeline

### 2. Install Worker Services

**macOS (LaunchAgents):**

```bash
clerk install-workers
```

This creates LaunchAgent plist files in `~/Library/LaunchAgents/` for each worker type.

**Verify installation:**

```bash
ls ~/Library/LaunchAgents/ | grep clerk
```

Expected: Multiple `clerk.worker.*.plist` files

**Linux (systemd):**

```bash
clerk install-workers
```

This creates systemd service files in `~/.config/systemd/user/` for each worker.

**Verify installation:**

```bash
systemctl --user list-unit-files | grep clerk
```

Expected: Multiple `clerk-worker-*.service` files

### 3. Start Workers

**macOS:**

```bash
# Start all workers
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/clerk.worker.*.plist

# Or restart if already loaded
launchctl kickstart gui/$(id -u)/clerk.worker.fetch.1
```

**Linux:**

```bash
# Enable and start all workers
systemctl --user enable clerk-worker-*
systemctl --user start clerk-worker-*
```

### 4. Verify Workers Running

**Check worker processes:**

```bash
ps aux | grep "clerk worker"
```

Expected: One process per configured worker

**Check worker status:**

**macOS:**

```bash
launchctl print gui/$(id -u)/clerk.worker.fetch.1
```

**Linux:**

```bash
systemctl --user status clerk-worker-fetch-1
```

**Use clerk status command:**

```bash
clerk status
```

Expected output:
```
Queue Status:
  fetch: 0 jobs
  ocr: 0 jobs
  compilation: 0 jobs
  extraction: 0 jobs
  deploy: 0 jobs

Active Workers:
  fetch: 2 workers
  ocr: 4 workers
  compilation: 2 workers
  extraction: 0 workers
  deploy: 1 worker
```

## Testing the Pipeline

### 1. Create a test site

```bash
clerk new test-city.civic.band
```

Follow prompts to configure site.

### 2. Trigger an update

```bash
clerk update -s test-city.civic.band
```

### 3. Monitor progress

```bash
# Watch queue depths
watch -n 2 clerk status

# Or follow logs (macOS)
tail -f /tmp/clerk.worker.fetch.1.log

# Or follow logs (Linux)
journalctl --user -u clerk-worker-fetch-1 -f
```

### 4. Verify completion

```bash
clerk status -s test-city.civic.band
```

Expected: Site shows "completed" status

## Next Steps

- [Verification Guide](verification.md) - Comprehensive testing
- [Operations Guide](../operations/index.md) - Day-to-day maintenance
- [Distributed Setup](distributed.md) - Scale to multiple machines

## Troubleshooting

See [Setup Troubleshooting](troubleshooting.md) for common issues.

### Workers not starting

**macOS:**

Check LaunchAgent logs:

```bash
cat /tmp/clerk.worker.fetch.1.log
```

**Linux:**

Check systemd logs:

```bash
journalctl --user -u clerk-worker-fetch-1 -n 50
```

Common fixes:
- Ensure Redis is running: `redis-cli ping`
- Ensure PostgreSQL is running: `psql $DATABASE_URL -c "SELECT 1;"`
- Check PATH in LaunchAgent/systemd files
- Verify `.env` file exists and is readable

### Jobs stuck in queue

Check worker logs for errors:

```bash
clerk diagnose-workers
```

This command shows:
- Worker process status
- Recent log output
- Configuration issues

### High memory usage

If extraction workers consume too much memory:

1. Set `EXTRACTION_WORKERS=0` in `.env`
2. Restart workers
3. Use [Distributed Setup](distributed.md) to run extraction on separate machine
```

**Step 3: Verify content**

```bash
grep -E "Worker Configuration|Install Worker Services|Start Workers|Verify Workers" docs/setup/single-machine.md | wc -l
```

Expected: At least 4 section headers

**Step 4: Commit**

```bash
git add docs/setup/single-machine.md
git commit -m "docs: add single-machine worker setup guide"
```

### Task 7: Write setup/distributed.md

**Files:**
- Modify: `docs/setup/distributed.md`

**Step 1: Write distributed setup guide**

Content for `docs/setup/distributed.md`:

```markdown
# Distributed Worker Setup

Scale Clerk across multiple machines for better performance and resource isolation.

## Overview

Distributed setup allows you to:
- Run OCR workers on dedicated machines (CPU-intensive)
- Run extraction workers on separate machines (memory-intensive)
- Scale horizontally by adding more worker machines
- Isolate core pipeline from optional extraction

## Architecture

```
┌─────────────── Shared Services ─────────────────┐
│  ┌──────────┐         ┌──────────────┐         │
│  │  Redis   │         │ PostgreSQL   │         │
│  │(Shared)  │         │  (Shared)    │         │
│  └────┬─────┘         └──────┬───────┘         │
└───────┼─────────────────────┼──────────────────┘
        │                     │
        │    Network          │
┌───────┼─────────────────────┼──────────────────┐
│ Machine 1: Core Pipeline    │                  │
│  fetch(2) compilation(2) deploy(1)            │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│ Machine 2: OCR Workers                          │
│  ocr(8)                                         │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│ Machine 3: Extraction Workers (Optional)        │
│  extraction(2)                                  │
└─────────────────────────────────────────────────┘
```

## Prerequisites

All machines must:
- Have network access to Redis and PostgreSQL
- Have Clerk installed (same version)
- Share `.env` configuration (Redis URL, Database URL)
- Have access to shared storage (NFS, S3, etc.) OR use deployment plugins

## Setup Steps

### 1. Configure Shared Services

**On one machine (service host):**

Install and configure Redis for network access:

**macOS:**

```bash
# Edit Redis config
nano /opt/homebrew/etc/redis.conf

# Change bind address
bind 0.0.0.0

# Set password (recommended)
requirepass YOUR_SECURE_PASSWORD

# Restart Redis
brew services restart redis
```

**Linux:**

```bash
# Edit Redis config
sudo nano /etc/redis/redis.conf

# Change bind address
bind 0.0.0.0

# Set password (recommended)
requirepass YOUR_SECURE_PASSWORD

# Restart Redis
sudo systemctl restart redis-server
```

Configure PostgreSQL for network access:

```bash
# Edit postgresql.conf
sudo nano /var/lib/postgresql/data/postgresql.conf

# Add:
listen_addresses = '*'

# Edit pg_hba.conf
sudo nano /var/lib/postgresql/data/pg_hba.conf

# Add (replace 192.168.1.0/24 with your network):
host  all  all  192.168.1.0/24  scram-sha-256

# Restart PostgreSQL
sudo systemctl restart postgresql
```

### 2. Configure Each Worker Machine

**Update `.env` on each machine:**

```bash
# Machine 1: Core Pipeline
cat > .env <<'EOF'
STORAGE_DIR=../sites
DATABASE_URL=postgresql://user:pass@SERVICE_HOST:5432/clerk_civic
REDIS_URL=redis://:YOUR_PASSWORD@SERVICE_HOST:6379
DEFAULT_OCR_BACKEND=tesseract
ENABLE_EXTRACTION=0

# Only core pipeline workers
FETCH_WORKERS=2
OCR_WORKERS=0
COMPILATION_WORKERS=2
EXTRACTION_WORKERS=0
DEPLOY_WORKERS=1
EOF

# Machine 2: OCR Workers
cat > .env <<'EOF'
STORAGE_DIR=../sites
DATABASE_URL=postgresql://user:pass@SERVICE_HOST:5432/clerk_civic
REDIS_URL=redis://:YOUR_PASSWORD@SERVICE_HOST:6379
DEFAULT_OCR_BACKEND=tesseract
ENABLE_EXTRACTION=0

# Only OCR workers
FETCH_WORKERS=0
OCR_WORKERS=8
COMPILATION_WORKERS=0
EXTRACTION_WORKERS=0
DEPLOY_WORKERS=0
EOF

# Machine 3: Extraction Workers
cat > .env <<'EOF'
STORAGE_DIR=../sites
DATABASE_URL=postgresql://user:pass@SERVICE_HOST:5432/clerk_civic
REDIS_URL=redis://:YOUR_PASSWORD@SERVICE_HOST:6379
DEFAULT_OCR_BACKEND=tesseract
ENABLE_EXTRACTION=1

# Only extraction workers
FETCH_WORKERS=0
OCR_WORKERS=0
COMPILATION_WORKERS=0
EXTRACTION_WORKERS=2
DEPLOY_WORKERS=0
EOF
```

**Replace:**
- `SERVICE_HOST` with the IP/hostname of your Redis/PostgreSQL server
- `YOUR_PASSWORD` with your Redis password
- `user:pass` with PostgreSQL credentials

### 3. Test Network Connectivity

**From each worker machine:**

```bash
# Test Redis
redis-cli -h SERVICE_HOST -a YOUR_PASSWORD ping

# Test PostgreSQL
psql postgresql://user:pass@SERVICE_HOST:5432/clerk_civic -c "SELECT 1;"
```

Expected: Both commands succeed

### 4. Install and Start Workers

**On each machine:**

```bash
# Install worker services
clerk install-workers

# Start workers (macOS)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/clerk.worker.*.plist

# Start workers (Linux)
systemctl --user enable clerk-worker-*
systemctl --user start clerk-worker-*
```

### 5. Verify Distributed Setup

**From any machine:**

```bash
clerk status
```

Expected output showing workers from all machines:
```
Queue Status:
  fetch: 0 jobs
  ocr: 0 jobs
  compilation: 0 jobs
  extraction: 0 jobs
  deploy: 0 jobs

Active Workers:
  fetch: 2 workers
  ocr: 8 workers
  compilation: 2 workers
  extraction: 2 workers
  deploy: 1 worker
```

## Storage Considerations

### Shared Storage (NFS/S3)

**Option 1: NFS Mount**

All machines mount the same storage directory:

```bash
# On service host, export storage
echo "/path/to/sites 192.168.1.0/24(rw,sync)" | sudo tee -a /etc/exports
sudo exportfs -a

# On worker machines, mount
sudo mount SERVICE_HOST:/path/to/sites ../sites
```

**Option 2: S3/Object Storage**

Use deployment plugins to upload directly to S3. Workers don't need shared filesystem.

### Local Storage with Plugins

If using deployment plugins (recommended for production):
- Each machine has local `STORAGE_DIR`
- Deploy workers upload to S3/CDN
- OCR/extraction workers only need temporary storage

## Monitoring Distributed Workers

### Check Worker Health

**On each machine:**

```bash
# macOS
launchctl list | grep clerk

# Linux
systemctl --user status clerk-worker-*
```

### Monitor Queue Depths

```bash
watch -n 5 clerk status
```

If queues grow:
- OCR queue growing → Add more OCR workers
- Extraction queue growing → Add more extraction workers

### Centralized Logging

Use structured logging to aggregate logs:

```bash
# Query logs by machine
grep "machine=ocr-host" /var/log/clerk.log

# Query logs by operation
grep "operation=ocr_complete" /var/log/clerk.log
```

See [Operations: Monitoring](../operations/monitoring.md) for detailed log queries.

## Scaling Strategy

### When to Scale

- **OCR queue depth > 100** → Add OCR workers or machines
- **Extraction queue depth > 10** → Add extraction workers
- **Memory pressure** → Separate extraction to dedicated machine
- **CPU saturation** → Add more OCR worker machines

### Adding Worker Capacity

**Option 1: Add workers to existing machine**

Edit `.env` to increase worker counts:

```bash
OCR_WORKERS=16  # Was 8
```

Reinstall workers:

```bash
clerk uninstall-workers
clerk install-workers
```

**Option 2: Add new worker machine**

1. Install Clerk on new machine
2. Configure `.env` with shared services
3. Set worker counts (only desired worker types)
4. Install and start workers
5. Verify with `clerk status`

## Next Steps

- [Verification Guide](verification.md) - Test distributed setup
- [Operations: Monitoring](../operations/monitoring.md) - Monitor distributed workers
- [Operations: Scaling](../operations/scaling.md) - Advanced scaling strategies

## Troubleshooting

### Workers can't connect to Redis

Check firewall rules:

```bash
# Allow Redis port
sudo ufw allow 6379/tcp
```

Test connection:

```bash
redis-cli -h SERVICE_HOST -a YOUR_PASSWORD ping
```

### Workers can't connect to PostgreSQL

Check pg_hba.conf allows your network:

```bash
sudo nano /var/lib/postgresql/data/pg_hba.conf
```

Test connection:

```bash
psql postgresql://user:pass@SERVICE_HOST:5432/clerk_civic -c "SELECT 1;"
```

### Jobs not distributed evenly

RQ distributes jobs round-robin. If one machine is slower:
- Check CPU/memory usage on each machine
- Reduce worker count on slower machines
- Ensure all machines have same Clerk version

### Storage sync issues

If using NFS and seeing file conflicts:
- Check NFS mount options (rw,sync)
- Verify clocks are synchronized (NTP)
- Check network latency between machines
```

**Step 2: Verify content**

```bash
grep -E "Configure Shared Services|Configure Each Worker Machine|Storage Considerations|Scaling Strategy" docs/setup/distributed.md | wc -l
```

Expected: At least 4 section headers

**Step 3: Commit**

```bash
git add docs/setup/distributed.md
git commit -m "docs: add distributed worker setup guide"
```

### Task 8: Write setup/verification.md and setup/troubleshooting.md

**Files:**
- Modify: `docs/setup/verification.md`
- Modify: `docs/setup/troubleshooting.md`

**Step 1: Write verification guide**

Content for `docs/setup/verification.md`:

```markdown
# Setup Verification

Comprehensive tests to verify your Clerk installation works correctly.

## Quick Verification

### 1. Check Clerk Installation

```bash
clerk --version
```

Expected: Version number displayed

### 2. Check Service Connectivity

**Redis:**

```bash
redis-cli ping
```

Expected: `PONG`

**PostgreSQL:**

```bash
psql $DATABASE_URL -c "SELECT COUNT(*) FROM sites;"
```

Expected: `0` (empty table)

### 3. Check Worker Status

```bash
clerk status
```

Expected:
- All configured queues listed
- Worker counts match your configuration
- No errors in output

## End-to-End Test

### 1. Create Test Site

```bash
clerk new test-verification.civic.band
```

When prompted:
- Municipality: Test City
- State: CA
- Country: USA
- Kind: city-council
- Scraper: mock (for testing)
- Start year: 2024
- Latitude: 37.8
- Longitude: -122.4

### 2. Verify Site Created

```bash
psql $DATABASE_URL -c "SELECT subdomain, name FROM sites WHERE subdomain='test-verification.civic.band';"
```

Expected: One row showing your test site

### 3. Trigger Update

```bash
clerk update -s test-verification.civic.band
```

Expected: Job enqueued message

### 4. Monitor Queue

```bash
watch -n 2 "clerk status -s test-verification.civic.band"
```

Watch for:
1. Job appears in fetch queue
2. Job moves to OCR queue
3. Job moves to compilation queue
4. Job moves to deploy queue
5. Site status becomes "completed"

Press Ctrl+C when complete.

### 5. Verify Output

Check storage directory:

```bash
ls ../sites/test-verification.civic.band/
```

Expected directories:
- `pdfs/` - Downloaded PDFs
- `txt/` - Extracted text
- `meetings.db` - Site database

Check database:

```bash
sqlite3 ../sites/test-verification.civic.band/meetings.db "SELECT COUNT(*) FROM minutes;"
```

Expected: Count > 0 (processed pages)

## Component Tests

### Test Redis Connection

```bash
redis-cli -h ${REDIS_URL#redis://} SET test_key test_value
redis-cli -h ${REDIS_URL#redis://} GET test_key
redis-cli -h ${REDIS_URL#redis://} DEL test_key
```

Expected: All commands succeed

### Test PostgreSQL Connection

```bash
psql $DATABASE_URL <<EOF
CREATE TABLE IF NOT EXISTS verification_test (id SERIAL PRIMARY KEY);
INSERT INTO verification_test DEFAULT VALUES;
SELECT COUNT(*) FROM verification_test;
DROP TABLE verification_test;
EOF
```

Expected: All commands succeed, count shows 1

### Test Worker Logs

**macOS:**

```bash
tail -20 /tmp/clerk.worker.fetch.1.log
```

**Linux:**

```bash
journalctl --user -u clerk-worker-fetch-1 -n 20
```

Expected: No error messages

### Test Queue System

```bash
# Check queue lengths
clerk status | grep -E "fetch|ocr|compilation"

# Check for failed jobs
redis-cli LLEN rq:queue:failed
```

Expected: All queues at 0 or decreasing, no failed jobs

## Performance Tests

### Test OCR Speed

Time a single PDF:

```bash
time clerk ocr -s test-verification.civic.band --force
```

Expected: Completes without errors

Typical speeds:
- Tesseract: 2-5 seconds per page
- Vision Framework: 0.5-1 second per page

### Test Database Build Speed

```bash
time clerk build-db-from-text -s test-verification.civic.band
```

Expected: Completes without errors

Typical speeds:
- Without extraction: 10-30 seconds for 100 pages
- With extraction: 5-10 minutes for 100 pages

## Verification Checklist

- [ ] `clerk --version` shows version number
- [ ] `redis-cli ping` returns PONG
- [ ] `psql $DATABASE_URL` connects successfully
- [ ] `clerk status` shows configured workers
- [ ] Test site creation succeeds
- [ ] Test site update completes end-to-end
- [ ] PDFs downloaded to storage directory
- [ ] Text extracted from PDFs
- [ ] Database created with content
- [ ] Worker logs show no errors
- [ ] No failed jobs in Redis

## Next Steps

If all checks pass:
- [Your First Site](../guides/first-site.md) - Complete tutorial
- [Operations Guide](../operations/index.md) - Day-to-day usage

If any checks fail:
- [Setup Troubleshooting](troubleshooting.md) - Fix common issues
```

**Step 2: Write troubleshooting guide**

Content for `docs/setup/troubleshooting.md`:

```markdown
# Setup Troubleshooting

Common setup issues and solutions.

## Installation Issues

### Command not found: clerk

**Symptom:** `clerk: command not found` after installation

**Diagnosis:**

```bash
which clerk
echo $PATH
```

**Fix (macOS/Linux):**

```bash
export PATH="$HOME/.local/bin:$PATH"
# Add to ~/.zshrc (macOS) or ~/.bashrc (Linux) for persistence
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

**Fix (alternative - reinstall with correct target):**

```bash
pip install --user "clerk[pdf,extraction] @ git+https://github.com/civicband/clerk.git"
```

### Module not found errors

**Symptom:** `ModuleNotFoundError: No module named 'clerk'`

**Fix:**

```bash
pip install -e .  # If in development directory
# OR
pip install "clerk[pdf,extraction] @ git+https://github.com/civicband/clerk.git"
```

## Service Connection Issues

### Redis connection failed

**Symptom:** `Error: Cannot connect to Redis`

**Diagnosis:**

```bash
redis-cli ping
```

**Fix (service not running):**

**macOS:**

```bash
brew services start redis
redis-cli ping
```

**Linux:**

```bash
sudo systemctl start redis-server
sudo systemctl enable redis-server
redis-cli ping
```

**Fix (wrong URL in .env):**

Check `.env` file:

```bash
cat .env | grep REDIS_URL
```

Should be: `REDIS_URL=redis://localhost:6379`

**Fix (firewall blocking - distributed setup):**

```bash
# Allow Redis port
sudo ufw allow 6379/tcp
```

### PostgreSQL connection failed

**Symptom:** `Error: could not connect to server`

**Diagnosis:**

```bash
psql $DATABASE_URL -c "SELECT 1;"
```

**Fix (service not running):**

**macOS:**

```bash
brew services start postgresql@15
```

**Linux:**

```bash
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

**Fix (database doesn't exist):**

```bash
createdb clerk_civic
```

**Fix (permission denied):**

```bash
sudo -u postgres createuser -s $USER
createdb clerk_civic
```

**Fix (wrong URL in .env):**

Check `.env` file:

```bash
cat .env | grep DATABASE_URL
```

Should be: `DATABASE_URL=postgresql://localhost/clerk_civic`

## Worker Issues

### Workers not starting

**Symptom:** `clerk status` shows 0 workers

**Diagnosis (macOS):**

```bash
launchctl list | grep clerk
cat /tmp/clerk.worker.fetch.1.log
```

**Diagnosis (Linux):**

```bash
systemctl --user status clerk-worker-fetch-1
journalctl --user -u clerk-worker-fetch-1 -n 50
```

**Fix (LaunchAgent not loaded - macOS):**

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/clerk.worker.*.plist
```

**Fix (systemd service not enabled - Linux):**

```bash
systemctl --user enable clerk-worker-*
systemctl --user start clerk-worker-*
```

**Fix (PATH issue in LaunchAgent):**

Edit `~/Library/LaunchAgents/clerk.worker.fetch.1.plist`:

```xml
<key>EnvironmentVariables</key>
<dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
</dict>
```

Reload:

```bash
launchctl bootout gui/$(id -u)/clerk.worker.fetch.1
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/clerk.worker.fetch.1.plist
```

**Fix (missing .env file):**

```bash
# Ensure .env exists in working directory
ls -la .env
```

See [Prerequisites](prerequisites.md) for .env template.

### Workers crash immediately

**Diagnosis:**

Check logs for error messages:

**macOS:**

```bash
cat /tmp/clerk.worker.*.log
```

**Linux:**

```bash
journalctl --user -u clerk-worker-* -n 100
```

**Common errors and fixes:**

**`ModuleNotFoundError`:**

```bash
pip install -e .  # Reinstall clerk
```

**`ImportError: cannot import name 'ClerkSpec'`:**

```bash
pip install --upgrade "clerk[pdf,extraction] @ git+https://github.com/civicband/clerk.git"
```

**`ConnectionError: Error connecting to Redis`:**

Check Redis is running and .env has correct REDIS_URL.

## Jobs Not Processing

### Jobs stuck in queue

**Symptom:** Queue depth increases but never decreases

**Diagnosis:**

```bash
clerk status
redis-cli LLEN rq:queue:failed
```

**Fix (workers not running):**

See "Workers not starting" above.

**Fix (failed jobs):**

View failed jobs:

```bash
redis-cli LRANGE rq:queue:failed 0 -1
```

Clear failed queue:

```bash
redis-cli DEL rq:queue:failed
```

**Fix (deadlock - job depends on failed job):**

```bash
# Purge all jobs for a site
clerk purge -s SUBDOMAIN

# Or purge entire queue
clerk purge-queue fetch
```

### Jobs fail with errors

**Diagnosis:**

Check worker logs for stack traces:

**macOS:**

```bash
grep -A 20 "ERROR\|Traceback" /tmp/clerk.worker.*.log
```

**Linux:**

```bash
journalctl --user -u clerk-worker-* | grep -A 20 "ERROR\|Traceback"
```

**Common errors and fixes:**

**`FileNotFoundError: tesseract is not installed`:**

Install Tesseract:

```bash
# macOS
brew install tesseract

# Linux
sudo apt install tesseract-ocr
```

**`FileNotFoundError: poppler is not installed`:**

Install Poppler:

```bash
# macOS
brew install poppler

# Linux
sudo apt install poppler-utils
```

**`MemoryError` during extraction:**

Reduce extraction workers or disable extraction:

```bash
# Edit .env
EXTRACTION_WORKERS=0  # Or reduce to 1

# Restart workers
clerk uninstall-workers
clerk install-workers
```

## Performance Issues

### OCR extremely slow

**Diagnosis:**

```bash
time clerk ocr -s SUBDOMAIN --force
```

If > 10 seconds per page, investigate:

**Fix (using Vision Framework on non-Apple Silicon):**

Switch to Tesseract:

```bash
# Edit .env
DEFAULT_OCR_BACKEND=tesseract

# Re-run OCR
clerk ocr -s SUBDOMAIN --force
```

**Fix (too few OCR workers):**

```bash
# Edit .env
OCR_WORKERS=8  # Increase from 4

# Restart workers
clerk uninstall-workers
clerk install-workers
```

### High memory usage

**Symptom:** System runs out of memory

**Diagnosis:**

```bash
# Check memory usage by worker
ps aux | grep "clerk worker" | awk '{print $4, $11}'
```

**Fix (extraction workers using too much RAM):**

Disable or reduce extraction workers:

```bash
# Edit .env
EXTRACTION_WORKERS=0  # Or set to 1

# Restart workers
clerk uninstall-workers
clerk install-workers
```

Use distributed setup to run extraction on separate machine:

See [Distributed Setup](distributed.md).

**Fix (reduce spaCy parallel processing):**

```bash
# Edit .env
SPACY_N_PROCESS=1  # Default is 2

# Restart extraction workers
systemctl --user restart clerk-worker-extraction-*
```

## Diagnostic Tools

### clerk diagnose-workers

Comprehensive worker diagnostics:

```bash
clerk diagnose-workers
```

Shows:
- Worker process status
- LaunchAgent/systemd configuration
- Recent log output
- Configuration issues

### clerk status

Queue and job status:

```bash
# Overall status
clerk status

# Site-specific status
clerk status -s SUBDOMAIN
```

### Manual Redis inspection

```bash
# List all queues
redis-cli KEYS "rq:queue:*"

# Check queue length
redis-cli LLEN rq:queue:fetch

# View jobs in queue
redis-cli LRANGE rq:queue:fetch 0 -1
```

## Getting More Help

If troubleshooting doesn't resolve your issue:

1. Check [GitHub Issues](https://github.com/civicband/clerk/issues)
2. Search existing issues for similar problems
3. Open a new issue with:
   - Platform (macOS/Linux)
   - Clerk version (`clerk --version`)
   - Full error messages
   - Output from `clerk diagnose-workers`
   - Relevant log files

## Next Steps

Once issues are resolved:
- [Verification Guide](verification.md) - Verify setup works
- [Your First Site](../guides/first-site.md) - Complete tutorial
```

**Step 3: Verify both files**

```bash
wc -l docs/setup/verification.md docs/setup/troubleshooting.md
```

Expected: Both files > 100 lines

**Step 4: Commit**

```bash
git add docs/setup/verification.md docs/setup/troubleshooting.md
git commit -m "docs: add verification and troubleshooting guides"
```

### Task 9: Update README.md

**Files:**
- Modify: `README.md`
- Reference: `README.md` (existing content to trim)

**Step 1: Backup existing README**

```bash
cp README.md README.md.old
```

**Step 2: Write new streamlined README**

Content for `README.md`:

```markdown
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
```

**Step 3: Verify new README**

```bash
wc -l README.md README.md.old
```

Expected: New README significantly shorter (~100 lines vs ~380 lines)

```bash
grep -E "Setup|Operations|Reference|Guides" README.md | wc -l
```

Expected: All 4 major sections present

**Step 4: Commit**

```bash
git add README.md
git commit -m "docs: streamline README to marketing page with links to comprehensive docs"
```

---

## Phase 1 Complete

At this point, Phase 1 (Setup Documentation) is complete. The implementation plan would continue with Phases 2-6, but this gives you a clear example of the level of detail and task granularity expected.

Each phase would follow the same pattern:
- Create directory structure
- Write content for each file with specific outlines
- Verify content covers required topics
- Commit frequently

**Estimated Phase Sizes:**
- Phase 1: 9 tasks (complete above)
- Phase 2: 8 tasks (operations docs)
- Phase 3: 12 tasks (reference docs - largest phase)
- Phase 4: 9 tasks (guides)
- Phase 5: 6 tasks (architecture & cleanup)
- Phase 6: 4 tasks (review & polish)

**Total: ~48 tasks**

---

## Execution Instructions

This plan is designed to be executed task-by-task with review checkpoints between phases.

**For Phase 1 execution:**
1. Complete Tasks 1-9 sequentially
2. After each task, verify the output matches expected results
3. Commit after each task completion
4. After Phase 1 complete, review all setup docs before proceeding to Phase 2

**For remaining phases:**
- Follow same pattern (create, write, verify, commit)
- Reference existing docs when migrating content
- Test all internal links after each phase
- Build Sphinx docs after Phases 3, 4, and 6
