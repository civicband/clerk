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
Look at the plist file:
```bash
cat ~/Library/LaunchAgents/com.civicband.clerk.worker.fetch.1.plist
# Check the <key>WorkingDirectory</key> value
```

**How to fix:**
- Ensure the working directory exists
- Ensure `.env` file is in that directory
- Re-run the install script from the correct directory

## Diagnostic Command

Run the diagnostic command to identify the issue:

```bash
clerk diagnose-workers
```

This will check:
1. `.env` file existence
2. Clerk executable
3. Redis connection
4. Log directory and recent errors
5. Plist file validity
6. Manual worker execution

## Checking Worker Logs

Worker logs are stored in `~/.clerk/logs/`:

```bash
# View error logs
tail -f ~/.clerk/logs/clerk-worker-fetch-1.error.log

# View stdout logs
tail -f ~/.clerk/logs/clerk-worker-fetch-1.log
```

## Manual Worker Testing

Test a worker manually to see the actual error:

```bash
cd /path/to/clerk
source .env

# Try running a worker
clerk worker fetch --burst
```

This will show you the actual error message that's preventing the worker from starting.

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

## Fixing and Reloading

After fixing the issue:

```bash
# Uninstall workers
clerk uninstall-workers

# Fix the issue (start Redis, fix .env, etc.)

# Reinstall workers (run from directory with .env)
clerk install-workers
```

## Verifying Success

After installation, verify workers are running:

```bash
# Check worker status
launchctl list | grep com.civicband.clerk.worker

# Should show workers with PIDs (not just "-")
# Example good output:
# 12345  0  com.civicband.clerk.worker.fetch.1
# 12346  0  com.civicband.clerk.worker.fetch.2

# Check for errors in logs
ls -lh ~/.clerk/logs/*.error.log
# Error log files should be 0 bytes if no errors
```
