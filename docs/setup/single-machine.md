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

### 2. Start Workers Manually

Start each worker type in separate terminal windows:

```bash
# Terminal 1: Fetch worker
clerk worker fetch

# Terminal 2: OCR workers
clerk worker ocr -n 4

# Terminal 3: Compilation worker
clerk worker compilation

# Terminal 4: Deploy worker  
clerk worker deploy
```

Or run all in the background:

```bash
clerk worker fetch &
clerk worker ocr -n 4 &
clerk worker compilation &
clerk worker deploy &
```

For production deployments, use your system's process manager (systemd, launchd, supervisor, etc.) to manage worker processes.

### 3. Verify Workers Running

**Check worker processes:**

```bash
ps aux | grep "clerk worker"
```

Expected: One process per worker (fetch, ocr, compilation, deploy)

**Check Redis queues:**

```bash
redis-cli LLEN rq:queue:fetch
redis-cli LLEN rq:queue:ocr
redis-cli LLEN rq:queue:compilation
redis-cli LLEN rq:queue:deploy
```

Expected: All return 0 or a number (indicates Redis is working)

## Testing the Pipeline

### 1. Create a test site

```bash
clerk etl new test-city.civic.band
```

Follow prompts to configure site.

### 2. Trigger an update

```bash
clerk etl update -s test-city.civic.band
```

### 3. Monitor progress

```bash
# Watch queue depths
watch -n 2 "redis-cli LLEN rq:queue:fetch; redis-cli LLEN rq:queue:ocr; redis-cli LLEN rq:queue:compilation"

# Or follow worker output (if running in foreground)
# Just watch the terminal where you started the workers
```

### 4. Verify completion

Check the storage directory for output:

```bash
ls ../sites/test-city.civic.band/
```

Expected: Contains `pdfs/`, `txt/`, and `meetings.db`

## Next Steps

- [Verification Guide](verification.md) - Comprehensive testing
- [Operations Guide](../operations/index.md) - Day-to-day maintenance
- [Distributed Setup](distributed.md) - Scale to multiple machines

## Troubleshooting

See [Setup Troubleshooting](troubleshooting.md) for common issues.

### Workers not starting

Check the terminal where you started the workers for error messages.

Common fixes:
- Ensure Redis is running: `redis-cli ping`
- Ensure PostgreSQL is running: `psql $DATABASE_URL -c "SELECT 1;"`
- Verify `.env` file exists and is readable
- Check that the `STORAGE_DIR` exists and is writable

### Jobs stuck in queue

Check if workers are running and check for errors in their output:

```bash
# List all worker processes
ps aux | grep "clerk worker"

# Check Redis for stuck jobs
redis-cli LRANGE rq:queue:fetch 0 -1
```

Look at the worker output/logs for error messages about why jobs aren't completing.

### High memory usage

If extraction workers consume too much memory:

1. Set `EXTRACTION_WORKERS=0` in `.env`
2. Restart workers
3. Use [Distributed Setup](distributed.md) to run extraction on separate machine
