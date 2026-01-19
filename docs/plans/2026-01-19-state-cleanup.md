# Pipeline State Cleanup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove old state management infrastructure after atomic counter system proves stable.

**Architecture:** Phased cleanup starting with code dependencies, then database schema. Each phase is deployable independently to minimize risk.

**Tech Stack:** SQLAlchemy, Alembic migrations, Python

**Context:** This plan should be executed 1-2 weeks after the pipeline state consolidation migration has "baked" in production. See success criteria below.

---

## Pre-Flight Verification

**DO NOT proceed with this plan until ALL criteria are met:**

### Success Criteria Checklist

Run these verification queries and confirm thresholds:

```sql
-- 1. Stuck sites <1%
SELECT
    COUNT(*) FILTER (WHERE updated_at < NOW() - INTERVAL '2 hours') as stuck,
    COUNT(*) as total,
    ROUND(100.0 * COUNT(*) FILTER (WHERE updated_at < NOW() - INTERVAL '2 hours') / COUNT(*), 1) as stuck_pct
FROM sites
WHERE current_stage != 'completed' AND current_stage IS NOT NULL;
-- REQUIRED: stuck_pct < 1.0

-- 2. Reconciliation finding <5 stuck sites per run (check logs)
-- REQUIRED: Last 10 reconciliation runs found <5 stuck sites each

-- 3. Health score >95%
SELECT
    ROUND(100.0 *
        COUNT(*) FILTER (
            WHERE current_stage = 'completed'
               OR updated_at >= NOW() - INTERVAL '2 hours'
        ) / NULLIF(COUNT(*), 0),
    1) as health_score
FROM sites
WHERE current_stage IS NOT NULL;
-- REQUIRED: health_score >= 95.0

-- 4. No manual intervention needed for 7+ days
-- REQUIRED: No manual site unsticking in past week
```

**If ANY criterion fails:** STOP. Wait longer for system to stabilize.

**Backup before proceeding:**
```bash
# On production server
pg_dump $DATABASE_URL > civic_db_backup_$(date +%Y%m%d).sql
```

---

## Overview of What Gets Removed

### 1. site_progress Table (Entire Table)
Old source of truth with these columns:
- subdomain (PK)
- current_stage
- stage_total
- stage_completed
- started_at
- updated_at

**Replaced by:** Atomic counters in sites table

### 2. Legacy Columns in sites Table
- `status` (String) → replaced by `current_stage`
- `extraction_status` (String) → replaced by extraction counters
- `last_updated` (String) → replaced by `updated_at` (DateTime)
- `last_deployed` (String) → replaced by `updated_at` when stage='completed'
- `last_extracted` (String) → replaced by extraction counters

### 3. Code Dependencies
- `update_site_progress()` function in queue_db.py
- `increment_stage_progress()` function in queue_db.py
- All `update_site(conn, subdomain, {"status": ...})` calls in workers.py
- Tests that assert on site_progress or legacy status fields

---

## Task 1: Remove site_progress Function Dependencies

**Goal:** Remove functions that write to site_progress table from queue_db.py

**Files:**
- Modify: `src/clerk/queue_db.py` (lines 59-100)
- Test: `tests/test_queue_db.py`

**Step 1: Read current queue_db.py to see what needs removal**

Read the file to identify:
- `update_site_progress()` function (lines ~59-83)
- `increment_stage_progress()` function (lines ~85-100)

**Step 2: Remove update_site_progress function**

Delete the entire function:
```python
def update_site_progress(conn, subdomain, stage=None, stage_total=None):
    """Update site progress.

    Args:
        conn: SQLAlchemy connection
        subdomain: Site subdomain
        stage: New stage (optional)
        stage_total: Total items in stage (optional)
    """
    # ... entire function body ...
```

**Step 3: Remove increment_stage_progress function**

Delete the entire function:
```python
def increment_stage_progress(conn, subdomain):
    """Increment the stage completion counter.

    Args:
        conn: SQLAlchemy connection
        subdomain: Site subdomain
    """
    # ... entire function body ...
```

**Step 4: Remove site_progress_table import if unused**

Check if site_progress_table is imported at top of file:
```python
from .models import site_progress_table  # Remove this line if present
```

**Step 5: Check test_queue_db.py for breakage**

Run: `uv run pytest tests/test_queue_db.py -v`

Expected: Tests that use these functions will fail. That's OK - we'll update them later.

**Step 6: Commit**

```bash
git add src/clerk/queue_db.py
git commit -m "refactor: remove site_progress table functions

These functions are no longer needed after migration to atomic
counters. They wrote to the old site_progress table which will
be dropped in a later migration.

Breaking change: update_site_progress() and increment_stage_progress()
removed. All callers should use atomic counter APIs instead."
```

---

## Task 2: Remove site_progress Calls from Workers

**Goal:** Remove all calls to update_site_progress and increment_stage_progress in workers.py

**Files:**
- Modify: `src/clerk/workers.py` (lines 192, 842, 1059-1060)
- Test: `tests/test_workers.py`

**Step 1: Find all update_site_progress calls**

Search for pattern: `update_site_progress(`

Expected locations:
- Line ~192: After fetch, before OCR
- Line ~842: After extraction, before deploy
- Line ~1059: When marking completed

**Step 2: Remove call at line 192 (fetch → OCR transition)**

Find this code:
```python
# Update progress: moving to OCR stage
with civic_db_connection() as conn:
    update_site_progress(conn, subdomain, stage="ocr", stage_total=len(pdf_files))
    # Update legacy status field for backward compatibility
    update_site(
        conn,
        subdomain,
        {
            "status": "needs_ocr",
            "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
```

Change to:
```python
# NOTE: Stage transition handled by initialize_stage() call earlier in pipeline
# No need to update site_progress (table will be dropped)
```

**Step 3: Remove call at line 842 (extraction → deploy transition)**

Find this code:
```python
# Update progress: moving to deploy stage
with civic_db_connection() as conn:
    update_site_progress(conn, subdomain, stage="deploy", stage_total=1)
    # Update legacy status field for backward compatibility
    update_site(
        conn,
        subdomain,
        {
            "status": "needs_deploy",
            "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
```

Change to:
```python
# NOTE: Stage transition handled by atomic counter updates
# No need to update site_progress (table will be dropped)
```

**Step 4: Remove calls at lines 1059-1060 (completion)**

Find this code:
```python
with civic_db_connection() as conn:
    update_site_progress(conn, subdomain, stage="completed", stage_total=1)
    increment_stage_progress(conn, subdomain)
    # Update legacy status field for backward compatibility
    update_site(
        conn,
        subdomain,
        {
            "status": "deployed",
            "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
```

Change to:
```python
# NOTE: Completion handled by current_stage update in atomic counter system
# No need to update site_progress (table will be dropped)
```

**Step 5: Remove import if no longer used**

Check top of file for:
```python
from .queue_db import increment_stage_progress, update_site_progress
```

Remove these from the import list if present.

**Step 6: Run tests to verify atomic counters still work**

Run: `uv run pytest tests/test_workers.py -v -k "test_ocr" -x`

Expected: Tests should still pass. Pipeline should still transition stages correctly using atomic counters.

**Step 7: Commit**

```bash
git add src/clerk/workers.py
git commit -m "refactor: remove site_progress table updates from workers

Removes all update_site_progress() and increment_stage_progress()
calls. Stage transitions now rely entirely on atomic counter system
in sites table.

No behavior change - atomic counters already handle all state tracking."
```

---

## Task 3: Remove Legacy Status Field Updates (Part 1: No Documents Case)

**Goal:** Remove first update_site() call that writes to legacy status field

**Files:**
- Modify: `src/clerk/workers.py` (lines ~571-578)
- Test: `tests/test_workers.py`

**Context:** There are 5 update_site() calls in workers.py that write to the legacy "status" field. We'll remove them one at a time to minimize risk.

**Step 1: Locate the "no_documents" status update**

Find this code in ocr_complete_coordinator around line 571:
```python
# Update legacy status
update_site(
    conn,
    subdomain,
    {
        "status": "no_documents",
        "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    },
)
```

**Step 2: Remove the update_site call**

Delete the entire call:
```python
# Update legacy status
update_site(
    conn,
    subdomain,
    {
        "status": "no_documents",
        "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    },
)
```

**Step 3: Add comment explaining removal**

Add this comment where the code was:
```python
# Legacy status field removed - use current_stage='completed' + last_error_message instead
```

**Step 4: Verify no duplicate status tracking**

Ensure the code already sets current_stage='completed' and last_error_message for this case.

Expected: Should see earlier in the function:
```python
conn.execute(
    update(sites_table)
    .where(sites_table.c.subdomain == subdomain)
    .values(
        current_stage="completed",
        last_error_stage="fetch",
        last_error_message="No PDFs found during fetch - site may have no documents or fetch failed",
        last_error_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
)
```

**Step 5: Run test to verify behavior unchanged**

Run: `uv run pytest tests/test_workers.py::test_ocr_coordinator_no_documents -v`

Expected: Test passes. Site marked as completed with error tracking.

**Step 6: Commit**

```bash
git add src/clerk/workers.py
git commit -m "refactor: remove legacy status='no_documents' update

Use current_stage='completed' + last_error_message instead.
Legacy status field will be dropped in database migration."
```

---

## Task 4: Remove Legacy Status Field Updates (Part 2: Needs OCR)

**Goal:** Remove update_site() call that writes status='needs_ocr'

**Files:**
- Modify: `src/clerk/workers.py` (lines ~194-201)

**Step 1: Locate the "needs_ocr" status update**

Find this code after fetch completion around line 194:
```python
# Update legacy status field for backward compatibility
update_site(
    conn,
    subdomain,
    {
        "status": "needs_ocr",
        "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    },
)
```

**Step 2: Remove the update_site call and comment**

Delete the entire block including comment.

**Step 3: Verify initialize_stage already sets current_stage**

Check earlier in function for:
```python
initialize_stage(subdomain, stage="ocr", total_jobs=len(ocr_job_ids))
```

Expected: This should set current_stage="ocr" in sites table.

**Step 4: Run test**

Run: `uv run pytest tests/test_workers.py::test_fetch_coordinator -v`

Expected: Test passes. Site transitions to OCR stage correctly.

**Step 5: Commit**

```bash
git add src/clerk/workers.py
git commit -m "refactor: remove legacy status='needs_ocr' update

Use current_stage='ocr' set by initialize_stage() instead."
```

---

## Task 5: Remove Legacy Status Field Updates (Part 3: Needs Extraction)

**Goal:** Remove update_site() call that writes status='needs_extraction'

**Files:**
- Modify: `src/clerk/workers.py` (lines ~620-627)

**Step 1: Locate the "needs_extraction" status update**

Find this code in ocr_complete_coordinator around line 620:
```python
# Update legacy status field for backward compatibility
update_site(
    conn,
    subdomain,
    {
        "status": "needs_extraction",
        "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    },
)
```

**Step 2: Remove the update_site call**

Delete the entire block.

**Step 3: Verify sites table update sets current_stage**

Check earlier in the function for:
```python
conn.execute(
    update(sites_table)
    .where(sites_table.c.subdomain == subdomain)
    .values(
        current_stage="extraction",
        updated_at=datetime.now(UTC),
    )
)
```

**Step 4: Run test**

Run: `uv run pytest tests/test_workers.py::test_ocr_coordinator_success -v`

Expected: Test passes. Site transitions to extraction stage.

**Step 5: Commit**

```bash
git add src/clerk/workers.py
git commit -m "refactor: remove legacy status='needs_extraction' update

Use current_stage='extraction' set in sites table update instead."
```

---

## Task 6: Remove Legacy Status Field Updates (Part 4: Needs Deploy)

**Goal:** Remove update_site() call that writes status='needs_deploy'

**Files:**
- Modify: `src/clerk/workers.py` (lines ~844-851)

**Step 1: Locate the "needs_deploy" status update**

Find this code in extraction_coordinator around line 844:
```python
# Update legacy status field for backward compatibility
update_site(
    conn,
    subdomain,
    {
        "status": "needs_deploy",
        "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    },
)
```

**Step 2: Remove the update_site call**

Delete the entire block.

**Step 3: Verify current_stage='deploy' is set**

Check for atomic counter update that sets current_stage.

**Step 4: Run test**

Run: `uv run pytest tests/test_workers.py::test_extraction_coordinator -v`

Expected: Test passes.

**Step 5: Commit**

```bash
git add src/clerk/workers.py
git commit -m "refactor: remove legacy status='needs_deploy' update

Use current_stage='deploy' instead."
```

---

## Task 7: Remove Legacy Status Field Updates (Part 5: Deployed)

**Goal:** Remove final update_site() call that writes status='deployed'

**Files:**
- Modify: `src/clerk/workers.py` (lines ~1062-1069)

**Step 1: Locate the "deployed" status update**

Find this code in deploy_coordinator around line 1062:
```python
# Update legacy status field for backward compatibility
update_site(
    conn,
    subdomain,
    {
        "status": "deployed",
        "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    },
)
```

**Step 2: Remove the update_site call**

Delete the entire block.

**Step 3: Verify current_stage='completed' is set**

Check for sites table update setting current_stage="completed".

**Step 4: Run test**

Run: `uv run pytest tests/test_workers.py::test_deploy_coordinator -v`

Expected: Test passes.

**Step 5: Commit**

```bash
git add src/clerk/workers.py
git commit -m "refactor: remove legacy status='deployed' update

Use current_stage='completed' instead. This completes removal
of all legacy status field updates from workers."
```

---

## Task 8: Update CLI Commands to Use current_stage

**Goal:** Replace any CLI commands that read the legacy "status" field with current_stage

**Files:**
- Read: `src/clerk/cli.py`
- Modify: Various CLI commands as needed

**Step 1: Search for status field reads**

Search pattern: `site.status` or `sites_table.c.status`

Run: `uv run rg 'site\.status|sites_table\.c\.status' src/clerk/cli.py`

**Step 2: For each usage, determine replacement**

Map legacy status values to current_stage:
- `status="needs_ocr"` → `current_stage="ocr"`
- `status="needs_extraction"` → `current_stage="extraction"`
- `status="needs_deploy"` → `current_stage="deploy"`
- `status="deployed"` → `current_stage="completed"`
- `status="no_documents"` → `current_stage="completed"` + check last_error_message

**Step 3: Update each command**

For each occurrence, replace:
```python
# Before
if site.status == "deployed":
    ...

# After
if site.current_stage == "completed":
    ...
```

**Step 4: Test affected commands**

Run: `uv run pytest tests/test_cli.py -v`

Expected: All CLI tests pass.

**Step 5: Test manually if needed**

If any commands don't have tests, test manually:
```bash
clerk <command-name>
```

**Step 6: Commit**

```bash
git add src/clerk/cli.py
git commit -m "refactor: update CLI commands to use current_stage

Replace all legacy status field reads with current_stage.
Prepares for dropping status column from database."
```

---

## Task 9: Update get_oldest_site to Use updated_at

**Goal:** Replace last_updated (String) with updated_at (DateTime) in get_oldest_site function

**Files:**
- Modify: `src/clerk/db.py` (lines 232-269)

**Step 1: Read current get_oldest_site implementation**

Note: Function currently casts last_updated from String to DateTime.

**Step 2: Replace with updated_at column**

Change from:
```python
last_updated_dt = cast(sites_table.c.last_updated, DateTime)

stmt = (
    select(sites_table.c.subdomain)
    .where(
        or_(
            sites_table.c.last_updated.is_(None),
            last_updated_dt < cutoff,
        )
    )
    .order_by(sites_table.c.last_updated.asc().nulls_first())
    .limit(1)
)
```

To:
```python
stmt = (
    select(sites_table.c.subdomain)
    .where(
        or_(
            sites_table.c.updated_at.is_(None),
            sites_table.c.updated_at < cutoff,
        )
    )
    .order_by(sites_table.c.updated_at.asc().nulls_first())
    .limit(1)
)
```

**Step 3: Remove cast import if no longer needed**

Check if `cast` from sqlalchemy is still used elsewhere in file. If not, remove from imports.

**Step 4: Update docstring**

Change:
```python
"""Find site with oldest last_updated timestamp."""
```

To:
```python
"""Find site with oldest updated_at timestamp."""
```

**Step 5: Test**

Run: `uv run pytest tests/test_db.py::test_get_oldest_site -v`

Expected: Test passes.

**Step 6: Commit**

```bash
git add src/clerk/db.py
git commit -m "refactor: use updated_at instead of last_updated in get_oldest_site

Replace string-based last_updated with DateTime updated_at column.
Simpler and more accurate."
```

---

## Task 10: Create Migration to Drop site_progress Table

**Goal:** Create Alembic migration that drops site_progress table

**Files:**
- Create: `alembic/versions/<rev>_drop_site_progress_table.py`

**Step 1: Generate migration skeleton**

Run: `alembic revision -m "drop_site_progress_table"`

Expected: Creates new file `alembic/versions/<revision>_drop_site_progress_table.py`

**Step 2: Implement upgrade function**

```python
def upgrade() -> None:
    """Drop site_progress table - replaced by atomic counters in sites table."""
    op.drop_table("site_progress")
```

**Step 3: Implement downgrade function**

```python
def downgrade() -> None:
    """Recreate site_progress table if rollback needed."""
    op.create_table(
        "site_progress",
        sa.Column("subdomain", sa.String(), nullable=False),
        sa.Column("current_stage", sa.String(), nullable=True),
        sa.Column("stage_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stage_completed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("subdomain"),
    )
```

**Step 4: Test migration locally**

```bash
# Upgrade
alembic upgrade head

# Verify table dropped
psql $DATABASE_URL -c "\dt site_progress"
# Expected: "Did not find any relation named 'site_progress'"

# Downgrade to test rollback
alembic downgrade -1

# Verify table recreated
psql $DATABASE_URL -c "\dt site_progress"
# Expected: Table exists

# Upgrade again
alembic upgrade head
```

**Step 5: Commit**

```bash
git add alembic/versions/*_drop_site_progress_table.py
git commit -m "migration: drop site_progress table

Table replaced by atomic counters in sites table.
All code dependencies removed in previous commits.

Safe to drop after 1-2 weeks of stable operation."
```

---

## Task 11: Create Migration to Drop Legacy Columns from sites Table

**Goal:** Create Alembic migration that drops legacy columns from sites table

**Files:**
- Create: `alembic/versions/<rev>_drop_legacy_status_columns.py`

**Step 1: Generate migration skeleton**

Run: `alembic revision -m "drop_legacy_status_columns"`

**Step 2: Implement upgrade function**

```python
def upgrade() -> None:
    """Drop legacy status tracking columns from sites table.

    These columns are replaced by:
    - status → current_stage
    - extraction_status → extraction_* counters
    - last_updated → updated_at
    - last_deployed → updated_at when current_stage='completed'
    - last_extracted → extraction_* counters
    """
    op.drop_column("sites", "last_extracted")
    op.drop_column("sites", "last_deployed")
    op.drop_column("sites", "last_updated")
    op.drop_column("sites", "extraction_status")
    op.drop_column("sites", "status")
```

**Step 3: Implement downgrade function**

```python
def downgrade() -> None:
    """Recreate legacy columns if rollback needed."""
    op.add_column("sites", sa.Column("status", sa.String(), nullable=True))
    op.add_column(
        "sites",
        sa.Column("extraction_status", sa.String(), server_default="pending", nullable=True),
    )
    op.add_column("sites", sa.Column("last_updated", sa.String(), nullable=True))
    op.add_column("sites", sa.Column("last_deployed", sa.String(), nullable=True))
    op.add_column("sites", sa.Column("last_extracted", sa.String(), nullable=True))
```

**Step 4: Test migration locally**

```bash
# Upgrade
alembic upgrade head

# Verify columns dropped
psql $DATABASE_URL -c "\d sites" | grep -E "status|last_updated|last_deployed|last_extracted|extraction_status"
# Expected: No matches

# Downgrade to test rollback
alembic downgrade -1

# Verify columns recreated
psql $DATABASE_URL -c "\d sites" | grep -E "status|last_updated"
# Expected: Columns exist

# Upgrade again
alembic upgrade head
```

**Step 5: Commit**

```bash
git add alembic/versions/*_drop_legacy_status_columns.py
git commit -m "migration: drop legacy status columns from sites table

Removes:
- status → use current_stage
- extraction_status → use extraction_* counters
- last_updated → use updated_at
- last_deployed → use updated_at when current_stage='completed'
- last_extracted → use extraction_* counters

All code updated to use new columns in previous commits."
```

---

## Task 12: Remove site_progress_table from Models

**Goal:** Remove site_progress_table definition from models.py

**Files:**
- Modify: `src/clerk/models.py` (lines 70-79)

**Step 1: Remove table definition**

Delete this code:
```python
site_progress_table = Table(
    "site_progress",
    metadata,
    Column("subdomain", String, primary_key=True),
    Column("current_stage", String, nullable=True),
    Column("stage_total", Integer, server_default="0"),
    Column("stage_completed", Integer, server_default="0"),
    Column("started_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
```

**Step 2: Remove legacy column definitions from sites_table**

Delete these lines from sites_table definition:
```python
# Deprecated (keep during migration)
Column("status", String),
Column("extraction_status", String, server_default="pending"),
Column("last_updated", String),
Column("last_deployed", String),
Column("last_extracted", String),
```

**Step 3: Remove deprecation comment**

Delete the comment `# Deprecated (keep during migration)` from sites_table.

**Step 4: Verify imports are used**

Check that no other code imports site_progress_table.

Run: `uv run rg "from.*models import.*site_progress_table|from .models import.*site_progress_table"`

Expected: Only migration files (if any) should import it.

**Step 5: Run tests**

Run: `uv run pytest tests/test_models.py -v`

Expected: Tests pass.

**Step 6: Commit**

```bash
git add src/clerk/models.py
git commit -m "refactor: remove site_progress_table and legacy columns from models

Table and columns dropped in database migrations.
Models now reflect actual production schema."
```

---

## Task 13: Update Tests to Remove site_progress References

**Goal:** Update all tests to remove assertions on site_progress table and legacy status fields

**Files:**
- Modify: `tests/test_workers.py`
- Modify: `tests/test_queue_db.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_db.py`
- Modify: Other test files as needed

**Step 1: Find all site_progress assertions**

Run: `uv run rg "site_progress|\.status.*==" tests/`

**Step 2: Update test_workers.py**

For each test that asserts on site_progress:
```python
# Before
result = conn.execute(select(site_progress_table)).fetchone()
assert result.current_stage == "ocr"

# After (use sites_table instead)
result = conn.execute(
    select(sites_table).where(sites_table.c.subdomain == subdomain)
).fetchone()
assert result.current_stage == "ocr"
```

For each test that asserts on legacy status:
```python
# Before
assert site.status == "deployed"

# After
assert site.current_stage == "completed"
```

**Step 3: Remove test_queue_db.py tests for removed functions**

If tests exist for `update_site_progress()` or `increment_stage_progress()`, delete them:
```python
def test_update_site_progress():
    # DELETE THIS TEST
    pass

def test_increment_stage_progress():
    # DELETE THIS TEST
    pass
```

**Step 4: Update fixture data**

Check `tests/fixtures/sample_sites.json` for legacy status fields.

Remove or update:
```json
{
  "subdomain": "example",
  "status": "deployed",  // Remove this
  "last_updated": "2024-01-01T00:00:00"  // Remove this
}
```

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`

Expected: All tests pass.

**Step 6: Commit**

```bash
git add tests/
git commit -m "test: remove site_progress and legacy status assertions

Update tests to use current_stage and sites table atomic counters.
Removes tests for deleted functions."
```

---

## Task 14: Update Documentation

**Goal:** Update docs to reflect new state management system

**Files:**
- Modify: `docs/developer-guide/architecture.md`
- Modify: `docs/user-guide/task-queue.md`
- Modify: Any other docs mentioning site_progress or legacy status

**Step 1: Search docs for mentions**

Run: `uv run rg "site_progress|status.*deployed|status.*needs_ocr" docs/`

**Step 2: Update architecture.md**

Replace any mentions of:
- "site_progress table" → "atomic counters in sites table"
- "3 sources of truth" → "single source of truth (sites table)"
- "status field" → "current_stage field"

**Step 3: Update user-guide/task-queue.md**

Update any references to old state management to reflect new atomic counter system.

**Step 4: Review and commit**

```bash
git add docs/
git commit -m "docs: update for atomic counter state management

Remove references to site_progress table and legacy status field.
Document single source of truth in sites table."
```

---

## Task 15: Deploy and Verify in Production

**Goal:** Deploy all changes to production and verify pipeline still works

**NOT AUTOMATED - Manual Steps**

**Step 1: Deploy code changes**

```bash
# On production server
pip install --upgrade clerk

# Verify version
clerk --version
```

**Step 2: Run database migrations**

```bash
# On production server
alembic upgrade head
```

**Step 3: Verify site_progress table dropped**

```bash
psql $DATABASE_URL -c "\dt site_progress"
```

Expected: "Did not find any relation named 'site_progress'"

**Step 4: Verify legacy columns dropped**

```bash
psql $DATABASE_URL -c "\d sites" | grep -E "status|last_updated|extraction_status"
```

Expected: No matches (only current_stage and updated_at should exist)

**Step 5: Monitor pipeline for 24 hours**

Use monitoring queries from earlier:
```bash
clerk pipeline-status
```

Check:
- Sites still transitioning through stages
- No errors about missing columns
- Reconciliation still working
- Success rates unchanged

**Step 6: Check logs for errors**

```bash
grep -i "column.*status\|site_progress" /var/log/clerk-*.log
```

Expected: No errors about missing columns or tables

---

## Task 16: Rollback Plan (If Something Goes Wrong)

**Goal:** Document how to rollback if issues arise

**NOT A TASK - Reference Only**

If issues occur after deployment:

### 1. Rollback Database Migrations

```bash
# On production server
alembic downgrade -2  # Go back 2 migrations (before both drops)
```

This recreates:
- site_progress table
- Legacy columns in sites table

### 2. Rollback Code

```bash
# On production server
pip install clerk==<previous-version>
```

### 3. Verify Rollback

```bash
psql $DATABASE_URL -c "\dt site_progress"  # Should exist
psql $DATABASE_URL -c "\d sites" | grep status  # Should show status column
```

### 4. Resume Operations

```bash
clerk reconcile-pipeline  # Should work with old system
```

---

## Success Criteria

After completing all tasks and deploying:

✅ `site_progress` table dropped from database
✅ Legacy columns (`status`, `extraction_status`, `last_updated`, `last_deployed`, `last_extracted`) dropped from `sites` table
✅ All tests passing
✅ Pipeline still processing sites correctly
✅ Reconciliation still working
✅ No errors in production logs
✅ `clerk pipeline-status` shows healthy metrics
✅ Documentation updated

---

## Estimated Timeline

- **Task 1-3:** 30 minutes (remove site_progress dependencies)
- **Task 4-7:** 1 hour (remove legacy status updates one by one)
- **Task 8-9:** 30 minutes (update CLI and db.py)
- **Task 10-11:** 30 minutes (create migrations)
- **Task 12:** 10 minutes (clean up models)
- **Task 13:** 1 hour (update tests)
- **Task 14:** 20 minutes (update docs)
- **Task 15:** 30 minutes (deploy and verify)

**Total:** ~4-5 hours of implementation work

**Note:** Does NOT include the 1-2 week "baking" period before starting.

---

## References

- Original design: `docs/plans/2026-01-18-pipeline-state-consolidation-design.md`
- Implementation: `docs/plans/2026-01-18-pipeline-state-consolidation.md`
- Migration guide: `docs/plans/MIGRATION-pipeline-state-consolidation-UPDATED.md`
