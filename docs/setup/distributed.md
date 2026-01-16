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
