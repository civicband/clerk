# Sequential Extraction Job Design

## Overview

Separate entity/vote extraction from database building into an independent, sequential background job that processes sites one at a time with minimal memory footprint.

## Problem

Current `build-db-from-text` does everything inline:
- Reads text files
- Runs spaCy extraction (with SPACY_N_PROCESS=2, ~10GB memory)
- Writes to database
- Takes ~20 minutes per site

For 900 sites needing full extraction rebuild, this creates:
- Long blocking operations (20 min × 900 = 300 hours)
- Memory constraints limit parallelization
- Extraction failures require full rebuild
- Sites can't go live until extraction completes

## Solution

Split into two independent operations:

1. **Fast database build**: `build-db-from-text` creates database with text only (seconds/minutes)
2. **Async extraction**: New `extract-entities` command processes sites sequentially in background

## Architecture

### Database Schema Changes

Add two new columns to `sites` table:

**`extraction_status` (TEXT)**:
- `pending` - Needs extraction (default for existing sites)
- `in_progress` - Currently being extracted (prevents concurrent jobs)
- `completed` - Extraction finished
- `failed` - Extraction failed, can retry

**`last_extracted` (TEXT)**:
- Timestamp of last successful extraction
- NULL for never-extracted sites

### Migration

**One-time setup command**:
```bash
clerk migrate-extraction-schema
```

**Implementation** (idempotent):
```python
@cli.command()
def migrate_extraction_schema():
    """Add extraction tracking columns to sites table"""
    db = assert_db_exists()

    # Add columns if they don't exist
    existing_columns = {col.name for col in db["sites"].columns}

    if "extraction_status" not in existing_columns:
        db.execute("ALTER TABLE sites ADD COLUMN extraction_status TEXT DEFAULT 'pending'")

    if "last_extracted" not in existing_columns:
        db.execute("ALTER TABLE sites ADD COLUMN last_extracted TEXT")

    # Set pending for all sites that don't have a status
    db.execute("UPDATE sites SET extraction_status = 'pending' WHERE extraction_status IS NULL")

    click.echo("Migration complete: extraction_status and last_extracted columns added")
```

**For 900-site rebuild**:
```sql
UPDATE sites SET extraction_status = 'pending', last_extracted = NULL;
```

## Command Interface

### Two modes

**Specific site** (testing/manual):
```bash
clerk extract-entities --subdomain alameda.ca.civic.band
```

**Next site** (cron job):
```bash
clerk extract-entities --next-site
```

### Site Selection Query

```sql
SELECT subdomain FROM sites
WHERE extraction_status IN ('pending', 'failed')
ORDER BY last_extracted ASC NULLS FIRST
LIMIT 1
```

Priority:
1. Never-extracted sites (last_extracted IS NULL)
2. Oldest extractions first
3. Failed sites can retry
4. In-progress sites skipped (prevents conflicts)

### Command Flow

For `--next-site`:

1. Query for next site needing extraction
2. If none found: log "No sites need extraction", exit
3. Mark site as `extraction_status = 'in_progress'`
4. Run extraction (details below)
5. Deploy updated database (unless CIVIC_DEV_MODE)
6. Mark as `extraction_status = 'completed'`, set `last_extracted = NOW()`
7. On failure: mark as `extraction_status = 'failed'`, log error

## Extraction Process

**Core function**: `extract_entities_for_site(subdomain, force_extraction=False)`

Reuses existing `build_table_from_text` logic but operates on existing database:

1. **Read existing database records**:
```python
db = sqlite_utils.Database(f"{STORAGE_DIR}/{subdomain}/meetings.db")
pages = list(db["minutes"].rows) + list(db["agendas"].rows)
```

2. **For each page**:
   - Read text from corresponding `.txt` file (using page metadata)
   - Check `.extracted.json` cache (existing cache system)
   - If uncached: Extract entities/votes with spaCy (SPACY_N_PROCESS=1)
   - Write to cache file
   - Update database: `UPDATE minutes SET entities_json = ?, votes_json = ? WHERE id = ?`

3. **Progress tracking**:
```
alameda.ca.civic.band: Found 15,432 pages
alameda.ca.civic.band: Cache hits: 14,200 (92%), needs extraction: 1,232
alameda.ca.civic.band: Extracting entities... [progress]
alameda.ca.civic.band: Completed in 18m 32s
```

**Memory profile**: Single-threaded spaCy (SPACY_N_PROCESS=1) keeps memory ~5GB constant.

## Deployment Integration

After successful extraction, trigger existing deployment hooks:

```python
if not os.environ.get("CIVIC_DEV_MODE"):
    pm.hook.deploy_municipality(
        subdomain=subdomain,
        municipality=site_name,
        db=db
    )
    pm.hook.post_deploy(
        subdomain=subdomain,
        municipality=site_name
    )
    log("Deployed updated database", subdomain=subdomain)
else:
    log("DEV MODE: Skipping deployment", subdomain=subdomain)
```

**Testing workflow**:
```bash
# Extract without deploying
CIVIC_DEV_MODE=1 ENABLE_EXTRACTION=1 clerk extract-entities --subdomain test.civic.band

# Production (deploys)
ENABLE_EXTRACTION=1 clerk extract-entities --next-site
```

## Error Handling

### Extraction Failures

**On spaCy crashes, missing files, corrupted cache**:
- Mark site as `extraction_status = 'failed'`
- Log error details
- Don't update `last_extracted`
- Next cron run will retry failed sites

### Partial Extraction

**If extraction fails mid-site**:
- Database transaction for updates (all-or-nothing per site)
- Cache files already written remain valid
- Retry resumes from where cache left off

### Deployment Failures

**If deploy fails after successful extraction**:
- Log error but don't mark extraction as failed
- Site stays in previous state
- Manual intervention needed

### Queue Management

**Prevent concurrent processing**:
```python
num_in_progress = db.execute(
    "SELECT COUNT(*) FROM sites WHERE extraction_status = 'in_progress'"
).fetchone()[0]

if num_in_progress > 0:
    log("Extraction already in progress, exiting")
    return
```

## Cron Setup

**Production cron** (runs every 30 minutes):
```cron
*/30 * * * * cd /path/to/clerk && ENABLE_EXTRACTION=1 clerk extract-entities --next-site
```

**With logging**:
```cron
*/30 * * * * cd /path/to/clerk && ENABLE_EXTRACTION=1 clerk extract-entities --next-site >> /var/log/clerk-extraction.log 2>&1
```

## Testing Strategy

### Unit Tests

- `test_migrate_extraction_schema()` - Column creation, idempotency
- `test_extract_entities_for_site()` - Mock spaCy, verify DB updates
- `test_site_selection_query()` - NULLS FIRST ordering, status filtering
- `test_dev_mode_skips_deploy()` - CIVIC_DEV_MODE honored

### Integration Tests

- `test_extract_entities_full_workflow()` - Small test site end-to-end
- `test_next_site_selection()` - Multiple sites, correct ordering
- `test_failed_extraction_retry()` - Failed site gets retried
- `test_cache_reuse_during_extraction()` - Cache hit rates verified

### Manual Testing Workflow

```bash
# 1. Migrate schema
clerk migrate-extraction-schema

# 2. Test extraction on small site (dev mode)
CIVIC_DEV_MODE=1 ENABLE_EXTRACTION=1 clerk extract-entities --subdomain small.civic.band

# 3. Verify database updated, deployment skipped
sqlite3 ../sites/small.civic.band/meetings.db "SELECT COUNT(*) FROM minutes WHERE entities_json != ''"

# 4. Test next-site selection
CIVIC_DEV_MODE=1 ENABLE_EXTRACTION=1 clerk extract-entities --next-site

# 5. Production test on one site
ENABLE_EXTRACTION=1 clerk extract-entities --subdomain test.civic.band
```

## Rollout Plan

1. **Deploy code** with new commands
2. **Run migration**: `clerk migrate-extraction-schema`
3. **Manual test** on 1-2 small sites
4. **Mark all sites for extraction**: `UPDATE sites SET extraction_status = 'pending'`
5. **Enable cron job** for gradual 900-site processing
6. **Monitor** progress via extraction_status queries

## Benefits

**Immediate**:
- Database builds fast (seconds/minutes vs 20 minutes)
- Sites go live immediately with searchable text
- Minimal memory footprint (~5GB per extraction)

**Operational**:
- Sequential processing prevents memory spikes
- Failed extractions don't block database builds
- Can prioritize which sites get extraction first
- Resume interrupted processing automatically

**Flexibility**:
- Run extraction on different machines/schedules
- Test extraction without affecting production
- Retry failed extractions independently
- Clear visibility into extraction status

## Trade-offs

**Complexity**: Two commands instead of one
**Deployment timing**: Sites initially deployed without entities/votes
**Status tracking**: Need to monitor extraction_status separately

These are acceptable given the operational benefits and 900-site rebuild requirement.
