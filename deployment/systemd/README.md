# Systemd Timer for Pipeline Reconciliation

This directory contains systemd service and timer units for automatically reconciling stuck pipelines.

## What It Does

The reconciliation timer runs every 15 minutes and:
1. Finds sites with stale `updated_at` timestamps (>2 hours old)
2. Counts completed documents on filesystem (source of truth)
3. Updates database counters to match reality
4. Enqueues missing coordinators to continue pipeline

This solves issues where:
- OCR jobs timeout and don't update counters
- Workers crash mid-job
- Coordinators fail to trigger due to counter mismatches

## Installation (Linux with systemd)

1. **Edit paths in the service file** to match your deployment:
   ```bash
   # Edit clerk-reconcile.service
   # Update these lines:
   WorkingDirectory=/home/deploy/civic-band
   Environment="STORAGE_DIR=/Volumes/CivicBandData/sites"
   ExecStart=/home/deploy/civic-band/.venv/bin/clerk reconcile-pipeline --threshold-hours 2
   ```

2. **Copy files to systemd directory**:
   ```bash
   sudo cp clerk-reconcile.service /etc/systemd/system/
   sudo cp clerk-reconcile.timer /etc/systemd/system/
   ```

3. **Reload systemd**:
   ```bash
   sudo systemctl daemon-reload
   ```

4. **Enable and start the timer**:
   ```bash
   # Enable timer to start on boot
   sudo systemctl enable clerk-reconcile.timer

   # Start timer immediately
   sudo systemctl start clerk-reconcile.timer
   ```

5. **Verify timer is active**:
   ```bash
   # Check timer status
   sudo systemctl status clerk-reconcile.timer

   # List all timers
   sudo systemctl list-timers --all | grep clerk
   ```

## Manual Testing

Before enabling the timer, test the service manually:

```bash
# Run once manually
sudo systemctl start clerk-reconcile.service

# Check logs
sudo journalctl -u clerk-reconcile.service -f
```

## Monitoring

Check reconciliation logs:

```bash
# Recent logs
sudo journalctl -u clerk-reconcile.service -n 50

# Follow logs in real-time
sudo journalctl -u clerk-reconcile.service -f

# Logs for last 24 hours
sudo journalctl -u clerk-reconcile.service --since "24 hours ago"
```

Check timer next run time:

```bash
sudo systemctl list-timers clerk-reconcile.timer
```

## Adjusting Schedule

To change the frequency, edit the timer file:

```ini
# Every 5 minutes
OnCalendar=*:0/5

# Every 30 minutes
OnCalendar=*:0/30

# Every hour at :15 past
OnCalendar=*:15

# Every day at 3:00 AM
OnCalendar=03:00
```

Then reload:

```bash
sudo systemctl daemon-reload
sudo systemctl restart clerk-reconcile.timer
```

## Troubleshooting

**Timer not triggering:**
```bash
# Check if timer is enabled
sudo systemctl is-enabled clerk-reconcile.timer

# Check timer status
sudo systemctl status clerk-reconcile.timer
```

**Service failing:**
```bash
# Check service logs for errors
sudo journalctl -u clerk-reconcile.service -n 100

# Run service manually to see errors
sudo systemctl start clerk-reconcile.service
sudo systemctl status clerk-reconcile.service
```

**Wrong STORAGE_DIR:**
```bash
# Edit service file
sudo vim /etc/systemd/system/clerk-reconcile.service

# Update Environment line
Environment="STORAGE_DIR=/your/actual/path"

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart clerk-reconcile.timer
```

## Alternative: Cron Setup

If you prefer cron instead of systemd:

```bash
# Edit crontab for deploy user
crontab -e

# Add this line (runs every 15 minutes):
*/15 * * * * cd /home/deploy/civic-band && /home/deploy/civic-band/.venv/bin/clerk reconcile-pipeline --threshold-hours 2 >> /home/deploy/logs/reconcile.log 2>&1
```

Make sure STORAGE_DIR is set in your .env file when using cron.
