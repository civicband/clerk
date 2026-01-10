# Task Queue System

clerk uses a distributed task queue system powered by [RQ (Redis Queue)](https://python-rq.org/) to process civic meeting data at scale. The queue system orchestrates the entire data pipeline from fetching PDFs through OCR, entity extraction, and deployment.

## Overview

The task queue system provides:

- **Distributed Processing**: Scale workers horizontally across multiple machines
- **Parallel Execution**: OCR hundreds of PDFs simultaneously
- **Real-Time Monitoring**: Track progress for each site through the pipeline
- **Fault Tolerance**: RQ handles job failures and retries
- **Priority Queues**: Express lane for urgent site updates
- **Observability**: Full job tracking in PostgreSQL

## Architecture

### Pipeline Flow

```
clerk enqueue <subdomain> [--priority high]
  ↓
[high/fetch queue] → fetch_site_job
  ↓
Downloads PDFs → Spawns N × ocr_page_job → [ocr queue]
  ↓
ocr_complete_coordinator (waits for ALL OCR jobs)
  ├─→ db_compilation_job(entities=False) → [extraction queue] (fast path)
  └─→ extraction_job → db_compilation_job(entities=True) → deploy_job
```

### Queue Types

clerk uses five specialized queues:

| Queue | Purpose | Workers | Concurrency |
|-------|---------|---------|-------------|
| **high** | Priority jobs | 1-2 | Low |
| **fetch** | Download PDFs | 2-4 | Medium |
| **ocr** | OCR processing | 4-8 | High |
| **extraction** | Entity extraction + DB compilation | 2-4 | Medium |
| **deploy** | Deploy to production | 1-2 | Low |

### Fan-Out/Fan-In Pattern

The queue system uses a fan-out/fan-in pattern for efficient parallel processing:

1. **Fan-Out**: One fetch job spawns many OCR jobs (one per PDF page)
2. **Fan-In**: A coordinator job waits for ALL OCR jobs to complete
3. **Parallel Paths**: After OCR, two paths run simultaneously:
   - Fast path: Database compilation without entity extraction
   - Full path: Entity extraction → Database compilation → Deployment

This ensures users get quick results (fast path) while comprehensive data builds in the background (full path).

## Prerequisites

### Required Services

1. **PostgreSQL** (9.6+)
   - Stores job tracking and site progress
   - Connection string: `DATABASE_URL`

2. **Redis** (5.0+)
   - Queue backend and job broker
   - Connection string: `REDIS_URL`

### Installation

#### macOS (Homebrew)

```bash
# Install services
brew install postgresql@16 redis

# Start services
brew services start postgresql@16
brew services start redis

# Verify connections
psql -h localhost -U postgres -c "SELECT 1"
redis-cli ping
```

#### Linux (Ubuntu/Debian)

```bash
# Install services
sudo apt-get install postgresql redis-server

# Start services
sudo systemctl start postgresql redis-server

# Enable on boot
sudo systemctl enable postgresql redis-server
```

#### Docker Compose

```yaml
version: '3.8'
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: clerk
      POSTGRES_DB: clerk
    ports:
      - "5432:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres-data:
```

## Configuration

### Environment Variables

Create a `.env` file in your project root:

```bash
# Database Configuration
# PostgreSQL connection for job tracking and site progress
DATABASE_URL=postgresql://clerk:password@localhost:5432/clerk

# Redis Configuration
# Redis connection for RQ queue backend
REDIS_URL=redis://localhost:6379/0

# Storage Configuration
# Base directory for site data (PDFs, text, databases)
STORAGE_DIR=../sites

# OCR Backend
# Choose 'tesseract' (Linux/macOS) or 'vision' (macOS only)
DEFAULT_OCR_BACKEND=tesseract

# Worker Configuration
# Number of background workers for each queue
FETCH_WORKERS=2
OCR_WORKERS=4
EXTRACTION_WORKERS=2
DEPLOY_WORKERS=1

# Optional: Centralized Logging
# LOKI_URL=http://localhost:3100/loki/api/v1/push
```

### Database Setup

Run database migrations to create queue tables:

```bash
# Initialize database and run migrations
clerk db upgrade

# Verify migration status
clerk db current

# View migration history
clerk db history
```

The migrations create two tables:

- **job_tracking**: Links RQ job IDs to sites for observability
- **site_progress**: Tracks per-site progress through pipeline stages

## Running Workers

### Option 1: Manual Workers (Development)

Start workers manually for development and testing:

```bash
# Start fetch workers (downloads PDFs)
clerk worker fetch -n 2

# Start OCR workers (parallel OCR processing)
clerk worker ocr -n 4

# Start extraction workers (entity extraction + DB compilation)
clerk worker extraction -n 2

# Start deploy worker (deployment to production)
clerk worker deploy -n 1
```

**Burst Mode** (process existing jobs then exit):

```bash
# Useful for testing - processes queued jobs then stops
clerk worker ocr --burst
```

### Option 2: Background Services (Production)

#### macOS (LaunchAgents)

Install workers as macOS background services:

```bash
# Install all workers as LaunchAgents
# Reads worker counts from .env file
clerk install-workers

# Workers start automatically on login
# Logs: ~/Library/Logs/clerk-worker-*.log

# Uninstall workers
clerk uninstall-workers
```

LaunchAgents configuration:
- **Location**: `~/Library/LaunchAgents/com.civic.band.clerk.worker-*.plist`
- **Auto-start**: Launches on user login
- **Keep-alive**: Automatically restarts if crashed
- **Logs**: `~/Library/Logs/clerk-worker-{type}-{n}.log`

#### Linux (systemd)

Create systemd unit files:

```ini
# /etc/systemd/system/clerk-worker-fetch@.service
[Unit]
Description=Clerk Fetch Worker %i
After=network.target redis.service postgresql.service

[Service]
Type=simple
User=clerk
WorkingDirectory=/opt/clerk
EnvironmentFile=/opt/clerk/.env
ExecStart=/opt/clerk/.venv/bin/clerk worker fetch -n 1
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Start workers:

```bash
# Start 2 fetch workers
sudo systemctl start clerk-worker-fetch@{1,2}

# Enable on boot
sudo systemctl enable clerk-worker-fetch@{1,2}

# Check status
sudo systemctl status clerk-worker-fetch@1
```

#### Docker Compose

Add workers to your `docker-compose.yml`:

```yaml
services:
  worker-fetch:
    image: clerk:latest
    command: clerk worker fetch -n 2
    environment:
      DATABASE_URL: postgresql://clerk:password@postgres:5432/clerk
      REDIS_URL: redis://redis:6379/0
      STORAGE_DIR: /data/sites
    volumes:
      - clerk-data:/data
    depends_on:
      - postgres
      - redis

  worker-ocr:
    image: clerk:latest
    command: clerk worker ocr -n 4
    environment:
      DATABASE_URL: postgresql://clerk:password@postgres:5432/clerk
      REDIS_URL: redis://redis:6379/0
      STORAGE_DIR: /data/sites
    volumes:
      - clerk-data:/data
    depends_on:
      - postgres
      - redis

volumes:
  clerk-data:
```

## Usage

### Enqueueing Sites

Add sites to the processing queue:

```bash
# Enqueue a single site
clerk enqueue pleasanton

# Enqueue multiple sites
clerk enqueue pleasanton oakland berkeley

# High-priority (jump to front of queue)
clerk enqueue pleasanton --priority high
```

Sites are processed through the pipeline automatically:
1. Fetch PDFs from source website
2. OCR all PDF pages in parallel
3. Extract entities (people, votes, motions)
4. Compile database with full-text search
5. Deploy to production

### Monitoring Progress

#### Queue Status

View overall queue health:

```bash
# Show queue depths and active sites
clerk status
```

Output:
```
Queue Status
============
high         0 jobs
fetch        2 jobs
ocr          47 jobs
extraction   1 jobs
deploy       0 jobs

Active Sites
============
pleasanton: ocr (23/50, 46.0%)
oakland: fetch
```

#### Site-Specific Progress

Track individual site progress:

```bash
# Detailed progress for a site
clerk status --subdomain pleasanton
```

Output:
```
Site Progress: pleasanton
=========================
Current Stage: ocr
Progress: 23/50 completed (46.0%)
Started: 2026-01-08 14:23:15
Last Updated: 2026-01-08 14:25:42

Pipeline Stages:
  ✓ fetch    - Complete
  → ocr      - In Progress (23/50)
    extraction - Pending
    deploy   - Pending
```

### Emergency Operations

#### Purge Site Jobs

Remove all jobs for a stuck site:

```bash
# Cancel and delete all jobs for a site
clerk purge pleasanton

# Output:
# Found 47 job(s) for site pleasanton
# Purged 47 job(s) from queues for site pleasanton
# Deleted database records for site pleasanton
```

This removes:
- Jobs from all RQ queues
- Job tracking records from PostgreSQL
- Site progress tracking

**Note**: Does not delete fetched PDFs or compiled databases.

#### Clear Queue

Emergency operation to clear an entire queue:

```bash
# Clear all jobs from OCR queue (nuclear option)
clerk purge-queue ocr

# Output:
# Cleared 127 job(s) from queue: ocr
```

**⚠️ Warning**: This affects ALL sites in the queue, not just one site. Use with caution.

## Troubleshooting

### Worker Issues

**Workers not processing jobs**:

```bash
# Check workers are running
ps aux | grep "clerk worker"

# macOS: Check LaunchAgent status
launchctl list | grep clerk

# Linux: Check systemd status
systemctl status clerk-worker-*
```

**Check worker logs**:

```bash
# macOS LaunchAgents
tail -f ~/Library/Logs/clerk-worker-fetch-1.log

# systemd
journalctl -u clerk-worker-fetch@1 -f

# Docker
docker-compose logs -f worker-fetch
```

### Connection Issues

**Redis connection errors**:

```bash
# Test Redis connection
redis-cli ping

# Check REDIS_URL format
echo $REDIS_URL
# Should be: redis://localhost:6379/0

# Check Redis is listening
netstat -an | grep 6379
```

**PostgreSQL connection errors**:

```bash
# Test PostgreSQL connection
psql $DATABASE_URL -c "SELECT 1"

# Check DATABASE_URL format
echo $DATABASE_URL
# Should be: postgresql://user:password@host:5432/dbname
```

### Job Failures

**View failed jobs** (via RQ):

```python
from redis import Redis
from rq import Queue
from rq.registry import FailedJobRegistry

redis_conn = Redis.from_url('redis://localhost:6379/0')
queue = Queue('ocr', connection=redis_conn)
failed = FailedJobRegistry(queue=queue)

for job_id in failed.get_job_ids():
    job = queue.fetch_job(job_id)
    print(f"Job {job_id}: {job.exc_info}")
```

**Requeue failed jobs**:

```python
for job_id in failed.get_job_ids():
    failed.requeue(job_id)
```

### Performance Issues

**Too many jobs queued**:

```bash
# Check queue depths
clerk status

# If OCR queue is very large, add more workers
clerk worker ocr -n 8  # Increase parallelism
```

**Workers crashing**:

```bash
# Check memory usage
top

# OCR is memory-intensive, reduce workers if OOM
# In .env:
# OCR_WORKERS=2  # Reduce from 4
```

**Slow processing**:

- **Fetch**: Slow website, network issues → Increase `FETCH_WORKERS`
- **OCR**: CPU-bound → Increase `OCR_WORKERS` or use faster OCR backend (`vision` on macOS)
- **Extraction**: CPU-bound → Increase `EXTRACTION_WORKERS`

## Advanced Topics

### Custom Job Timeouts

Jobs have default timeouts to prevent hanging:

- Fetch: 10 minutes
- OCR: 10 minutes
- Extraction: 2 hours
- Deploy: 10 minutes

Modify in `src/clerk/workers.py` if needed.

### Monitoring with RQ Dashboard

Install [RQ Dashboard](https://github.com/Parallels/rq-dashboard) for web UI:

```bash
pip install rq-dashboard

# Run dashboard
rq-dashboard --redis-url redis://localhost:6379/0

# Open: http://localhost:9181
```

Features:
- View queues and job counts
- Monitor workers and their status
- Inspect job details and failures
- Requeue failed jobs

### Scaling Workers Across Machines

Run workers on multiple machines pointing to same Redis/PostgreSQL:

**Machine 1** (fetch + deploy):
```bash
export DATABASE_URL=postgresql://clerk:password@db-server:5432/clerk
export REDIS_URL=redis://redis-server:6379/0

clerk worker fetch -n 4
clerk worker deploy -n 1
```

**Machine 2** (OCR):
```bash
export DATABASE_URL=postgresql://clerk:password@db-server:5432/clerk
export REDIS_URL=redis://redis-server:6379/0

clerk worker ocr -n 16  # Dedicated OCR machine
```

### Priority Queue Usage

Use the high-priority queue for urgent site updates:

```bash
# Normal priority (default)
clerk enqueue pleasanton

# High priority (jumps queue)
clerk enqueue pleasanton --priority high
```

High-priority jobs go to the `high` queue which workers check first before polling their assigned queues.

## Best Practices

### Worker Sizing

**Development (local machine)**:
- Fetch: 1-2 workers
- OCR: 2-4 workers (CPU-bound)
- Extraction: 1-2 workers
- Deploy: 1 worker

**Production (dedicated server)**:
- Fetch: 2-4 workers
- OCR: 4-8 workers (scale with CPU cores)
- Extraction: 2-4 workers
- Deploy: 1-2 workers

**Production (distributed)**:
- Dedicated OCR machines with 8-16 workers each
- Fetch/extraction/deploy on separate machines

### Monitoring

**Check queue health regularly**:

```bash
# Add to cron (every 5 minutes)
*/5 * * * * /usr/local/bin/clerk status > /var/log/clerk-status.log
```

**Set up alerting** (example with Prometheus):

```python
# Export metrics for Prometheus
from prometheus_client import Gauge, start_http_server
from redis import Redis
from rq import Queue

queue_depth = Gauge('clerk_queue_depth', 'Jobs in queue', ['queue'])

def collect_metrics():
    redis_conn = Redis.from_url(os.getenv('REDIS_URL'))
    for queue_name in ['fetch', 'ocr', 'extraction', 'deploy']:
        queue = Queue(queue_name, connection=redis_conn)
        queue_depth.labels(queue=queue_name).set(len(queue))

start_http_server(8000)  # Prometheus scrapes :8000/metrics
```

### Graceful Shutdowns

**macOS LaunchAgents**:
```bash
launchctl stop com.civic.band.clerk.worker-ocr-1
```

**systemd**:
```bash
sudo systemctl stop clerk-worker-ocr@1
```

**Manual workers**: Press `Ctrl+C` - RQ workers handle `SIGINT` gracefully, finishing current jobs before exiting.

## See Also

- [RQ Documentation](https://python-rq.org/)
- [Redis Documentation](https://redis.io/documentation)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Implementation Details](../plans/implementation-summary-task-queue.md)
