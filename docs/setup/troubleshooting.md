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

### Database connection failed (SQLite or PostgreSQL)

**If using SQLite (default):**

**Symptom:** `Error: unable to open database file`

**Fix:**

```bash
# Ensure the database file is writable
touch civic.db
chmod 644 civic.db

# Verify it's being used
grep DATABASE_URL .env
# Should show: DATABASE_URL=sqlite:///civic.db
```

**If using PostgreSQL (production):**

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

**Symptom:** No worker processes running (`ps aux | grep "clerk worker"` shows nothing)

**Diagnosis:**

```bash
# Check if worker process is running
ps aux | grep "clerk worker"

# Try starting a worker and see error
clerk worker fetch

# Check Redis connectivity
redis-cli ping
```

**Fix (Redis not running):**

```bash
# macOS
brew services start redis
redis-cli ping

# Linux
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

**Fix (missing .env file):**

```bash
# Ensure .env exists in working directory
ls -la .env

# If missing, create it with required variables
cat > .env <<EOF
DATABASE_URL=sqlite:///civic.db
REDIS_URL=redis://localhost:6379
STORAGE_DIR=../sites
EOF
```

**Fix (wrong PATH):**

Ensure clerk is in your PATH:

```bash
which clerk
# If not found, use full path:
/usr/local/bin/clerk worker fetch
```

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
# Check queue depths
redis-cli LLEN rq:queue:fetch
redis-cli LLEN rq:queue:ocr
redis-cli LLEN rq:queue:failed

# Check for failed jobs
redis-cli LRANGE rq:queue:failed 0 -1
```

**Fix (workers not running):**

See "Workers not starting" above.

**Fix (failed jobs):**

View details of failed jobs:

```bash
redis-cli LRANGE rq:queue:failed 0 -1
```

This will show job IDs. Look at worker logs for error messages.

Clear failed queue (only if you understand why they failed):

```bash
redis-cli DEL rq:queue:failed
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

Disable extraction:

```bash
# Edit .env
ENABLE_EXTRACTION=0

# Stop extraction workers
pkill -f "clerk worker extraction"
```

## Performance Issues

### OCR extremely slow

**Diagnosis:**

```bash
time clerk etl ocr
```

If > 10 seconds per page, investigate:

**Fix (too few OCR workers):**

Stop existing workers and restart with more:

```bash
# Stop OCR workers
pkill -f "clerk worker ocr"

# Start with more workers
clerk worker ocr -n 8 &
```

### High memory usage

**Symptom:** System runs out of memory

**Diagnosis:**

```bash
# Check memory usage by worker
ps aux | grep "clerk worker" | awk '{print $4, $11}'
```

**Fix (disable extraction):**

Disable extraction entirely:

```bash
# Edit .env
ENABLE_EXTRACTION=0

# Stop extraction workers
pkill -f "clerk worker extraction"
```

Use distributed setup to run extraction on separate machine:

See [Distributed Setup](distributed.md).

## Diagnostic Tools

### Check Worker Status

```bash
# List all running worker processes
ps aux | grep "clerk worker"

# Check if workers are listening to queues
redis-cli KEYS "rq:worker:*"
```

### Queue and Job Inspection

```bash
# List all queues
redis-cli KEYS "rq:queue:*"

# Check queue length
redis-cli LLEN rq:queue:fetch
redis-cli LLEN rq:queue:ocr
redis-cli LLEN rq:queue:compilation

# View jobs in queue (show first 10)
redis-cli LRANGE rq:queue:fetch 0 10

# Check for failed jobs
redis-cli LLEN rq:queue:failed
redis-cli LRANGE rq:queue:failed 0 -1
```

## Getting More Help

If troubleshooting doesn't resolve your issue:

1. Check [GitHub Issues](https://github.com/civicband/clerk/issues)
2. Search existing issues for similar problems
3. Open a new issue with:
   - Platform (macOS/Linux)
   - Clerk version (`clerk --version`)
   - Full error messages
   - Output from `ps aux | grep "clerk worker"`
   - Queue status from Redis
   - Relevant log files

## Next Steps

Once issues are resolved:
- [Verification Guide](verification.md) - Verify setup works
- [Your First Site](../guides/first-site.md) - Complete tutorial
