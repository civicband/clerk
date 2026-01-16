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
