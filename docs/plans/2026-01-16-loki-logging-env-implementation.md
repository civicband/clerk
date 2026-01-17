# Loki Logging Environment Variable - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add LOKI_URL environment variable to LaunchAgent workers so they can push logs directly to Loki

**Architecture:** Modify worker deployment scripts to read LOKI_URL from .env and pass it to LaunchAgent plists as an environment variable. When set, workers will use logging_loki.LokiQueueHandler (already implemented in clerk/cli.py:configure_logging).

**Tech Stack:** Bash scripts, LaunchAgent plist XML

---

## Context

The clerk logger (clerk/cli.py:configure_logging) already supports direct Loki logging via LokiQueueHandler when LOKI_URL is set. However, the LaunchAgent deployment scripts don't pass this environment variable to workers, so they never create the Loki handler.

This fix adds LOKI_URL to three files:
1. `.env.example` - Document the variable
2. `scripts/install-workers.sh` - Read from .env and pass to plist template
3. `scripts/launchd-worker-template.plist` - Include in EnvironmentVariables dict

No code changes needed - just configuration.

---

### Task 1: Document LOKI_URL in .env.example

**Files:**
- Modify: `.env.example`

**Step 1: Add LOKI_URL documentation**

Add after line 57 (after LOKI_URL comment):

```bash
# Loki URL for direct log shipping (optional)
# When set, workers send logs directly to Loki via LokiQueueHandler
# Format: http://<loki-host>:3100 (no trailing path)
# Example with Tailscale: http://100.x.x.x:3100
# LOKI_URL=
```

**Step 2: Verify the change**

Run: `git diff .env.example`
Expected: See the new LOKI_URL documentation block

**Step 3: Commit**

```bash
git add .env.example
git commit -m "docs: add LOKI_URL to .env.example for direct Loki logging"
```

---

### Task 2: Update install-workers.sh to read and pass LOKI_URL

**Files:**
- Modify: `scripts/install-workers.sh:64` (add default)
- Modify: `scripts/install-workers.sh:115` (add to summary)
- Modify: `scripts/install-workers.sh:147` (add to sed replacements)

**Step 1: Add LOKI_URL default value**

Add after line 64 (after DEFAULT_OCR_BACKEND default):

```bash
LOKI_URL="${LOKI_URL:-}"  # Optional - empty string if not set
```

**Step 2: Add LOKI_URL to configuration summary output**

Add after line 115 (after OCR backend line):

```bash
echo "  LOKI_URL: ${LOKI_URL:-not set}"
```

**Step 3: Add LOKI_URL to sed replacements**

Add after line 147 (after PATH sed replacement):

```bash
        sed "s|{{LOKI_URL}}|${LOKI_URL}|g" | \
```

**Step 4: Verify the changes**

Run: `git diff scripts/install-workers.sh`
Expected: Three additions - default value, summary output, sed replacement

**Step 5: Test the script renders correctly**

Create a test .env:
```bash
echo "FETCH_WORKERS=1" > /tmp/test.env
echo "OCR_WORKERS=1" >> /tmp/test.env
echo "COMPILATION_WORKERS=1" >> /tmp/test.env
echo "EXTRACTION_WORKERS=0" >> /tmp/test.env
echo "DEPLOY_WORKERS=1" >> /tmp/test.env
echo "LOKI_URL=http://test.example.com:3100" >> /tmp/test.env
```

Run the script logic to verify it reads LOKI_URL:
```bash
source /tmp/test.env && echo "LOKI_URL=${LOKI_URL:-not set}"
```
Expected: `LOKI_URL=http://test.example.com:3100`

**Step 6: Commit**

```bash
git add scripts/install-workers.sh
git commit -m "feat: add LOKI_URL support to install-workers.sh"
```

---

### Task 3: Add LOKI_URL to LaunchAgent plist template

**Files:**
- Modify: `scripts/launchd-worker-template.plist:26` (add EnvironmentVariable)

**Step 1: Add LOKI_URL to EnvironmentVariables dict**

Add after line 26 (after PATH key-value pair, before closing dict tag):

```xml
        <key>LOKI_URL</key>
        <string>{{LOKI_URL}}</string>
```

**Step 2: Verify the change**

Run: `git diff scripts/launchd-worker-template.plist`
Expected: See LOKI_URL key-value pair in EnvironmentVariables

**Step 3: Verify XML is valid**

Run: `xmllint --noout scripts/launchd-worker-template.plist`
Expected: No output (valid XML)

**Step 4: Commit**

```bash
git add scripts/launchd-worker-template.plist
git commit -m "feat: add LOKI_URL to LaunchAgent environment variables"
```

---

### Task 4: Verify complete integration

**Files:**
- Read: `.env.example`
- Read: `scripts/install-workers.sh`
- Read: `scripts/launchd-worker-template.plist`

**Step 1: Create a test .env with LOKI_URL**

```bash
cat > /tmp/test-clerk.env << 'EOF'
FETCH_WORKERS=1
OCR_WORKERS=1
COMPILATION_WORKERS=1
EXTRACTION_WORKERS=0
DEPLOY_WORKERS=1
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=sqlite:///test.db
STORAGE_DIR=/tmp/test-sites
DEFAULT_OCR_BACKEND=tesseract
LOKI_URL=http://100.64.0.1:3100
EOF
```

**Step 2: Verify install-workers.sh can read all variables**

```bash
source /tmp/test-clerk.env
echo "LOKI_URL: ${LOKI_URL}"
echo "All other vars present: FETCH_WORKERS=${FETCH_WORKERS} OCR_WORKERS=${OCR_WORKERS}"
```

Expected: All variables print correctly, LOKI_URL shows `http://100.64.0.1:3100`

**Step 3: Verify template has placeholder**

```bash
grep "{{LOKI_URL}}" scripts/launchd-worker-template.plist
```

Expected: Find the placeholder in template

**Step 4: Verify install-workers.sh will substitute it**

```bash
grep "LOKI_URL" scripts/install-workers.sh
```

Expected: Find three occurrences - default value, summary output, sed replacement

**Step 5: Check .env.example documents it**

```bash
grep -A 4 "LOKI_URL" .env.example
```

Expected: See documentation comment and example

**Step 6: No commit needed - verification only**

This task verifies all pieces work together.

---

## Manual Testing After Deployment

After deploying to magmell, verify with these steps:

**1. Check worker has LOKI_URL:**
```bash
ssh phildini@magmell "launchctl print gui/\$(id -u)/com.civicband.clerk.worker.fetch.1 | grep LOKI_URL"
```

**2. Query Grafana for clerk logs:**
```logql
{job="clerk"}
```

**3. Test run_id filtering:**
```logql
{job="clerk", subdomain="alameda.civic.band"} | json | run_id != ""
```

---

## Success Criteria

- [ ] `.env.example` documents LOKI_URL with examples
- [ ] `install-workers.sh` reads LOKI_URL from .env with default empty string
- [ ] `install-workers.sh` includes LOKI_URL in summary output
- [ ] `install-workers.sh` passes LOKI_URL to template via sed
- [ ] `launchd-worker-template.plist` includes LOKI_URL in EnvironmentVariables
- [ ] Template XML is valid (xmllint passes)
- [ ] All three changes committed separately
- [ ] Integration test verifies all pieces connect

---

## Notes

**No test suite changes needed** - This is pure configuration. The logger code in `clerk/cli.py:configure_logging` already handles LOKI_URL correctly.

**Backward compatible** - If LOKI_URL is not set (empty string), workers behave exactly as before (console logging only).

**Already have dependency** - `python-logging-loki` is already in `pyproject.toml`, so no package changes needed.
