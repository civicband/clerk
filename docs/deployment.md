# Deployment Guide

Guide for deploying clerk in production with automated updates.

## Overview

Clerk provides built-in support for automated updates using macOS's launchd system. The `clerk install-launchd` command sets up scheduled jobs that:

- Run `clerk update -n` every 60 seconds
- Monitor for failures and send alerts
- Prevent overlapping runs with lock files
- Log all activity for debugging

## Prerequisites

### System Requirements

- macOS 10.15 (Catalina) or later
- Full Disk Access granted to:
  - `/usr/sbin/cron` (if using cron)
  - `/opt/homebrew/bin/gtimeout`
  - `/Users/youruser/.cargo/bin/uv`

### Required Tools

**gtimeout** (from GNU coreutils):
```bash
brew install coreutils
```

**uv** (Python package manager):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**clerk** (installed in your working directory):
```bash
cd /path/to/your/civic-band
uv sync
```

## Installation

### Basic Installation

From your civic-band working directory:

```bash
clerk install-launchd
```

This will:
1. Create `update-wrapper.sh` and `healthcheck.sh` in the current directory
2. Create `logs/` directory for output
3. Install launchd plists to `~/Library/LaunchAgents/`
4. Load the jobs automatically

### Installation with Webhook Alerts

To receive alerts via webhook (Slack, Discord, etc.):

```bash
clerk install-launchd --webhook-url https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

### Custom Working Directory

To install for a specific directory:

```bash
clerk install-launchd --work-dir /path/to/civic-band --webhook-url https://...
```

## Configuration

### Full Disk Access

On macOS Catalina and later, grant Full Disk Access to required binaries:

1. Open **System Preferences → Security & Privacy → Privacy**
2. Select **Full Disk Access** in the left sidebar
3. Click the lock icon and authenticate
4. Click **+** and add:
   - `/opt/homebrew/bin/gtimeout`
   - `/Users/youruser/.cargo/bin/uv`

### Webhook Alerts

The health check script sends alerts via webhook when:
- Updates haven't run in >15 minutes
- Lock file is stuck for >2 hours
- >10 errors in the last 100 log lines

Webhook format is compatible with:
- Slack incoming webhooks
- Discord webhooks
- Mattermost
- Any service accepting JSON payloads

## Monitoring

### View Logs

**Update logs:**
```bash
tail -f logs/update.log
tail -f logs/update.error.log
```

**Health check logs:**
```bash
tail -f logs/healthcheck.log
tail -f logs/healthcheck.error.log
```

### Check Job Status

```bash
# List all civicband jobs
launchctl list | grep civicband

# Should show:
# - com.civicband.update
# - com.civicband.healthcheck
```

### Manual Execution

To test the update job immediately:

```bash
launchctl start com.civicband.update
```

## Management

### Stop Jobs

```bash
launchctl unload ~/Library/LaunchAgents/com.civicband.update.plist
launchctl unload ~/Library/LaunchAgents/com.civicband.healthcheck.plist
```

### Start Jobs

```bash
launchctl load ~/Library/LaunchAgents/com.civicband.update.plist
launchctl load ~/Library/LaunchAgents/com.civicband.healthcheck.plist
```

### Reload After Changes

```bash
launchctl unload ~/Library/LaunchAgents/com.civicband.update.plist
launchctl load ~/Library/LaunchAgents/com.civicband.update.plist
```

### Uninstall

```bash
# Stop and remove jobs
launchctl unload ~/Library/LaunchAgents/com.civicband.update.plist
launchctl unload ~/Library/LaunchAgents/com.civicband.healthcheck.plist
rm ~/Library/LaunchAgents/com.civicband.*.plist

# Remove scripts (from your working directory)
rm update-wrapper.sh healthcheck.sh
```

## Troubleshooting

### Jobs Not Running

**Check if jobs are loaded:**
```bash
launchctl list | grep civicband
```

**Check logs for errors:**
```bash
cat logs/update.error.log
```

**Verify Full Disk Access is granted:**
- System Preferences → Security & Privacy → Privacy → Full Disk Access
- Ensure gtimeout and uv are listed and checked

### Lock File Stuck

If updates stop running and you see "Lock file stuck" messages:

```bash
# Check if process is actually running
ps aux | grep "clerk update"

# If no process, remove stuck lock
rm /tmp/civicband-update-$(whoami).lock

# Restart job
launchctl stop com.civicband.update
launchctl start com.civicband.update
```

### High CPU Usage

If multiple processes pile up:

```bash
# Kill all hung clerk processes
pkill -f "clerk update -n"

# Check for issues in logs
tail -100 logs/update.error.log
```

## Schedule Configuration

The default schedule is:
- **Update job:** Every 60 seconds
- **Health check:** Every 15 minutes (900 seconds)

To customize, edit the plist files:

```bash
nano ~/Library/LaunchAgents/com.civicband.update.plist
```

Change the `StartInterval` value (in seconds):

```xml
<key>StartInterval</key>
<integer>60</integer>  <!-- Change this value -->
```

Then reload:

```bash
launchctl unload ~/Library/LaunchAgents/com.civicband.update.plist
launchctl load ~/Library/LaunchAgents/com.civicband.update.plist
```

## Files Created

When you run `clerk install-launchd`, these files are created:

**In your working directory:**
- `update-wrapper.sh` - Main update script with lock file handling
- `healthcheck.sh` - Health monitoring script
- `logs/` - Directory for all log files

**In ~/Library/LaunchAgents/:**
- `com.civicband.update.plist` - Update job definition
- `com.civicband.healthcheck.plist` - Health check job definition

**In /tmp/:**
- `civicband-update-<username>.lock` - Lock file (created/removed automatically)

## Best Practices

1. **Monitor logs regularly** - Check for errors and performance issues
2. **Set up webhook alerts** - Get notified immediately of failures
3. **Test changes locally** - Before deploying to production
4. **Keep dependencies updated** - Regularly update uv, clerk, and system tools
5. **Document your setup** - Note any custom configurations
6. **Have a rollback plan** - Know how to quickly stop and restart services

## Migration from cron

If you're migrating from cron:

1. **Disable old cron job:**
   ```bash
   crontab -e
   # Comment out or remove the clerk update line
   ```

2. **Kill any hung cron processes:**
   ```bash
   pkill -f "clerk update"
   ```

3. **Install launchd:**
   ```bash
   cd /path/to/civic-band
   clerk install-launchd --webhook-url https://your-webhook-url
   ```

4. **Monitor for 15-30 minutes:**
   ```bash
   tail -f logs/update.log
   ```

5. **Verify database updates:**
   - Check that sites are being updated
   - Verify no errors in logs

## Auto-Scheduler Setup

To automatically update all sites once per day, set up a cron job:

```bash
# Edit crontab
crontab -e

# Add this line to run every minute:
* * * * * cd /path/to/clerk && /path/to/uv run clerk update --next-site >> /var/log/clerk/auto-enqueue.log 2>&1
```

**Monitoring:**

```bash
# View auto-enqueue log
tail -f /var/log/clerk/auto-enqueue.log

# Check queue status
clerk status
```

The auto-scheduler:
- Enqueues 1 site per minute (1440 sites/day capacity)
- Uses normal priority (manual updates jump ahead)
- Skips recently-updated sites automatically
- Self-heals if cron misses runs

## Related Documentation

- [Development Setup](DEVELOPMENT.md) - Setting up clerk for development
- [Architecture](architecture.md) - Understanding clerk's design
- [Testing](testing.md) - Running tests
