# Clerk to Loki Logging Fix - Design

**Date:** 2026-01-16
**Status:** Approved
**Goal:** Enable clerk workers to send structured logs directly to Loki/Grafana

## Problem

Clerk workers running on magmell (macOS LaunchAgents) are not sending logs to Loki, so the new comprehensive pipeline logging (run_id tracing, stage milestones) isn't visible in Grafana.

**Root cause:** The LaunchAgent plist template doesn't include `LOKI_URL` environment variable, so workers never create the `LokiQueueHandler` that pushes logs directly to Loki.

## Current State

**Clerk logging architecture (clerk/cli.py:configure_logging):**
- Always logs to console via `StreamHandler` (captured to `~/.clerk/logs/*.log` by LaunchAgents)
- If `LOKI_URL` env var is set → also logs to Loki via `logging_loki.LokiQueueHandler`
- Uses `JsonFormatter` for structured logging with fields: subdomain, run_id, stage, job_id, parent_job_id

**LaunchAgent deployment (scripts/install-workers.sh):**
- Reads worker config from `.env` (FETCH_WORKERS, OCR_WORKERS, etc.)
- Generates plists from template (scripts/launchd-worker-template.plist)
- Sets environment: REDIS_URL, DATABASE_URL, STORAGE_DIR, DEFAULT_OCR_BACKEND, PATH
- **Missing:** LOKI_URL

**Worker logs location:**
- `~/.clerk/logs/clerk-worker-fetch-1.log`
- `~/.clerk/logs/clerk-worker-ocr-1.log`
- etc.

## Solution: Direct to Loki (Recommended Approach)

Add `LOKI_URL` to LaunchAgent environment so workers can push logs directly to Loki.

**Why this approach:**
- Simpler - fewer moving parts
- Already implemented in code (logging_loki.LokiQueueHandler)
- No Promtail config changes needed
- Consistent with clerk's design

**Alternative rejected:** Configure Promtail to scrape `~/.clerk/logs/*.log` files
- More complex (Promtail config + docker volume mounts)
- Adds unnecessary indirection
- Promtail best for system logs, not app logs with direct push capability

## Implementation

### 1. Update .env.example

Add after existing variables:

```bash
# Loki URL for direct log shipping (optional)
# When set, workers send logs directly to Loki via LokiQueueHandler
# Format: http://<loki-host>:3100 (no trailing path)
# Example with Tailscale: http://100.x.x.x:3100
# LOKI_URL=
```

### 2. Update scripts/install-workers.sh

Add around line 64 with other defaults:

```bash
LOKI_URL="${LOKI_URL:-}"  # Optional - empty string if not set
```

Update summary output around line 115:

```bash
echo "  LOKI_URL: ${LOKI_URL:-not set}"
```

### 3. Update scripts/launchd-worker-template.plist

Add to EnvironmentVariables dict (around line 26):

```xml
        <key>LOKI_URL</key>
        <string>{{LOKI_URL}}</string>
```

Update sed replacement in install-workers.sh (around line 147):

```bash
        sed "s|{{LOKI_URL}}|${LOKI_URL}|g" | \
```

## Verification Steps

### On local machine (civicband/clerk):

1. **Check current worker status:**
   ```bash
   ssh phildini@magmell "launchctl list | grep com.civicband.clerk.worker"
   ```

2. **Check if workers have LOKI_URL set:**
   ```bash
   ssh phildini@magmell "launchctl print gui/\$(id -u)/com.civicband.clerk.worker.fetch.1 | grep LOKI_URL"
   ```

### In Grafana (after deployment):

3. **Query for clerk logs:**
   ```logql
   {job="clerk"}
   ```

4. **Test run_id filtering:**
   ```logql
   {job="clerk", subdomain="alameda.civic.band"} | json | run_id != ""
   ```

5. **Trace specific pipeline run:**
   ```logql
   {job="clerk", run_id="alameda_1737072000_abc123"}
   ```

### Fallback debugging:

6. **Check worker logs directly:**
   ```bash
   ssh phildini@magmell "tail -50 ~/.clerk/logs/clerk-worker-fetch-1.log | jq"
   ```

7. **Check Loki is reachable:**
   ```bash
   ssh phildini@magmell "curl -sf http://<loki-tailscale-ip>:3100/ready"
   ```

8. **Verify logging_loki is installed:**
   ```bash
   ssh phildini@magmell "cd ~/civicband/civic-band && uv pip list | grep logging-loki"
   ```

## Deployment Workflow

### In civicband/clerk repo:

1. **Test locally:**
   ```bash
   # Set LOKI_URL in local .env for testing
   echo "LOKI_URL=http://localhost:3100" >> .env

   # Run install-workers to verify template rendering
   uv run clerk install-workers

   # Check LOKI_URL appears in plist
   launchctl print gui/$(id -u)/com.civicband.clerk.worker.fetch.1 | grep LOKI_URL

   # Uninstall test workers
   uv run clerk uninstall-workers
   ```

2. **Commit and push changes**

3. **Deploy to magmell:**
   ```bash
   # From civicband/public-works repo
   cd /Users/phildini/code/civicband/public-works
   fab deploy --host=magmell --project=clerk
   ```

### On magmell:

4. **Update worker configuration:**
   ```bash
   ssh phildini@magmell
   cd ~/civicband/civic-band

   # Add LOKI_URL to .env (get Tailscale IP from Loki host)
   echo "LOKI_URL=http://<loki-tailscale-ip>:3100" >> .env

   # Reinstall workers with new environment variable
   uv run clerk uninstall-workers
   uv run clerk install-workers
   ```

5. **Verify in Grafana** (use queries from Verification section)

### Troubleshooting:

If logs don't appear:

- Check logging_loki is installed: `uv pip list | grep logging-loki`
- If missing: `uv pip install python-logging-loki`
- Check error logs: `tail -20 ~/.clerk/logs/clerk-worker-fetch-1.error.log`
- Force a test log: `uv run clerk --help`

## Success Criteria

- [ ] Workers have LOKI_URL set in LaunchAgent environment
- [ ] Grafana query `{job="clerk"}` returns logs
- [ ] Grafana query `{job="clerk", subdomain="alameda.civic.band"}` filters by subdomain
- [ ] Grafana query `{job="clerk", run_id="..."}` traces full pipeline execution
- [ ] Logs include structured fields: subdomain, run_id, stage, job_id, parent_job_id

## Files Changed

- `clerk/.env.example` - Document LOKI_URL
- `clerk/scripts/install-workers.sh` - Read and pass LOKI_URL
- `clerk/scripts/launchd-worker-template.plist` - Include LOKI_URL in environment

## Dependencies

- `python-logging-loki` package (should already be in pyproject.toml)
- Loki server reachable from magmell via Tailscale
- Network connectivity: magmell → Loki (port 3100)
