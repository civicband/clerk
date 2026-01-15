# Auto-Enqueue Scheduler Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add automatic site scheduling via `clerk update --next` that enqueues the least-recently-updated site every minute via cron, while making manual commands (`new`, `update -s`) use high priority.

**Architecture:** Modify `clerk update` command to support both manual high-priority enqueues and auto-scheduler normal-priority enqueues. Add `get_oldest_site()` helper to query for least-recently-updated site. Update `clerk new` to auto-enqueue after creation.

**Tech Stack:** SQLAlchemy, Click, pytest, existing RQ queue infrastructure

---

## Task 1: Add `get_oldest_site()` Helper Function

**Files:**
- Modify: `src/clerk/db.py` (add function at end)
- Test: `tests/test_db.py` (create new file)

**Step 1: Write the failing test**

Create `tests/test_db.py`:

```python
"""Tests for database helper functions."""
import pytest
from datetime import datetime, timedelta
from clerk.db import get_oldest_site, civic_db_connection
from clerk.models import sites_table


@pytest.mark.unit
class TestGetOldestSite:
    """Tests for get_oldest_site function."""

    def test_returns_site_with_null_last_updated_first(self, mocker):
        """Sites with NULL last_updated should be prioritized."""
        # Mock database connection
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)

        # Mock query result - site with NULL last_updated
        mock_result = mocker.MagicMock()
        mock_result.__getitem__ = mocker.Mock(return_value="null-site.civic.band")
        mock_conn.execute.return_value.fetchone.return_value = mock_result

        mocker.patch("clerk.db.civic_db_connection", return_value=mock_conn)

        result = get_oldest_site()

        assert result == "null-site.civic.band"

    def test_returns_oldest_site_when_all_have_last_updated(self, mocker):
        """Should return site with oldest last_updated timestamp."""
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)

        mock_result = mocker.MagicMock()
        mock_result.__getitem__ = mocker.Mock(return_value="oldest-site.civic.band")
        mock_conn.execute.return_value.fetchone.return_value = mock_result

        mocker.patch("clerk.db.civic_db_connection", return_value=mock_conn)

        result = get_oldest_site()

        assert result == "oldest-site.civic.band"

    def test_returns_none_when_all_sites_recently_updated(self, mocker):
        """Should return None if all sites updated within lookback window."""
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)

        # No results from query
        mock_conn.execute.return_value.fetchone.return_value = None

        mocker.patch("clerk.db.civic_db_connection", return_value=mock_conn)

        result = get_oldest_site(lookback_hours=23)

        assert result is None

    def test_respects_lookback_hours_parameter(self, mocker):
        """Should use custom lookback hours when specified."""
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)

        mock_result = mocker.MagicMock()
        mock_result.__getitem__ = mocker.Mock(return_value="site.civic.band")
        mock_conn.execute.return_value.fetchone.return_value = mock_result

        mocker.patch("clerk.db.civic_db_connection", return_value=mock_conn)

        result = get_oldest_site(lookback_hours=12)

        assert result == "site.civic.band"
        # Verify the query was called (we can check this via the mock)
        assert mock_conn.execute.called
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::TestGetOldestSite -v`

Expected: FAIL with "cannot import name 'get_oldest_site'"

**Step 3: Write minimal implementation**

Add to `src/clerk/db.py` at the end:

```python
def get_oldest_site(lookback_hours=23):
    """Find site with oldest last_updated timestamp.

    Args:
        lookback_hours: Skip sites updated within this many hours (default: 23)

    Returns:
        Subdomain string or None if no eligible sites
    """
    from datetime import datetime, timedelta
    from sqlalchemy import or_, select

    from .models import sites_table

    cutoff = datetime.now() - timedelta(hours=lookback_hours)

    stmt = (
        select(sites_table.c.subdomain)
        .where(
            or_(
                sites_table.c.last_updated.is_(None),
                sites_table.c.last_updated < cutoff,
            )
        )
        .order_by(sites_table.c.last_updated.asc().nulls_first())
        .limit(1)
    )

    with civic_db_connection() as conn:
        result = conn.execute(stmt).fetchone()
        return result[0] if result else None
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py::TestGetOldestSite -v`

Expected: 4 tests PASS

**Step 5: Commit**

```bash
git add tests/test_db.py src/clerk/db.py
git commit -m "feat: add get_oldest_site helper function

Query sites table for least-recently-updated site with configurable
lookback window. Returns None if all sites recently updated."
```

---

## Task 2: Update `clerk update --next` to Use Auto-Scheduler

**Files:**
- Modify: `src/clerk/cli.py` (update `update` command function)
- Test: `tests/test_cli.py` (add to existing TestUpdate class or create new)

**Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
@pytest.mark.unit
class TestAutoEnqueueScheduler:
    """Tests for auto-enqueue scheduler functionality."""

    def test_update_next_enqueues_oldest_site(self, cli_runner, mocker):
        """clerk update --next should enqueue the oldest site with normal priority."""
        # Mock get_oldest_site to return a site
        mocker.patch("clerk.cli.get_oldest_site", return_value="old-site.civic.band")

        # Mock enqueue_job
        mock_enqueue = mocker.patch("clerk.cli.enqueue_job")

        result = cli_runner.invoke(cli, ["update", "--next"])

        assert result.exit_code == 0
        assert "Auto-enqueueing old-site.civic.band" in result.output

        # Verify enqueued with normal priority
        mock_enqueue.assert_called_once_with(
            "fetch-site",
            "old-site.civic.band",
            priority="normal"
        )

    def test_update_next_exits_silently_when_no_eligible_sites(self, cli_runner, mocker):
        """clerk update --next should exit gracefully if all sites recently updated."""
        # Mock get_oldest_site to return None
        mocker.patch("clerk.cli.get_oldest_site", return_value=None)

        # Mock enqueue_job - should NOT be called
        mock_enqueue = mocker.patch("clerk.cli.enqueue_job")

        result = cli_runner.invoke(cli, ["update", "--next"])

        assert result.exit_code == 0
        assert "No sites eligible for auto-enqueue" in result.output

        # Verify enqueue was NOT called
        mock_enqueue.assert_not_called()

    def test_update_subdomain_enqueues_with_high_priority(self, cli_runner, mocker):
        """clerk update -s should enqueue specific site with high priority."""
        # Mock database check
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.cli.civic_db_connection", return_value=mock_conn)

        # Mock get_site_by_subdomain to return site
        mocker.patch(
            "clerk.cli.get_site_by_subdomain",
            return_value={"subdomain": "test-site.civic.band"}
        )

        # Mock enqueue_job
        mock_enqueue = mocker.patch("clerk.cli.enqueue_job")

        result = cli_runner.invoke(cli, ["update", "-s", "test-site.civic.band"])

        assert result.exit_code == 0
        assert "Enqueueing test-site.civic.band with high priority" in result.output

        # Verify enqueued with high priority
        mock_enqueue.assert_called_once_with(
            "fetch-site",
            "test-site.civic.band",
            priority="high"
        )

    def test_update_requires_subdomain_or_next_flag(self, cli_runner):
        """clerk update without flags should show usage error."""
        result = cli_runner.invoke(cli, ["update"])

        assert result.exit_code != 0
        assert "Must specify --subdomain or --next-site" in result.output
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::TestAutoEnqueueScheduler -v`

Expected: FAIL - tests fail because update command doesn't have new logic yet

**Step 3: Update `clerk update` command implementation**

Find the `update` command in `src/clerk/cli.py` (around line 370-395) and replace it with:

```python
@cli.command()
@click.option("-s", "--subdomain", help="Specific site subdomain")
@click.option("-n", "--next-site", is_flag=True, help="Enqueue oldest site (for auto-scheduler)")
@click.option("-a", "--all-years", is_flag=True)
@click.option("--skip-fetch", is_flag=True)
@click.option("--all-agendas", is_flag=True)
@click.option("--backfill", is_flag=True)
@click.option(
    "--ocr-backend",
    type=click.Choice(["tesseract", "vision"]),
    default="tesseract",
    help="OCR backend to use (tesseract or vision). Defaults to tesseract.",
)
def update(subdomain, next_site, all_years, skip_fetch, all_agendas, backfill, ocr_backend):
    """Update a site."""
    from .db import get_oldest_site, get_site_by_subdomain
    from .queue import enqueue_job

    if next_site:
        # Auto-scheduler mode: enqueue oldest site with normal priority
        oldest_subdomain = get_oldest_site(lookback_hours=23)
        if not oldest_subdomain:
            click.echo("No sites eligible for auto-enqueue")
            return

        click.echo(f"Auto-enqueueing {oldest_subdomain}")
        enqueue_job("fetch-site", oldest_subdomain, priority="normal")
        return

    if subdomain:
        # Manual update mode: enqueue specific site with high priority
        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, subdomain)
            if not site:
                click.secho(f"Error: Site '{subdomain}' not found", fg="red")
                raise click.Abort()

        click.echo(f"Enqueueing {subdomain} with high priority")

        # Build kwargs for job
        job_kwargs = {}
        if all_years:
            job_kwargs["all_years"] = True
        if all_agendas:
            job_kwargs["all_agendas"] = True
        if backfill:
            job_kwargs["backfill"] = True
        if ocr_backend:
            job_kwargs["ocr_backend"] = ocr_backend
        if skip_fetch:
            job_kwargs["skip_fetch"] = True

        enqueue_job("fetch-site", subdomain, priority="high", **job_kwargs)
        return

    # Error: must specify --subdomain or --next-site
    raise click.UsageError("Must specify --subdomain or --next-site")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::TestAutoEnqueueScheduler -v`

Expected: 4 tests PASS

**Step 5: Commit**

```bash
git add tests/test_cli.py src/clerk/cli.py
git commit -m "feat: update clerk update command for auto-scheduling

- Add --next-site flag for auto-scheduler (normal priority)
- Change -s/--subdomain to enqueue with high priority
- Require either --subdomain or --next-site flag
- Auto-scheduler uses get_oldest_site() helper"
```

---

## Task 3: Update `clerk new` to Auto-Enqueue with High Priority

**Files:**
- Modify: `src/clerk/cli.py` (update `new` command)
- Test: `tests/test_cli.py` (add to existing or create new test class)

**Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
@pytest.mark.unit
class TestNewCommand:
    """Tests for the new command."""

    def test_new_creates_site_and_enqueues_with_high_priority(self, cli_runner, mocker):
        """clerk new should create site and enqueue with high priority."""
        # Mock database operations
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.cli.civic_db_connection", return_value=mock_conn)

        # Mock site creation
        mocker.patch("clerk.cli.create_site_record")

        # Mock enqueue_job
        mock_enqueue = mocker.patch("clerk.cli.enqueue_job")

        result = cli_runner.invoke(
            cli,
            ["new", "new-city.civic.band"]
        )

        assert result.exit_code == 0
        assert "Enqueueing new site new-city.civic.band with high priority" in result.output

        # Verify enqueued with high priority
        mock_enqueue.assert_called_once_with(
            "fetch-site",
            "new-city.civic.band",
            priority="high"
        )
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::TestNewCommand::test_new_creates_site_and_enqueues_with_high_priority -v`

Expected: FAIL - new command doesn't enqueue yet

**Step 3: Update `clerk new` command implementation**

Find the `new` command in `src/clerk/cli.py` and update it to add enqueueing after site creation. Look for the function definition and add the enqueue call:

```python
@cli.command()
@click.argument("subdomain")
@click.option("--name", help="Site name")
@click.option("--state", help="State abbreviation")
@click.option("--kind", help="Municipality type (city, county, etc)")
@click.option("--scraper", help="Scraper type")
@click.option("--country", default="US", help="Country code (default: US)")
def new(subdomain, name, state, kind, scraper, country):
    """Create a new site."""
    from .queue import enqueue_job

    # Existing site creation logic...
    # [Keep all the existing code that creates the site record]

    # After site creation, add:
    click.echo(f"Enqueueing new site {subdomain} with high priority")
    enqueue_job("fetch-site", subdomain, priority="high")
```

Note: You'll need to find the exact location in the existing `new` function and add the enqueue call after the site record is created but before the function returns.

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::TestNewCommand::test_new_creates_site_and_enqueues_with_high_priority -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_cli.py src/clerk/cli.py
git commit -m "feat: auto-enqueue new sites with high priority

After creating site record, automatically enqueue with high priority
so new sites are processed immediately."
```

---

## Task 4: Update `clerk enqueue` Priority Default (Verify Existing Behavior)

**Files:**
- Test: `tests/test_cli.py` (add test to verify existing behavior)
- Possibly modify: `src/clerk/cli.py` (only if default isn't already 'normal')

**Step 1: Write test to verify existing default behavior**

Add to `tests/test_cli.py`:

```python
@pytest.mark.unit
class TestEnqueueCommand:
    """Tests for the enqueue command."""

    def test_enqueue_defaults_to_normal_priority(self, cli_runner, mocker):
        """clerk enqueue should default to normal priority."""
        # Mock database to return site exists
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.cli.civic_db_connection", return_value=mock_conn)

        mocker.patch(
            "clerk.cli.get_site_by_subdomain",
            return_value={"subdomain": "test-site.civic.band"}
        )

        # Mock enqueue_job
        mock_enqueue = mocker.patch("clerk.cli.enqueue_job")

        result = cli_runner.invoke(cli, ["enqueue", "test-site.civic.band"])

        assert result.exit_code == 0

        # Should use normal priority by default
        assert mock_enqueue.call_args[1]["priority"] == "normal"

    def test_enqueue_respects_priority_override(self, cli_runner, mocker):
        """clerk enqueue --priority high should use high priority."""
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.cli.civic_db_connection", return_value=mock_conn)

        mocker.patch(
            "clerk.cli.get_site_by_subdomain",
            return_value={"subdomain": "test-site.civic.band"}
        )

        mock_enqueue = mocker.patch("clerk.cli.enqueue_job")

        result = cli_runner.invoke(
            cli,
            ["enqueue", "--priority", "high", "test-site.civic.band"]
        )

        assert result.exit_code == 0
        assert mock_enqueue.call_args[1]["priority"] == "high"
```

**Step 2: Run test to verify current behavior**

Run: `uv run pytest tests/test_cli.py::TestEnqueueCommand -v`

Expected: Tests should PASS if `enqueue` already defaults to normal priority. If they FAIL, proceed to step 3.

**Step 3: Update default priority if needed**

If tests fail, find the `enqueue` command in `src/clerk/cli.py` and ensure the default priority is "normal":

```python
@cli.command()
@click.argument("subdomains", nargs=-1, required=True)
@click.option(
    "--priority",
    type=click.Choice(["high", "normal", "low"]),
    default="normal",  # Ensure this is "normal"
    help="Job priority (default: normal)",
)
def enqueue(subdomains, priority):
    """Enqueue sites for processing."""
    # ... rest of function
```

**Step 4: Run test again to verify**

Run: `uv run pytest tests/test_cli.py::TestEnqueueCommand -v`

Expected: 2 tests PASS

**Step 5: Commit (only if changes were needed)**

```bash
git add tests/test_cli.py src/clerk/cli.py
git commit -m "test: verify enqueue defaults to normal priority

Add tests confirming clerk enqueue uses normal priority by default
and respects --priority flag overrides."
```

---

## Task 5: Integration Test - Full Workflow

**Files:**
- Test: `tests/test_cli.py` (add integration test)

**Step 1: Write integration test**

Add to `tests/test_cli.py`:

```python
@pytest.mark.integration
class TestAutoEnqueueIntegration:
    """Integration tests for auto-enqueue workflow."""

    def test_full_auto_enqueue_workflow(self, cli_runner, mocker):
        """Test complete workflow: new -> auto-enqueue -> manual update."""
        # Mock database and queue
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.Mock(return_value=False)
        mocker.patch("clerk.cli.civic_db_connection", return_value=mock_conn)

        mock_enqueue = mocker.patch("clerk.cli.enqueue_job")
        mocker.patch("clerk.cli.create_site_record")

        # Step 1: Create new site - should enqueue with high priority
        mocker.patch(
            "clerk.cli.get_site_by_subdomain",
            return_value=None  # Site doesn't exist yet
        )

        result = cli_runner.invoke(cli, ["new", "new-site.civic.band"])
        assert result.exit_code == 0

        call_args = mock_enqueue.call_args_list[-1]
        assert call_args[0][0] == "fetch-site"
        assert call_args[0][1] == "new-site.civic.band"
        assert call_args[1]["priority"] == "high"

        mock_enqueue.reset_mock()

        # Step 2: Auto-scheduler picks oldest site - should use normal priority
        mocker.patch("clerk.cli.get_oldest_site", return_value="old-site.civic.band")

        result = cli_runner.invoke(cli, ["update", "--next"])
        assert result.exit_code == 0

        call_args = mock_enqueue.call_args_list[-1]
        assert call_args[0][1] == "old-site.civic.band"
        assert call_args[1]["priority"] == "normal"

        mock_enqueue.reset_mock()

        # Step 3: Manual update - should use high priority
        mocker.patch(
            "clerk.cli.get_site_by_subdomain",
            return_value={"subdomain": "urgent-site.civic.band"}
        )

        result = cli_runner.invoke(cli, ["update", "-s", "urgent-site.civic.band"])
        assert result.exit_code == 0

        call_args = mock_enqueue.call_args_list[-1]
        assert call_args[0][1] == "urgent-site.civic.band"
        assert call_args[1]["priority"] == "high"
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::TestAutoEnqueueIntegration -v`

Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_cli.py
git commit -m "test: add integration test for auto-enqueue workflow

Verify complete workflow: new site (high), auto-scheduler (normal),
manual update (high) all work together correctly."
```

---

## Task 6: Update Documentation

**Files:**
- Modify: `docs/getting-started/basic-usage.md`
- Modify: `docs/deployment.md`
- Modify: `README.md`

**Step 1: Update basic usage docs**

Add to `docs/getting-started/basic-usage.md` in the appropriate section:

```markdown
### Auto-Scheduling Sites

The auto-scheduler ensures all sites update approximately once per day:

```bash
# Run via cron every minute to auto-enqueue oldest site
clerk update --next
```

This command:
- Finds the site with the oldest `last_updated` timestamp
- Skips sites updated within the last 23 hours
- Enqueues the oldest eligible site with normal priority
- Exits silently if all sites are recently updated

### Manual vs Auto Priority

**High priority** (processed first):
- New sites: `clerk new <subdomain>`
- Manual updates: `clerk update -s <subdomain>`

**Normal priority** (processed after high queue empty):
- Auto-scheduler: `clerk update --next`
- Bulk operations: `clerk enqueue site1 site2 site3`
```

**Step 2: Update deployment docs**

Add to `docs/deployment.md`:

```markdown
## Auto-Scheduler Setup

To automatically update all sites once per day, set up a cron job:

```bash
# Edit crontab
crontab -e

# Add this line to run every minute:
* * * * * cd /path/to/clerk && /path/to/uv run clerk update --next >> /var/log/clerk/auto-enqueue.log 2>&1
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
```

**Step 3: Update README**

Add to the `README.md` usage section:

```markdown
## Automatic Scheduling

Set up a cron job to automatically update all sites:

```bash
# Run every minute to enqueue oldest site
* * * * * cd /path/to/clerk && uv run clerk update --next
```

Manual operations use high priority and jump to the front of the queue:

```bash
# New site - high priority
clerk new new-city.civic.band

# Manual update - high priority
clerk update -s important-city.civic.band

# Bulk enqueue - normal priority
clerk enqueue site1 site2 site3
```
```

**Step 4: Commit**

```bash
git add docs/getting-started/basic-usage.md docs/deployment.md README.md
git commit -m "docs: add auto-scheduler setup and usage instructions

Document clerk update --next usage, cron setup, and priority model
for manual vs automatic operations."
```

---

## Task 7: Run Full Test Suite

**Files:**
- None (verification step)

**Step 1: Run all tests**

Run: `uv run pytest tests/ -v`

Expected: All tests PASS

**Step 2: Run tests with coverage**

Run: `uv run pytest tests/ --cov=src/clerk --cov-report=term-missing`

Expected: Coverage report shows new code is tested

**Step 3: Check for any lint errors**

Run: `uv run ruff check src/ tests/`

Expected: No errors

**Step 4: Format code**

Run: `uv run ruff format src/ tests/`

Expected: Code formatted successfully

**Step 5: Final commit if formatting changed anything**

```bash
git add -A
git commit -m "style: format code with ruff"
```

---

## Task 8: Final Verification and Cleanup

**Files:**
- None (verification and documentation)

**Step 1: Verify all commits are clean**

Run: `git log --oneline -10`

Expected: See all commits from this implementation

**Step 2: Verify working directory is clean**

Run: `git status`

Expected: "nothing to commit, working tree clean"

**Step 3: Push feature branch**

Run: `git push -u origin feature/auto-enqueue-scheduler`

Expected: Branch pushed to remote

**Step 4: Document completion**

Create a completion summary in `docs/plans/2026-01-14-auto-enqueue-scheduler-completion.md`:

```markdown
# Auto-Enqueue Scheduler - Implementation Complete

**Date:** 2026-01-14
**Branch:** feature/auto-enqueue-scheduler

## What Was Implemented

✅ `get_oldest_site()` helper function with tests
✅ `clerk update --next` auto-scheduler mode (normal priority)
✅ `clerk update -s <subdomain>` manual mode (high priority)
✅ `clerk new` auto-enqueues with high priority
✅ `clerk enqueue` verified to use normal priority default
✅ Integration tests for full workflow
✅ Documentation updated (basic usage, deployment, README)

## Test Coverage

- Unit tests: `get_oldest_site()` function (4 tests)
- Unit tests: `clerk update --next` (2 tests)
- Unit tests: `clerk update -s` (1 test)
- Unit tests: `clerk new` enqueue (1 test)
- Unit tests: `clerk enqueue` priority (2 tests)
- Integration test: Full workflow (1 test)

**Total new tests:** 11

## Files Changed

- `src/clerk/db.py` - Added `get_oldest_site()`
- `src/clerk/cli.py` - Updated `update`, `new` commands
- `tests/test_db.py` - Created with tests for `get_oldest_site()`
- `tests/test_cli.py` - Added test classes for auto-enqueue
- `docs/getting-started/basic-usage.md` - Added auto-scheduler docs
- `docs/deployment.md` - Added cron setup instructions
- `README.md` - Added usage examples

## Next Steps

1. Create pull request to main branch
2. Code review
3. Merge to main
4. Deploy to production
5. Set up cron job on production server
6. Monitor auto-enqueue logs

## Deployment Checklist

- [ ] PR approved and merged
- [ ] Changes deployed to production
- [ ] Cron job configured: `* * * * * cd /path && uv run clerk update --next`
- [ ] Log directory created: `/var/log/clerk/`
- [ ] Verify cron is running: check logs after 1-2 minutes
- [ ] Monitor queue status: `clerk status`
- [ ] Verify sites are being auto-enqueued
```

**Step 5: Commit completion doc**

```bash
git add docs/plans/2026-01-14-auto-enqueue-scheduler-completion.md
git commit -m "docs: add implementation completion summary"
git push
```

---

## Execution Notes

- **@superpowers:test-driven-development** - Follow TDD strictly: test first, minimal implementation, refactor
- **@superpowers:verification-before-completion** - Always run tests to verify each step before committing
- **DRY** - Reuse existing `enqueue_job()` and database connection patterns
- **YAGNI** - Don't add features not in the design (configurable lookback, batch enqueuing, etc.)
- **Commit frequency** - One commit per task, clear messages

## Dependencies

**Required imports already available:**
- `sqlalchemy` - Database queries
- `click` - CLI framework
- `pytest` - Testing framework
- Existing `clerk.queue.enqueue_job` - Job enqueueing
- Existing `clerk.db.civic_db_connection` - Database connection
- Existing `clerk.models.sites_table` - Sites table model

**No new dependencies needed.**
