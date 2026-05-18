# Troubleshooting Worker Launch Failures

## Common Causes

When you see "Failed to load" errors for worker LaunchAgents, it's usually due to one of these issues:

### 1. Redis Not Running (Most Common)

The worker command validates the Redis connection immediately on startup. If Redis isn't running, the worker will fail with an exit code and launchctl will report "Failed to load".

**How to check:**
```bash
redis-cli ping
# Should return: PONG
```

**How to fix:**
```bash
# Start Redis
brew services start redis

# Or if using different Redis setup
redis-server &
```

### 2. Invalid Environment Variables

The workers need these environment variables from `.env`:
- `REDIS_URL` - Connection string for Redis
- `DATABASE_URL` - Database connection
- `STORAGE_DIR` - Where to store files
- `DEFAULT_OCR_BACKEND` - OCR backend to use

**How to check:**
```bash
cd /path/to/clerk
source .env
echo $REDIS_URL
```

**How to fix:**
- Ensure `.env` exists in the working directory
- Verify all required variables are set
- Check that paths are absolute, not relative

### 3. Clerk Executable Not Found

The plist tries to execute the clerk command, but if the path is wrong or the executable doesn't exist, it will fail.

**How to check:**
```bash
which clerk
# Or if using venv:
.venv/bin/clerk --version
```

**How to fix:**
- Reinstall clerk in the virtual environment
- Update the plist with the correct path to clerk
- Ensure the executable has execute permissions

### 4. Working Directory Issues

The worker runs from a specific working directory that must contain the `.env` file.

**How to check:**
```bash
# Verify you're in the correct directory
pwd
# Check if .env exists
ls -la .env
```

**How to fix:**
- Run clerk from the directory containing your `.env` file
- Ensure `.env` file is readable: `cat .env`

## Diagnostic Steps

To identify worker issues:

1. **Check if workers are running:**
   ```bash
   ps aux | grep "clerk worker"
   ```

2. **Try running a worker manually to see the error:**
   ```bash
   cd /path/to/clerk
   clerk worker fetch
   ```

3. **Check Redis connection:**
   ```bash
   redis-cli ping
   # Should return: PONG
   ```

4. **Check database connection:**
   
   For SQLite (default):
   ```bash
   sqlite3 civic.db "SELECT 1;"
   ```
   
   For PostgreSQL:
   ```bash
   psql $DATABASE_URL -c "SELECT 1;"
   ```

## Checking Worker Output

Workers output JSON-formatted logs to stdout/stderr:

```bash
# If running workers in a terminal, view logs there
# For background processes, redirect to a file when starting:
clerk worker fetch > /tmp/clerk-worker-fetch.log 2>&1 &

# Then tail the log:
tail -f /tmp/clerk-worker-fetch.log
```

## Manual Worker Testing

Test a worker manually to see any errors:

```bash
cd /path/to/clerk
source .env

# Try running a worker in burst mode (exits when queues empty)
clerk worker fetch --burst
```

This will show you any error messages that prevent the worker from starting or processing jobs.

## Common Error Messages

### "Cannot connect to Redis"
- **Cause:** Redis is not running or REDIS_URL is incorrect
- **Fix:** Start Redis with `brew services start redis`

### "clerk: command not found"
- **Cause:** Clerk executable path is wrong in plist
- **Fix:** Update CLERK_PATH in plist to absolute path

### "FileNotFoundError: .env"
- **Cause:** Working directory doesn't contain .env
- **Fix:** Ensure WorkingDirectory in plist points to directory with .env

### "Permission denied"
- **Cause:** Clerk executable doesn't have execute permissions
- **Fix:** `chmod +x /path/to/clerk`

## Fixing and Restarting

After fixing the issue:

```bash
# Stop the worker
pkill -f "clerk worker fetch"

# Fix the issue (start Redis, fix .env, etc.)

# Restart the worker
clerk worker fetch &
```

## Verifying Success

After starting workers, verify they are running:

```bash
# Check worker status
ps aux | grep "clerk worker"

# Should show running worker processes
# Example good output:
# user  12345  0.5  2.3  ... clerk worker fetch
# user  12346  0.5  2.3  ... clerk worker ocr

# Check that jobs are being processed
redis-cli LLEN rq:queue:fetch
# Should return 0 or decreasing number
```
