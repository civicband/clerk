# macOS Launchd Timer for Pipeline Reconciliation

This directory contains a launchd plist template for automatically reconciling stuck pipelines on macOS.

## What It Does

The reconciliation timer runs every 15 minutes and:
1. Finds sites with stale `updated_at` timestamps (>2 hours old)
2. Counts completed documents on filesystem (source of truth)
3. Updates database counters to match reality
4. Enqueues missing coordinators to continue pipeline

## Installation (macOS)

1. **Set variables** for your environment:
   ```bash
   export VENV_PATH="/Users/phildini/civicband/civic-band/.venv"
   export WORKING_DIR="/Users/phildini/civicband/civic-band"
   export STORAGE_DIR="/Volumes/CivicBandData/sites"
   export LOG_DIR="/Users/phildini/civicband/civic-band/logs"
   ```

2. **Generate plist from template**:
   ```bash
   sed -e "s|{{VENV_PATH}}|$VENV_PATH|g" \
       -e "s|{{WORKING_DIR}}|$WORKING_DIR|g" \
       -e "s|{{STORAGE_DIR}}|$STORAGE_DIR|g" \
       -e "s|{{LOG_DIR}}|$LOG_DIR|g" \
       com.civicband.reconcile.plist.template \
       > ~/Library/LaunchAgents/com.civicband.reconcile.plist
   ```

3. **Load the launchd job**:
   ```bash
   launchctl load ~/Library/LaunchAgents/com.civicband.reconcile.plist
   ```

4. **Verify it's running**:
   ```bash
   launchctl list | grep civicband
   ```

## Manual Testing

Before loading permanently, test manually:

```bash
# Run once manually
/Users/phildini/civicband/civic-band/.venv/bin/clerk reconcile-pipeline --threshold-hours 2

# Check logs
tail -f ~/civicband/civic-band/logs/reconcile.log
tail -f ~/civicband/civic-band/logs/reconcile.error.log
```

## Monitoring

Check reconciliation logs:

```bash
# Recent logs
tail -50 ~/civicband/civic-band/logs/reconcile.log

# Follow logs in real-time
tail -f ~/civicband/civic-band/logs/reconcile.log

# Check error logs
tail -50 ~/civicband/civic-band/logs/reconcile.error.log
```

Check if job is loaded:

```bash
launchctl list | grep reconcile
```

## Adjusting Schedule

To change the frequency, edit the plist and update the `StartInterval`:

```xml
<!-- Every 5 minutes (300 seconds) -->
<key>StartInterval</key>
<integer>300</integer>

<!-- Every 30 minutes (1800 seconds) -->
<key>StartInterval</key>
<integer>1800</integer>

<!-- Every hour (3600 seconds) -->
<key>StartInterval</key>
<integer>3600</integer>
```

Then reload:

```bash
launchctl unload ~/Library/LaunchAgents/com.civicband.reconcile.plist
launchctl load ~/Library/LaunchAgents/com.civicband.reconcile.plist
```

## Troubleshooting

**Job not running:**
```bash
# Check if loaded
launchctl list | grep reconcile

# View plist contents
cat ~/Library/LaunchAgents/com.civicband.reconcile.plist

# Check for syntax errors in plist
plutil ~/Library/LaunchAgents/com.civicband.reconcile.plist
```

**Service failing:**
```bash
# Check error logs
tail -100 ~/civicband/civic-band/logs/reconcile.error.log

# Run manually to see errors
/Users/phildini/civicband/civic-band/.venv/bin/clerk reconcile-pipeline --threshold-hours 2
```

**Wrong paths:**
```bash
# Unload job
launchctl unload ~/Library/LaunchAgents/com.civicband.reconcile.plist

# Edit plist
vim ~/Library/LaunchAgents/com.civicband.reconcile.plist

# Reload
launchctl load ~/Library/LaunchAgents/com.civicband.reconcile.plist
```

## Uninstalling

To remove the reconciliation job:

```bash
# Unload
launchctl unload ~/Library/LaunchAgents/com.civicband.reconcile.plist

# Remove plist
rm ~/Library/LaunchAgents/com.civicband.reconcile.plist
```
