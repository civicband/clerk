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
