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

**SQLite Database:**

```bash
sqlite3 civic.db "SELECT COUNT(*) FROM sites;"
```

Expected: `0` (empty table)

**PostgreSQL (if configured):**

```bash
psql $DATABASE_URL -c "SELECT COUNT(*) FROM sites;"
```

### 3. Check Worker Status

```bash
# Check if workers are running
ps aux | grep "rq worker"

# Check queue status in Redis
redis-cli --raw LLEN rq:queue:fetch
redis-cli --raw LLEN rq:queue:ocr
redis-cli --raw LLEN rq:queue:compilation
redis-cli --raw LLEN rq:queue:deploy
```

Expected:
- Worker processes listed
- Queue lengths return 0 or numbers (indicates Redis is responsive)

## End-to-End Test

### 1. Create Test Site

```bash
clerk etl new test-verification.civic.band
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

Using SQLite:

```bash
sqlite3 civic.db "SELECT subdomain, name FROM sites WHERE subdomain='test-verification.civic.band';"
```

Expected: One row showing your test site

(If using PostgreSQL, use `psql` instead of `sqlite3`)

### 3. Trigger Update

```bash
clerk etl update -s test-verification.civic.band
```

Expected: Job enqueued message

### 4. Monitor Queue

Monitor the queue status:

```bash
# Watch the queue depths (update every second)
watch -n 1 "redis-cli --raw LLEN rq:queue:fetch; redis-cli --raw LLEN rq:queue:ocr; redis-cli --raw LLEN rq:queue:compilation; redis-cli --raw LLEN rq:queue:deploy"
```

Watch for:
1. Job appears in fetch queue (LLEN > 0)
2. Queue lengths decrease as jobs process
3. All queues return to 0 when complete

If workers are running in foreground terminals, watch their stdout output for any errors.

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
redis-cli --raw LLEN rq:queue:fetch
redis-cli --raw LLEN rq:queue:ocr
redis-cli --raw LLEN rq:queue:compilation
redis-cli --raw LLEN rq:queue:deploy

# Check for failed jobs
redis-cli LLEN rq:queue:failed
```

Expected: All queues at 0 or decreasing, no failed jobs

## Performance Tests

### Test OCR Performance

Monitor OCR queue processing time:

```bash
# Time from when you enqueue to when queue returns to 0
time (
  clerk etl update -s test-verification.civic.band
  until [ $(redis-cli LLEN rq:queue:ocr) -eq 0 ]; do sleep 1; done
)
```

Typical speeds with Tesseract: 2-5 seconds per page

### Test Compilation Performance

Monitor compilation time:

```bash
# After OCR completes, time the compilation
redis-cli LLEN rq:queue:compilation
# Wait for compilation queue to process
```

Typical speeds:
- Without extraction: 10-30 seconds for 100 pages
- With extraction: 5-10 minutes for 100 pages

## Verification Checklist

- [ ] `clerk --version` shows version number
- [ ] `redis-cli ping` returns PONG
- [ ] `psql $DATABASE_URL` connects successfully
- [ ] Worker processes are running (`ps aux | grep "rq worker"`)
- [ ] Redis queues are accessible
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
