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
