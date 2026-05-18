# Monitoring Your Clerk Pipeline

This guide covers monitoring and health checking for your clerk pipeline using Redis commands and system tools.

## Quick Health Check

### Check Service Connectivity

```bash
# Redis
redis-cli ping
# Expected: PONG

# SQLite (default)
sqlite3 civic.db "SELECT COUNT(*) FROM sites;"
# Expected: A number

# PostgreSQL (if configured)
psql $DATABASE_URL -c "SELECT COUNT(*) FROM sites;"
# Expected: A number
```

### Check Worker Status

```bash
# List running workers
ps aux | grep "clerk worker"

# Expected: One or more clerk worker processes
```

### Check Queue Depths

```bash
redis-cli LLEN rq:queue:fetch
redis-cli LLEN rq:queue:ocr
redis-cli LLEN rq:queue:compilation
redis-cli LLEN rq:queue:deploy
redis-cli LLEN rq:queue:failed
```

If queues are growing and workers are running, your system is catching up. If queues keep growing, you may need more workers.

## Queue Monitoring

### View Queue Depths

```bash
# Watch queue depths in real-time
watch -n 2 "echo 'Fetch:' && redis-cli LLEN rq:queue:fetch && echo 'OCR:' && redis-cli LLEN rq:queue:ocr && echo 'Compilation:' && redis-cli LLEN rq:queue:compilation && echo 'Failed:' && redis-cli LLEN rq:queue:failed"
```

### List Jobs in Queue

```bash
# Show first 10 jobs in fetch queue
redis-cli LRANGE rq:queue:fetch 0 10

# Show all failed jobs
redis-cli LRANGE rq:queue:failed 0 -1
```

### Check Job Details

```bash
# Get job details (requires job ID from queue listing)
redis-cli GET rq:job:JOB_ID
```

## Worker Monitoring

### Monitor Worker Processes

```bash
# List all worker processes with CPU/memory
ps aux | grep "clerk worker" | grep -v grep

# Monitor resource usage in real-time
top -p $(pgrep -f "clerk worker" | tr '\n' ',')
```

### Check Worker Registration

```bash
# List registered workers in Redis
redis-cli KEYS "rq:worker:*"

# Get worker details
redis-cli GET "rq:worker:*worker-name*"
```

## Database Health

### Check Site Status

Using SQLite:

```bash
# Count total sites
sqlite3 civic.db "SELECT COUNT(*) FROM sites;"

# List sites by status
sqlite3 civic.db "SELECT subdomain, status, last_updated FROM sites ORDER BY last_updated DESC;"

# Check sites stuck in progress (not updated in 2+ hours)
sqlite3 civic.db "SELECT subdomain, status, last_updated FROM sites WHERE last_updated < datetime('now', '-2 hours');"
```

Using PostgreSQL (if configured):

```bash
# Count total sites
psql $DATABASE_URL -c "SELECT COUNT(*) FROM sites;"

# List sites by status
psql $DATABASE_URL -c "SELECT subdomain, status, last_updated FROM sites ORDER BY last_updated DESC;"

# Check sites stuck in progress (not updated in 2+ hours)
psql $DATABASE_URL -c "SELECT subdomain, status, last_updated FROM sites WHERE last_updated < NOW() - INTERVAL '2 hours';"
```

### Verify Pipeline Progression

SQLite:
```bash
sqlite3 civic.db "SELECT status, COUNT(*) FROM sites GROUP BY status;"
```

PostgreSQL:
```bash
psql $DATABASE_URL -c "SELECT status, COUNT(*) FROM sites GROUP BY status;"
```

## Monitoring Patterns

### Real-Time Pipeline Status

```bash
#!/bin/bash
# continuous-monitor.sh - Monitor pipeline every 5 seconds

while true; do
  clear
  echo "=== Clerk Pipeline Status ==="
  echo "Time: $(date)"
  echo ""
  echo "=== Queue Depths ==="
  echo -n "Fetch: "
  redis-cli LLEN rq:queue:fetch
  echo -n "OCR: "
  redis-cli LLEN rq:queue:ocr
  echo -n "Compilation: "
  redis-cli LLEN rq:queue:compilation
  echo -n "Deploy: "
  redis-cli LLEN rq:queue:deploy
  echo -n "Failed: "
  redis-cli LLEN rq:queue:failed
  echo ""
  echo "=== Workers ==="
  ps aux | grep "clerk worker" | grep -v grep | wc -l
  echo ""
  echo "=== Recent Sites ==="
  sqlite3 civic.db "SELECT subdomain, status, last_updated FROM sites ORDER BY last_updated DESC LIMIT 5;" 2>/dev/null || echo "Database unavailable"
  sleep 5
done
```

Run it with:
```bash
bash continuous-monitor.sh
```

### Alert on Queue Growth

```bash
#!/bin/bash
# alert-on-queue-growth.sh - Alert if queues exceed thresholds

FETCH_QUEUE=$(redis-cli LLEN rq:queue:fetch)
OCR_QUEUE=$(redis-cli LLEN rq:queue:ocr)
FAILED_QUEUE=$(redis-cli LLEN rq:queue:failed)

if [ $FETCH_QUEUE -gt 100 ]; then
  echo "⚠️  High fetch queue depth: $FETCH_QUEUE"
fi

if [ $OCR_QUEUE -gt 500 ]; then
  echo "⚠️  High OCR queue depth: $OCR_QUEUE"
fi

if [ $FAILED_QUEUE -gt 10 ]; then
  echo "⚠️  Failed jobs detected: $FAILED_QUEUE"
fi
```

## Monitoring in Production

### With systemd

```bash
# Log jobs to journald
journalctl -u clerk-worker-* -f

# Check worker status
systemctl --user status clerk-worker-*
```

### With Log Files

If running workers with output redirection (optional):

```bash
# Start workers with output redirection
clerk worker fetch > logs/worker-fetch.log 2>&1 &

# Monitor worker output
tail -f logs/worker-fetch.log

# Count errors in logs
grep -c "ERROR" logs/worker-fetch.log
```

### With Cron

```bash
# Check health every 5 minutes
*/5 * * * * cd /path/to/clerk && (redis-cli LLEN rq:queue:failed > /tmp/clerk-failed-jobs.txt) 2>&1

# Alert if too many failed jobs
*/5 * * * * [ $(cat /tmp/clerk-failed-jobs.txt) -gt 20 ] && /usr/local/bin/send-alert.sh "Clerk: too many failed jobs"
```

## Troubleshooting

### High Queue Depths

If queue depths are growing:

1. **Check worker processes**: `ps aux | grep "clerk worker"`
2. **Check worker logs**: Look for errors or crashes
3. **Check Redis**: `redis-cli ping` should return PONG
4. **Add workers**: Start more worker processes

### Failed Jobs

If you see failed jobs:

```bash
# View failed job IDs
redis-cli LRANGE rq:queue:failed 0 -1

# Get details of a failed job
redis-cli GET rq:job:JOB_ID

# Check worker output (if running in foreground or tailed to file)
# Worker output is JSON-formatted to stdout/stderr
```

### Stuck Sites

If sites are in progress for too long:

SQLite:
```bash
sqlite3 civic.db "SELECT subdomain, status, last_updated FROM sites WHERE status != 'deployed' AND last_updated < datetime('now', '-2 hours');"
```

PostgreSQL:
```bash
psql $DATABASE_URL -c "SELECT subdomain, status, last_updated FROM sites WHERE status != 'deployed' AND last_updated < NOW() - INTERVAL '2 hours';"
```

Check logs for the affected sites and manually retry if needed.

### No Idle Workers

If all workers are busy:

1. Check if jobs are slow: `top` or `ps aux | grep "clerk worker"`
2. Add more workers: Start additional `clerk worker` processes
3. Optimize slow jobs: Profile and optimize the bottleneck operation

## See Also

- [Task Queue Guide](task-queue.md) - Understanding the queue system
- [Troubleshooting](../setup/troubleshooting.md) - Debugging issues
