# Task Queue System Design

**Date**: 2026-01-06
**Status**: Approved
**Authors**: Claude Sonnet 4.5, phildini

## Executive Summary

This design introduces a distributed task queue system to replace the current single-job launchd implementation. The new system enables parallel processing of sites across multiple workers and machines, improving throughput by 10-15x while maintaining observability and control.

**Key Benefits:**
- **10-15x throughput improvement** - Process 10-15 sites/hour vs 1 site/hour
- **Multi-node scaling** - Distribute workers across multiple machines via Redis
- **Resource saturation** - Tune worker counts to maximize CPU/memory usage
- **Better observability** - Track each site through fetch → OCR → extraction → deploy pipeline
- **Priority queues** - Jump critical sites to the front of the line
- **Easy purge operations** - Remove all jobs for a site across all queues

## Motivation

### Current System Limitations

The existing launchd-based system has significant bottlenecks:

1. **Serialization**: Lock file allows only one `clerk update -n` process at a time
2. **Single-site processing**: Each invocation processes one site sequentially through all stages
3. **Resource underutilization**: On an 8-core machine, only ~1-2 cores are used during fetch/deploy
4. **No parallelism**: OCR processing happens sequentially even though pages are independent
5. **Poor observability**: Only database `status` field shows where sites are in pipeline
6. **No priority**: All sites processed FIFO, no way to expedite critical sites

### Requirements

1. **Resource saturation** - Use close to 100% of available CPU and memory
2. **Stage-based parallelism** - Different sites can be in different stages simultaneously
3. **Sequential per-site progression** - Each site moves through stages sequentially
4. **Fan-out/fan-in support** - One fetch job spawns N OCR jobs that must all complete
5. **Observability** - Track "Site X: ocr 45/100 pages (45%)"
6. **Priority queues** - Jump sites to head of line
7. **Purge operations** - Remove all jobs for a site from all queues
8. **Multi-node support** - Run workers on different machines

## Architecture

### High-Level Design

```
┌─────────────────┐
│   PostgreSQL    │  ← Job metadata, site progress tracking
│    (civic.db)   │     (observability)
└─────────────────┘

┌─────────────────┐
│  Managed Redis  │  ← Active job queues, coordinator events
│                 │     (queue management)
└─────────────────┘

┌─────────────────┐
│ Fetch Workers   │  ← Download PDFs (I/O bound, high parallelism)
│  (10-20 workers)│
└─────────────────┘

┌─────────────────┐
│  OCR Workers    │  ← Extract text from PDFs (CPU bound)
│   (8-16 workers)│
└─────────────────┘

┌─────────────────┐
│Extract Workers  │  ← spaCy entity extraction (memory intensive)
│   (2-4 workers) │
└─────────────────┘

┌─────────────────┐
│Deploy Workers   │  ← Publish results
│   (2 workers)   │
└─────────────────┘
```

### Technology Choices

**Queue System: RQ (Redis Queue)**

Chosen over custom implementation or Celery:

- **Simplicity**: 10x smaller than Celery (200KB vs 2.5MB)
- **Redis-only**: Matches our Redis requirement for multi-node
- **Job dependencies**: Built-in `depends_on` for fan-out/fan-in
- **Monitoring**: Built-in web dashboard
- **Less code**: ~100 lines of RQ integration vs ~500 lines custom

**Database: PostgreSQL (civic.db)**

Existing PostgreSQL database used for:

- Job metadata tracking (which RQ job belongs to which site)
- Site progress tracking (observability: "ocr 45/100 pages")
- Audit trail (job history)

**Queue Backend: Managed Redis**

- Multi-node worker support (workers on different machines)
- High availability with automatic failover
- Professional queue management without maintenance burden
- Recommended services: AWS ElastiCache, Redis Cloud, Azure Cache

### Processing Pipeline

```
1. User: clerk enqueue site.civic.band
   ↓
2. Create fetch job → queue:fetch
   ↓
3. Fetch worker: download PDFs, count pages
   ↓
4. Create 100 OCR jobs → queue:ocr
   Create coordinator job (depends_on: all 100 OCR jobs)
   ↓
5. OCR workers: process pages in parallel (fan-out)
   Each completion increments site_progress.stage_completed
   ↓
6. Coordinator job: runs when ALL OCR jobs complete (fan-in)
   ↓
7. Create extraction job → queue:extraction
   ↓
8. Extraction worker: process text files
   ↓
9. Create deploy job → queue:deploy
   ↓
10. Deploy worker: publish results
    ↓
11. Site complete
```

## Database Schema

### New Tables

**job_tracking** - Links RQ jobs to sites for observability

```sql
CREATE TABLE job_tracking (
    rq_job_id VARCHAR PRIMARY KEY,      -- RQ's job ID
    site_id VARCHAR NOT NULL,           -- Subdomain
    job_type VARCHAR NOT NULL,          -- fetch-site, ocr-page, extract-site, deploy-site
    stage VARCHAR,                      -- fetch, ocr, extraction, deploy
    created_at TIMESTAMP,
    INDEX idx_site_id (site_id)
);
```

**site_progress** - Tracks site progress through pipeline

```sql
CREATE TABLE site_progress (
    site_id VARCHAR PRIMARY KEY,
    current_stage VARCHAR,              -- fetch, ocr, extraction, deploy, completed
    stage_total INTEGER DEFAULT 0,      -- Total items in current stage (e.g., 100 PDFs)
    stage_completed INTEGER DEFAULT 0,  -- Completed items (e.g., 45 PDFs)
    started_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**Design Notes:**

- Generic `stage_total`/`stage_completed` works for any multi-step stage (OCR, extraction, etc.)
- No hardcoded stage-specific columns (avoids `ocr_total`, `extraction_total`, etc.)
- Lightweight tracking - only stores counters, not job results
- PostgreSQL indexes on `site_id` for fast lookups

### Existing Tables

**sites** - No schema changes required

Existing `status` field can be phased out or kept for compatibility:
- Old system uses: `deployed`, `needs_ocr`, `needs_extraction`
- New system tracks progress in `site_progress` table
- Migration path: sites can coexist in both systems during transition

## Queue Architecture

### Queue Structure

**Redis Queues:**

- `queue:express` - High-priority jobs (all stages check this first)
- `queue:fetch` - Fetch jobs (normal priority)
- `queue:ocr` - OCR jobs (normal priority)
- `queue:extraction` - Extraction jobs (normal priority)
- `queue:deploy` - Deploy jobs (normal priority)

**Worker Poll Order:**

```python
# Each worker checks express queue first, then its specific queue
fetch_worker.queues = [queue:express, queue:fetch]
ocr_worker.queues = [queue:express, queue:ocr]
extraction_worker.queues = [queue:express, queue:extraction]
deploy_worker.queues = [queue:express, queue:deploy]
```

This ensures high-priority jobs always process first regardless of stage.

### Fan-Out/Fan-In Pattern

**Problem**: Fetch creates 100 OCR jobs; extraction must wait for ALL to complete.

**Solution**: RQ's `depends_on` with multiple dependencies

```python
# Fetch job completes
def fetch_site_job(site_id):
    # Download PDFs
    pdf_files = fetch_pdfs(site_id)

    # Spawn OCR jobs (fan-out)
    ocr_job_ids = []
    for pdf in pdf_files:
        job = ocr_queue.enqueue(ocr_page_job, site_id, pdf)
        ocr_job_ids.append(job.id)

    # Create coordinator that waits for ALL OCR jobs (fan-in)
    extraction_queue.enqueue(
        ocr_complete_coordinator,
        site_id=site_id,
        depends_on=ocr_job_ids  # RQ waits for ALL
    )

# Coordinator runs ONLY when all dependencies complete
def ocr_complete_coordinator(site_id):
    # Update progress
    update_site_progress(conn, site_id, stage='extraction')

    # Spawn extraction job
    extraction_queue.enqueue(extraction_job, site_id)
```

**Benefits:**
- No custom coordinator process blocking a worker slot
- RQ manages dependency tracking
- Automatic retry if any OCR job fails
- Clear progress tracking via `site_progress` table

## Worker Implementation

### Worker Base Pattern

RQ handles worker process management. We just provide job functions:

```python
# workers.py

def fetch_site_job(site_id, all_years=False, all_agendas=False):
    """RQ job: Fetch PDFs for a site."""
    # Use existing fetch logic
    site = get_site_by_subdomain(conn, site_id)
    fetcher = get_fetcher(site, all_years=all_years, all_agendas=all_agendas)
    fetch_internal(site_id, fetcher)

    # Count PDFs for tracking
    pdf_count = count_pdfs(site_id)

    # Update progress
    with civic_db_connection() as conn:
        update_site_progress(conn, site_id, stage='ocr', stage_total=pdf_count)

    # Spawn OCR jobs (implementation shown above)

def ocr_page_job(site_id, pdf_path, backend='tesseract'):
    """RQ job: OCR a single PDF page."""
    from .ocr_utils import ocr_single_page

    output_path = pdf_path.replace('/pdfs/', '/txt/').replace('.pdf', '.txt')
    ocr_single_page(pdf_path, output_path, backend=backend)

    # Increment progress
    with civic_db_connection() as conn:
        increment_stage_progress(conn, site_id)

def extraction_job(site_id):
    """RQ job: Extract entities from text."""
    # Use existing extraction logic
    build_db_from_text_internal(site_id, extract_entities=True)

    # Spawn deploy job
    deploy_queue.enqueue(deploy_job, site_id)

def deploy_job(site_id):
    """RQ job: Deploy site."""
    # Use existing deploy logic
    pm.hook.deploy_municipality(subdomain=site_id)

    # Mark complete
    with civic_db_connection() as conn:
        update_site_progress(conn, site_id, stage='completed')
```

### Starting Workers

**CLI command:**

```bash
clerk worker fetch -n 10    # Start 10 fetch workers
clerk worker ocr -n 8        # Start 8 OCR workers
clerk worker extraction -n 2 # Start 2 extraction workers
clerk worker deploy -n 2     # Start 2 deploy workers
```

**Implementation:**

```python
@cli.command()
@click.argument("worker_type", type=click.Choice(["fetch", "ocr", "extraction", "deploy", "all"]))
@click.option("--num-workers", "-n", type=int, default=1)
def worker(worker_type, num_workers):
    """Start RQ workers."""
    from rq import Worker
    from rq.worker_pool import WorkerPool

    queue_map = {
        "fetch": [high_queue, fetch_queue],
        "ocr": [high_queue, ocr_queue],
        # ...
    }

    queues = queue_map[worker_type]

    if num_workers == 1:
        worker = Worker(queues, connection=redis_conn)
        worker.work(with_scheduler=True)
    else:
        with WorkerPool(queues, num_workers=num_workers, connection=redis_conn) as pool:
            pool.start()
```

## Deployment Strategies

### Option 1: macOS LaunchAgents (Recommended for Mac)

**Use case**: Mac development machines, Mac Mini production servers

**Benefits**:
- Native macOS integration
- Vision Framework support (3-5x faster OCR on Apple Silicon)
- Automatic startup on boot
- Easy monitoring with system tools

**Configuration**: `.env` file

```bash
FETCH_WORKERS=10
OCR_WORKERS=8
EXTRACTION_WORKERS=2
DEPLOY_WORKERS=2
DEFAULT_OCR_BACKEND=vision
```

**Installation**:

```bash
clerk install-workers
# Creates N LaunchAgent plists based on .env
# Each worker is a separate launchd job
```

**Worker distribution**:
```
com.civicband.worker.fetch.1
com.civicband.worker.fetch.2
...
com.civicband.worker.fetch.10
com.civicband.worker.ocr.1
...
```

### Option 2: Linux systemd

**Use case**: Single Linux server

**Benefits**:
- Native Linux integration
- Integrated with journald logging
- Resource limits via systemd
- Automatic startup on boot

**Configuration**: Same `.env` file as macOS

**Installation**:

```bash
sudo clerk install-workers
# Creates systemd services
```

**Worker distribution**:
```
clerk-worker@fetch-1.service
clerk-worker@fetch-2.service
...
```

### Option 3: Docker Compose (Multi-node Linux)

**Use case**: Multiple Linux servers, container orchestration

**Benefits**:
- Multi-node support
- Container isolation
- Easy horizontal scaling
- Works on any Linux with Docker

**⚠️ Not recommended for macOS** - Docker Desktop has poor file I/O performance

**Configuration**: Same `.env` file

**Deployment**:

```yaml
# docker-compose.yml
services:
  fetch-workers:
    image: clerk:latest
    command: clerk worker fetch -n 1
    env_file: .env
    deploy:
      replicas: ${FETCH_WORKERS:-10}  # From .env
```

**Scaling**:

```bash
# Edit .env: FETCH_WORKERS=20
docker-compose up -d --scale fetch-workers=20
```

## CLI Commands

### Queue Management

```bash
# Enqueue sites
clerk enqueue site.civic.band
clerk enqueue site1.civic.band site2.civic.band --priority=high

# Monitor
clerk status                           # Overall queue status
clerk status --site-id site.civic.band # Specific site progress
clerk dashboard                        # Web UI (http://localhost:9181)

# Control
clerk purge site.civic.band            # Remove all jobs for site
clerk purge-queue ocr                  # Clear entire OCR queue
```

### Worker Management

```bash
# macOS/Linux: Install workers as background services
clerk install-workers
clerk uninstall-workers

# Manual: Start workers for development/testing
clerk worker fetch -n 10
clerk worker ocr -n 8 --burst  # Exit when queue empty
```

### Database Migrations

```bash
# Run migrations
clerk db upgrade

# Check current version
clerk db current

# Show history
clerk db history

# Create new migration
clerk db migrate -m "add new table"

# Rollback
clerk db downgrade
```

## Observability

### Site Progress Tracking

**Query site progress**:

```python
# Get progress for site
with civic_db_connection() as conn:
    progress = get_site_progress(conn, site_id)

# Returns:
{
    'site_id': 'example.civic.band',
    'current_stage': 'ocr',
    'stage_total': 100,
    'stage_completed': 45,
    'started_at': datetime(2026, 1, 6, 10, 0, 0),
    'updated_at': datetime(2026, 1, 6, 10, 5, 23)
}
```

**CLI display**:

```bash
$ clerk status --site-id example.civic.band

Site: example.civic.band
Current stage: ocr
Progress: 45/100 (45.0%)
Started: 2026-01-06 10:00:00
Updated: 2026-01-06 10:05:23
```

### Queue Status

**CLI display**:

```bash
$ clerk status

=== Queue Status ===
High priority: 0 jobs
Fetch:         3 jobs
OCR:           247 jobs
Extraction:    1 jobs
Deploy:        0 jobs

=== Active Sites ===
  site1.civic.band: ocr (45/100, 45%)
  site2.civic.band: extraction (12/50, 24%)
  site3.civic.band: fetch
```

### RQ Dashboard

Built-in web UI at http://localhost:9181

Features:
- All queues and job counts
- Worker status and statistics
- Failed jobs with error details
- Job history and timing

### Logging

Workers send logs to:
- Console (JSON formatted)
- Loki (if configured via `LOKI_URL`)
- Files (macOS LaunchAgents: `logs/worker-*.log`)

## Priority Queues

### Implementation

**Three priority levels**:
- `high` - Goes to `queue:express` (checked first by all workers)
- `normal` - Goes to stage-specific queue
- `low` - Same as normal (future: could implement weighted polling)

**Usage**:

```bash
# High priority - jumps to front of all queues
clerk enqueue urgent.civic.band --priority=high

# Normal priority (default)
clerk enqueue example.civic.band
```

**Worker behavior**:

```python
# Workers always check express queue first
worker.queues = [queue:express, queue:fetch]

# Poll order:
# 1. Check queue:express (high priority)
# 2. If empty, check queue:fetch (normal priority)
```

This ensures high-priority jobs process immediately regardless of queue depth.

## Purge Operations

### Purge Site (All Jobs)

```bash
clerk purge example.civic.band
```

**Implementation**:

1. Query `job_tracking` for all RQ job IDs for site
2. Cancel and delete each job from RQ
3. Remove from all Redis queues (express, fetch, ocr, extraction, deploy)
4. Delete from `job_tracking` table
5. Delete from `site_progress` table

```python
def purge_site(site_id):
    # Get all RQ jobs for site
    with civic_db_connection() as conn:
        jobs = get_jobs_for_site(conn, site_id)

    # Cancel each job in RQ
    for job_data in jobs:
        job_id = job_data['rq_job_id']

        for queue in [high_queue, fetch_queue, ocr_queue, extraction_queue, deploy_queue]:
            try:
                job = queue.fetch_job(job_id)
                if job:
                    job.cancel()
                    job.delete()
            except:
                pass

    # Clean up tracking
    with civic_db_connection() as conn:
        delete_site_progress(conn, site_id)
        delete_jobs_for_site(conn, site_id)
```

### Purge Queue (Emergency)

```bash
clerk purge-queue ocr
```

**Implementation**:

```python
def purge_queue(queue_name):
    queues = {
        "fetch": fetch_queue,
        "ocr": ocr_queue,
        # ...
    }

    queue = queues[queue_name]
    queue.empty()  # RQ built-in: removes all jobs
```

## Worker Tuning

### Calculating Worker Counts

**Formulas**:

| Worker Type | Formula | Reasoning |
|-------------|---------|-----------|
| Fetch | 2-3x CPU cores | I/O bound, waiting on network |
| OCR | 1x CPU cores | CPU bound, text extraction |
| Extraction | RAM ÷ 8GB | Memory intensive, spaCy models |
| Deploy | Fixed (2) | Light work, few needed |

**Example (8-core, 32GB machine)**:

```bash
FETCH_WORKERS=16       # 2x 8 cores
OCR_WORKERS=8          # 1x 8 cores
EXTRACTION_WORKERS=4   # 32GB / 8GB
DEPLOY_WORKERS=2       # Fixed
```

**Total**: 30 worker processes

### Hardware-Specific Examples

**MacBook Pro M1 Max (10 cores, 32GB)**:
```bash
FETCH_WORKERS=20
OCR_WORKERS=10
EXTRACTION_WORKERS=4
DEPLOY_WORKERS=2
DEFAULT_OCR_BACKEND=vision  # 3-5x faster
```

**Mac Mini M2 (8 cores, 16GB)**:
```bash
FETCH_WORKERS=16
OCR_WORKERS=8
EXTRACTION_WORKERS=2
DEPLOY_WORKERS=2
DEFAULT_OCR_BACKEND=vision
```

**Linux Server (16 cores, 64GB)**:
```bash
FETCH_WORKERS=32
OCR_WORKERS=16
EXTRACTION_WORKERS=8
DEPLOY_WORKERS=2
DEFAULT_OCR_BACKEND=tesseract
```

## Migration Path

### For Existing Users

**Old system** (launchd + lock file):
- Single `clerk update -n` every 60 seconds
- Lock file prevents concurrent execution
- Processes 1 site at a time
- ~24 sites per day

**New system** (RQ + workers):
- Multiple workers processing in parallel
- 10-15 sites per hour
- ~240-360 sites per day
- 10-15x throughput improvement

### Migration Steps

1. **Install Redis** (managed service recommended)
2. **Update .env** with worker counts and Redis URL
3. **Run migrations** (`clerk db upgrade`)
4. **Uninstall old launchd jobs** (`launchctl unload ...`)
5. **Install new workers** (`clerk install-workers`)
6. **Test with small site** (`clerk enqueue test-site.civic.band`)
7. **Monitor progress** (`clerk status`, `clerk dashboard`)

See [Migration Guide](../user-guide/migration-to-queue-system.md) for detailed instructions.

## Alternatives Considered

### 1. Custom Queue System

**Considered**: Building custom worker loop, Redis operations, job serialization

**Rejected**:
- 500+ lines of custom code vs 100 lines RQ integration
- Need to implement: retries, failure handling, monitoring, job dependencies
- RQ provides all this out-of-box with 10x less code

### 2. Celery

**Considered**: More feature-rich than RQ, supports multiple brokers

**Rejected**:
- 10x larger installation (2.5MB vs 200KB)
- More complex configuration
- Overkill for our use case
- We only need Redis (not RabbitMQ, SQS, etc.)

### 3. No Coordinators (Pure Dependencies)

**Considered**: Using only RQ's `depends_on` without coordinator jobs

**Example**:
```python
# Spawn all 100 OCR jobs with dependencies
ocr_jobs = [enqueue(ocr_page_job, pdf) for pdf in pdfs]

# Extraction depends on ALL OCR jobs
enqueue(extraction_job, depends_on=ocr_jobs)
```

**Rejected**:
- No way to track progress (45/100 OCR jobs done)
- Can't update `site_progress` table incrementally
- Harder to observe what's happening

**Solution**: Lightweight coordinator jobs that just update progress and spawn next stage

### 4. SQLite for Queue State

**Considered**: Store queue state in SQLite instead of Redis

**Rejected**:
- No multi-node support (can't distribute workers across machines)
- SQLite has locking issues with high concurrency
- Redis is industry standard for queues
- We need Redis anyway for RQ

**Decision**: Use Redis for queue state, PostgreSQL for observability/audit trail

### 5. Hard-coded Stage Columns

**Considered**: `ocr_total`, `ocr_completed`, `extraction_total`, `extraction_completed` columns

**Rejected**:
- Inflexible - need schema change for new stages
- Repetitive code
- Harder to query generically

**Solution**: Generic `stage_total`/`stage_completed` works for any stage

## Performance Characteristics

### Expected Throughput

**Old system**:
- 1 site every ~60 minutes (sequential)
- ~24 sites per day (24/7 operation)

**New system (8-core, 32GB machine)**:
- 16 fetch + 8 OCR + 4 extraction + 2 deploy workers
- ~10-15 sites per hour
- ~240-360 sites per day
- **10-15x improvement**

### Resource Usage

**CPU**:
- Target: 80-90% utilization
- Fetch workers: Low CPU (I/O bound)
- OCR workers: High CPU (text extraction)
- Extraction workers: Medium CPU (spaCy processing)

**Memory**:
- Fetch workers: ~100-200MB each
- OCR workers: ~500MB each
- Extraction workers: ~5-8GB each (spaCy models)
- Deploy workers: ~100-200MB each

**Example (8-core, 32GB machine)**:
- 16 fetch = 3.2GB
- 8 OCR = 4GB
- 4 extraction = 24GB
- 2 deploy = 0.4GB
- **Total**: ~32GB (saturates available RAM)

### Scaling Characteristics

**Horizontal scaling** (multi-node):
- Linear throughput increase with more machines
- Redis handles coordination across nodes
- Shared PostgreSQL for state
- Shared storage (NFS, S3) for PDFs/text

**Vertical scaling** (bigger machine):
- More cores → more OCR workers
- More RAM → more extraction workers
- Diminishing returns above 16 cores (I/O becomes bottleneck)

## Security Considerations

### Redis Security

- Use managed Redis with authentication (`REDIS_URL=redis://user:pass@host`)
- Enable TLS for production (`rediss://` URL)
- Firewall Redis port (only allow worker nodes)
- Rotate credentials regularly

### Database Security

- Use PostgreSQL role-based access
- Minimum privileges for worker role (SELECT, INSERT, UPDATE on specific tables)
- Use connection pooling with limits
- Enable SSL for PostgreSQL connections

### Job Isolation

- Each job runs in separate process (RQ worker pool)
- Jobs can't interfere with each other
- Failed jobs don't crash workers (RQ handles exceptions)
- Malicious job can't access other jobs' data

## Testing Strategy

### Unit Tests

- Test job functions in isolation
- Mock RQ dependencies
- Test database helpers
- Test progress tracking logic

### Integration Tests

- Test full pipeline (fetch → OCR → extraction → deploy)
- Test coordinator fan-out/fan-in
- Test priority queue behavior
- Test purge operations

### Load Tests

- Enqueue 100 sites simultaneously
- Verify workers process in parallel
- Verify no resource exhaustion
- Verify correct progress tracking

## Open Questions

1. **Job retention**: How long to keep completed jobs in Redis?
   - **Answer**: RQ default is to keep successful jobs for 500 seconds, failed jobs forever
   - **Recommendation**: Keep failed jobs for 7 days for debugging, then purge

2. **Failed job retry**: Should failed jobs auto-retry?
   - **Answer**: RQ supports retries via `@job(retry=Retry(max=3))`
   - **Recommendation**: Retry transient errors (network), don't retry permanent errors (missing file)

3. **Coordinator timeout**: What if coordinator job gets stuck?
   - **Answer**: RQ has job timeout (default 180s, configurable)
   - **Recommendation**: Set timeout based on expected stage duration (OCR: 10m, extraction: 2h)

4. **Queue priority starvation**: Can low-priority jobs starve if high-priority constantly added?
   - **Answer**: Currently yes (strict priority)
   - **Recommendation**: Monitor high-priority queue depth, alert if constantly full

## Future Enhancements

### Phase 2 (Future)

1. **Weighted priority**: Instead of strict priority, use weighted random selection
2. **Rate limiting**: Limit requests per second to external services
3. **Job scheduling**: Schedule sites to run at specific times (e.g., "run every Monday")
4. **Dead letter queue**: Separate queue for repeatedly failed jobs
5. **Prometheus metrics**: Export queue depth, worker utilization, job timing
6. **Automatic scaling**: Adjust worker counts based on queue depth

### Phase 3 (Future)

1. **Kubernetes deployment**: Helm charts for k8s clusters
2. **Dynamic worker allocation**: Auto-scale workers based on load
3. **Cost optimization**: Spot instances for batch processing
4. **Multi-region**: Distribute workers across AWS regions

## Implementation Plan

See [Implementation Plan](2026-01-06-task-queue-implementation-plan.md) for detailed implementation steps.

**Estimated effort**: 3-4 weeks

1. Week 1: Core queue system (RQ integration, database schema, basic workers)
2. Week 2: Deployment scripts (LaunchD, systemd, Docker)
3. Week 3: CLI commands, monitoring, testing
4. Week 4: Documentation, migration guide, testing with real data

## References

- [RQ Documentation](https://python-rq.org/)
- [RQ vs Celery Comparison](https://judoscale.com/blog/choose-python-task-queue)
- [Task Queue Best Practices](https://offlinemark.com/task-queues-redis-python-celery-rq/)
- [Alembic Migrations](https://alembic.sqlalchemy.org/)

## Appendix A: Database Migration

```python
# alembic/versions/XXXX_add_queue_tables.py

"""Add task queue tables

Revision ID: XXXX
Revises: YYYY
Create Date: 2026-01-06
"""

from alembic import op
import sqlalchemy as sa

def upgrade():
    # job_tracking table
    op.create_table(
        'job_tracking',
        sa.Column('rq_job_id', sa.String(), nullable=False),
        sa.Column('site_id', sa.String(), nullable=False),
        sa.Column('job_type', sa.String(), nullable=False),
        sa.Column('stage', sa.String()),
        sa.Column('created_at', sa.DateTime()),
        sa.PrimaryKeyConstraint('rq_job_id')
    )
    op.create_index('idx_job_tracking_site_id', 'job_tracking', ['site_id'])

    # site_progress table
    op.create_table(
        'site_progress',
        sa.Column('site_id', sa.String(), nullable=False),
        sa.Column('current_stage', sa.String()),
        sa.Column('stage_total', sa.Integer(), server_default='0'),
        sa.Column('stage_completed', sa.Integer(), server_default='0'),
        sa.Column('started_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
        sa.PrimaryKeyConstraint('site_id')
    )

def downgrade():
    op.drop_table('site_progress')
    op.drop_table('job_tracking')
```

## Appendix B: Example .env Configuration

```bash
# Database
DATABASE_URL=postgresql://civic:password@localhost:5432/civic

# Redis (managed service)
REDIS_URL=redis://user:pass@redis.example.com:6379

# Storage
STORAGE_DIR=/data/sites

# Worker counts (8-core, 32GB machine)
FETCH_WORKERS=16
OCR_WORKERS=8
EXTRACTION_WORKERS=4
DEPLOY_WORKERS=2

# OCR backend
DEFAULT_OCR_BACKEND=tesseract  # or vision (macOS only)

# Extraction
ENABLE_EXTRACTION=1
SPACY_N_PROCESS=2

# Logging
LOKI_URL=https://loki.example.com
```

## Appendix C: Worker Scaling Calculator

```python
import os

def calculate_workers():
    """Calculate optimal worker counts based on system resources."""

    # Detect CPU cores
    cpu_cores = os.cpu_count()

    # Detect RAM (Linux)
    with open('/proc/meminfo') as f:
        meminfo = dict((i.split()[0].rstrip(':'), int(i.split()[1])) for i in f.readlines())
    ram_gb = meminfo['MemTotal'] / 1024 / 1024

    # Calculate workers
    fetch_workers = cpu_cores * 2
    ocr_workers = cpu_cores
    extraction_workers = max(1, int(ram_gb / 8))
    deploy_workers = 2

    print(f"System: {cpu_cores} cores, {ram_gb:.1f}GB RAM")
    print(f"Recommended worker counts:")
    print(f"  FETCH_WORKERS={fetch_workers}")
    print(f"  OCR_WORKERS={ocr_workers}")
    print(f"  EXTRACTION_WORKERS={extraction_workers}")
    print(f"  DEPLOY_WORKERS={deploy_workers}")

if __name__ == '__main__':
    calculate_workers()
```

---

**End of Design Document**
