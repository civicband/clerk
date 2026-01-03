# Datastore Plugin Hooks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace direct `db["sites"].update()` calls with plugin hooks to enable extensibility for logging, webhooks, and side effects.

**Architecture:** Add `update_site` and `create_site` hooks to pluggy hookspecs. Create `DefaultDBPlugin` that performs actual SQLite writes. Replace all direct database write calls in CLI with hook invocations.

**Tech Stack:** pluggy (existing), sqlite-utils (existing), pytest

---

## Task 1: Add Hook Specifications

**Files:**
- Modify: `src/clerk/hookspecs.py:31`

**Step 1: Write failing test for update_site hookspec**

Create: `tests/test_db_hooks.py`

```python
"""Tests for database plugin hooks."""

import sqlite_utils
from clerk.hookspecs import ClerkSpec


def test_update_site_hookspec_exists():
    """Test that update_site hookspec is defined."""
    assert hasattr(ClerkSpec, "update_site")


def test_create_site_hookspec_exists():
    """Test that create_site hookspec is defined."""
    assert hasattr(ClerkSpec, "create_site")
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_db_hooks.py::test_update_site_hookspec_exists -v
pytest tests/test_db_hooks.py::test_create_site_hookspec_exists -v
```

Expected: FAIL with "AttributeError: type object 'ClerkSpec' has no attribute 'update_site'"

**Step 3: Add hookspecs to ClerkSpec**

In `src/clerk/hookspecs.py`, add after line 30 (after `post_create`):

```python
    @hookspec
    def update_site(self, subdomain, updates):
        """Update a site record in civic.db

        Args:
            subdomain: The site subdomain (e.g., 'berkeleyca.civic.band')
            updates: Dictionary of fields to update (e.g., {'status': 'deployed'})
        """

    @hookspec
    def create_site(self, subdomain, site_data):
        """Create a new site record in civic.db

        Args:
            subdomain: The site subdomain
            site_data: Dictionary of all site fields
        """
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_db_hooks.py -v
```

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add src/clerk/hookspecs.py tests/test_db_hooks.py
git commit -m "feat: add update_site and create_site hookspecs"
```

---

## Task 2: Create Default Database Plugin

**Files:**
- Modify: `src/clerk/plugins.py:28`

**Step 1: Write test for DefaultDBPlugin.update_site**

Add to `tests/test_db_hooks.py`:

```python
import tempfile
from pathlib import Path

from clerk.plugins import DefaultDBPlugin


def test_default_plugin_update_site(tmp_path):
    """Test that DefaultDBPlugin updates site in database."""
    # Setup test database
    db_path = tmp_path / "civic.db"
    db = sqlite_utils.Database(db_path)
    db["sites"].insert({"subdomain": "test.civic.band", "status": "deployed"})

    # Simulate assert_db_exists() returning this db
    import clerk.plugins
    original_db = clerk.plugins.assert_db_exists
    clerk.plugins.assert_db_exists = lambda: db

    try:
        # Call hook
        plugin = DefaultDBPlugin()
        plugin.update_site("test.civic.band", {"status": "needs_extraction"})

        # Verify update
        site = db["sites"].get("test.civic.band")
        assert site["status"] == "needs_extraction"
    finally:
        clerk.plugins.assert_db_exists = original_db


def test_default_plugin_create_site(tmp_path):
    """Test that DefaultDBPlugin creates site in database."""
    # Setup test database
    db_path = tmp_path / "civic.db"
    db = sqlite_utils.Database(db_path)
    db["sites"].create({"subdomain": str, "status": str}, pk="subdomain")

    # Simulate assert_db_exists() returning this db
    import clerk.plugins
    original_db = clerk.plugins.assert_db_exists
    clerk.plugins.assert_db_exists = lambda: db

    try:
        # Call hook
        plugin = DefaultDBPlugin()
        plugin.create_site("new.civic.band", {"subdomain": "new.civic.band", "status": "new"})

        # Verify creation
        site = db["sites"].get("new.civic.band")
        assert site["subdomain"] == "new.civic.band"
        assert site["status"] == "new"
    finally:
        clerk.plugins.assert_db_exists = original_db
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_db_hooks.py::test_default_plugin_update_site -v
pytest tests/test_db_hooks.py::test_default_plugin_create_site -v
```

Expected: FAIL with "ImportError: cannot import name 'DefaultDBPlugin'"

**Step 3: Implement DefaultDBPlugin**

Add to `src/clerk/plugins.py` after the `DummyPlugins` class (after line 27):

```python
class DefaultDBPlugin:
    """Default plugin that handles actual database writes."""

    @hookimpl
    def update_site(self, subdomain, updates):
        """Default implementation: write to SQLite."""
        from .utils import assert_db_exists
        db = assert_db_exists()
        db["sites"].update(subdomain, updates)

    @hookimpl
    def create_site(self, subdomain, site_data):
        """Default implementation: insert into SQLite."""
        from .utils import assert_db_exists
        db = assert_db_exists()
        db["sites"].insert(site_data)
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_db_hooks.py::test_default_plugin_update_site -v
pytest tests/test_db_hooks.py::test_default_plugin_create_site -v
```

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add src/clerk/plugins.py tests/test_db_hooks.py
git commit -m "feat: add DefaultDBPlugin for database writes"
```

---

## Task 3: Auto-Register DefaultDBPlugin

**Files:**
- Modify: `src/clerk/utils.py:60`

**Step 1: Write test for auto-registration**

Add to `tests/test_db_hooks.py`:

```python
from clerk.utils import pm


def test_default_db_plugin_registered():
    """Test that DefaultDBPlugin is auto-registered."""
    # Check that update_site hook is available
    assert pm.hook.update_site
    assert pm.hook.create_site

    # Check that at least one plugin implements these hooks
    update_impls = pm.hook.update_site.get_hookimpls()
    create_impls = pm.hook.create_site.get_hookimpls()

    assert len(update_impls) > 0
    assert len(create_impls) > 0
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_db_hooks.py::test_default_db_plugin_registered -v
```

Expected: FAIL with assertion error (no implementations)

**Step 3: Auto-register DefaultDBPlugin**

In `src/clerk/utils.py`, after line 60 (after `pm.add_hookspecs(ClerkSpec)`), add:

```python
from .plugins import DefaultDBPlugin

pm.register(DefaultDBPlugin())
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_db_hooks.py::test_default_db_plugin_registered -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/utils.py tests/test_db_hooks.py
git commit -m "feat: auto-register DefaultDBPlugin on startup"
```

---

## Task 4: Replace db["sites"].insert in new command

**Files:**
- Modify: `src/clerk/cli.py:155-177`

**Step 1: Replace db["sites"].insert with hook call**

In `src/clerk/cli.py`, find the `new` command function (around line 155). Replace the `db["sites"].insert()` call:

Before (lines 155-177):
```python
    db["sites"].insert(  # pyright: ignore[reportAttributeAccessIssue]
        {
            "subdomain": subdomain,
            "name": municipality,
            "state": state,
            "country": country,
            "kind": kind,
            "scraper": scraper,
            "pages": 0,
            "start_year": start_year,
            "status": "new",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "lat": lat,
            "lng": lng,
            "extra": json.dumps(extra) if extra else "{}",
            "extraction_status": "pending",
            "last_extracted": None,
        }
    )
```

After:
```python
    pm.hook.create_site(
        subdomain=subdomain,
        site_data={
            "subdomain": subdomain,
            "name": municipality,
            "state": state,
            "country": country,
            "kind": kind,
            "scraper": scraper,
            "pages": 0,
            "start_year": start_year,
            "status": "new",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "lat": lat,
            "lng": lng,
            "extra": json.dumps(extra) if extra else "{}",
            "extraction_status": "pending",
            "last_extracted": None,
        },
    )
```

**Step 2: Remove db variable from new command**

Remove the line `db = assert_db_exists()` from the `new` function since we no longer need it directly.

**Step 3: Run existing tests**

```bash
pytest tests/test_cli.py -v -k new
```

Expected: Tests pass

**Step 4: Commit**

```bash
git add src/clerk/cli.py
git commit -m "refactor: use create_site hook in new command"
```

---

## Task 5: Replace db["sites"].update in fetch_internal

**Files:**
- Modify: `src/clerk/cli.py:319-327` and `src/clerk/cli.py:336-343`

**Step 1: Replace first update call (line 319)**

In `src/clerk/cli.py`, function `fetch_internal`, replace:

Before (lines 319-327):
```python
    db["sites"].update(  # pyright: ignore[reportAttributeAccessIssue]
        subdomain,
        {
            "status": "needs_fetch",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
```

After:
```python
    pm.hook.update_site(
        subdomain=subdomain,
        updates={
            "status": "needs_fetch",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
```

**Step 2: Replace second update call (line 336)**

In the same function, replace:

Before (lines 336-343):
```python
    db["sites"].update(  # pyright: ignore[reportAttributeAccessIssue]
        subdomain,
        {
            "status": status,
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
```

After:
```python
    pm.hook.update_site(
        subdomain=subdomain,
        updates={
            "status": status,
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
```

**Step 3: Remove db variable from fetch_internal**

Remove the line `db = assert_db_exists()` from the function (line 317).

**Step 4: Run existing tests**

```bash
pytest tests/test_cli.py -v -k fetch
```

Expected: Existing tests should still pass

**Step 5: Commit**

```bash
git add src/clerk/cli.py
git commit -m "refactor: use update_site hook in fetch_internal"
```

---

## Task 6: Replace db["sites"].update in update_site_internal

**Files:**
- Modify: `src/clerk/cli.py:260-266`, `src/clerk/cli.py:271-277`, `src/clerk/cli.py:281-290`

**Step 1: Replace first update (needs_extraction status)**

In `src/clerk/cli.py`, function `update_site_internal`, replace:

Before (lines 260-266):
```python
    db["sites"].update(  # type: ignore
        subdomain,
        {
            "status": "needs_extraction",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
```

After:
```python
    pm.hook.update_site(
        subdomain=subdomain,
        updates={
            "status": "needs_extraction",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
```

**Step 2: Replace second update (needs_deploy status)**

Replace (lines 271-277):

Before:
```python
    db["sites"].update(  # type: ignore
        subdomain,
        {
            "status": "needs_deploy",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
```

After:
```python
    pm.hook.update_site(
        subdomain=subdomain,
        updates={
            "status": "needs_deploy",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
```

**Step 3: Replace third update (deployed status)**

Replace (lines 281-290):

Before:
```python
    db["sites"].update(  # type: ignore
        subdomain,
        {
            "status": "deployed",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
```

After:
```python
    pm.hook.update_site(
        subdomain=subdomain,
        updates={
            "status": "deployed",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
```

**Step 4: Remove db variable from update_site_internal**

Remove the line `db = assert_db_exists()` from the function (line 213).

**Step 5: Commit**

```bash
git add src/clerk/cli.py
git commit -m "refactor: use update_site hook in update_site_internal"
```

---

## Task 7: Replace db["sites"].update in update_page_count

**Files:**
- Modify: `src/clerk/cli.py:472-490`

**Step 1: Replace update call**

In `src/clerk/cli.py`, function `update_page_count`, replace:

Before (lines 485-490):
```python
    db["sites"].update(  # type: ignore
        subdomain,
        {
            "pages": page_count,
        },
    )
```

After:
```python
    pm.hook.update_site(
        subdomain=subdomain,
        updates={
            "pages": page_count,
        },
    )
```

**Step 2: Keep db variable**

Note: The `db` variable is still needed in this function for the query on line 473, so we only replace the update call, not remove the variable.

**Step 3: Run existing tests**

```bash
pytest tests/test_cli.py -v -k update_page_count
```

Expected: Tests pass

**Step 4: Commit**

```bash
git add src/clerk/cli.py
git commit -m "refactor: use update_site hook in update_page_count"
```

---

## Task 8: Replace db["sites"].update in extract_entities_internal

**Files:**
- Modify: `src/clerk/cli.py:585`, `src/clerk/cli.py:593-601`, `src/clerk/cli.py:623`

**Step 1: Replace first update (in_progress status)**

In `src/clerk/cli.py`, function `extract_entities_internal`, replace:

Before (line 585):
```python
    db["sites"].update(subdomain, {"extraction_status": "in_progress"})
```

After:
```python
    pm.hook.update_site(
        subdomain=subdomain,
        updates={"extraction_status": "in_progress"},
    )
```

**Step 2: Replace second update (completed status)**

Replace (lines 593-601):

Before:
```python
        db["sites"].update(
            subdomain,
            {
                "extraction_status": "completed",
                "last_extracted": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
```

After:
```python
        pm.hook.update_site(
            subdomain=subdomain,
            updates={
                "extraction_status": "completed",
                "last_extracted": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
```

**Step 3: Replace third update (failed status)**

Replace (line 623):

Before:
```python
        db["sites"].update(subdomain, {"extraction_status": "failed"})
```

After:
```python
        pm.hook.update_site(
            subdomain=subdomain,
            updates={"extraction_status": "failed"},
        )
```

**Step 4: Keep db variable**

Note: The `db` variable is still needed for other operations in this function (like getting site data), so we only replace update calls.

**Step 5: Commit**

```bash
git add src/clerk/cli.py
git commit -m "refactor: use update_site hook in extract_entities_internal"
```

---

## Task 9: Write Integration Test for Multiple Plugins

**Files:**
- Modify: `tests/test_db_hooks.py`

**Step 1: Write test for multiple plugin execution**

Add to `tests/test_db_hooks.py`:

```python
def test_multiple_plugins_execute_sequentially():
    """Test that multiple plugins implementing hooks all execute."""
    from clerk.hookspecs import hookimpl
    from clerk.utils import pm

    call_log = []

    class TestPlugin1:
        @hookimpl
        def update_site(self, subdomain, updates):
            call_log.append(('plugin1', subdomain, updates))

    class TestPlugin2:
        @hookimpl
        def update_site(self, subdomain, updates):
            call_log.append(('plugin2', subdomain, updates))

    # Register test plugins
    plugin1 = TestPlugin1()
    plugin2 = TestPlugin2()
    pm.register(plugin1)
    pm.register(plugin2)

    try:
        # Clear call log
        call_log.clear()

        # Call hook
        pm.hook.update_site(subdomain="test.civic.band", updates={"status": "deployed"})

        # Verify all plugins were called
        assert len(call_log) >= 2  # At least our 2 test plugins

        # Verify our plugins got the right args
        plugin1_calls = [c for c in call_log if c[0] == 'plugin1']
        plugin2_calls = [c for c in call_log if c[0] == 'plugin2']

        assert len(plugin1_calls) == 1
        assert len(plugin2_calls) == 1
        assert plugin1_calls[0][1] == "test.civic.band"
        assert plugin2_calls[0][1] == "test.civic.band"
    finally:
        # Cleanup
        pm.unregister(plugin1)
        pm.unregister(plugin2)
```

**Step 2: Run test**

```bash
pytest tests/test_db_hooks.py::test_multiple_plugins_execute_sequentially -v
```

Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_db_hooks.py
git commit -m "test: verify multiple plugins execute for hooks"
```

---

## Task 10: Update Plugin Documentation

**Files:**
- Modify: `docs/plugin-development.md:505`

**Step 1: Add hook documentation**

Add to `docs/plugin-development.md` in the "Available Hooks" section (after `post_create`):

```markdown
### update_site

React to or extend site updates in civic.db.

```python
@hookimpl
def update_site(self, subdomain: str, updates: dict):
    """Called when a site is updated in civic.db.

    Args:
        subdomain: The site subdomain (e.g., 'berkeleyca.civic.band')
        updates: Dictionary of fields being updated (e.g., {'status': 'deployed'})
    """
    # Your plugin logic here
    import logfire
    logfire.info("Site updated", subdomain=subdomain, updates=updates)
```

**Use cases:**
- Log all database changes for auditing
- Send webhooks on status changes
- Invalidate caches when data changes
- Update external systems when sites are modified

**Example: Status Change Webhook**

```python
@hookimpl
def update_site(self, subdomain: str, updates: dict):
    """Send webhook when site status changes."""
    if 'status' in updates:
        import requests
        requests.post(
            "https://example.com/webhook",
            json={
                "event": "status_change",
                "subdomain": subdomain,
                "new_status": updates['status'],
            }
        )
```

### create_site

React to new site creation.

```python
@hookimpl
def create_site(self, subdomain: str, site_data: dict):
    """Called when a new site is created in civic.db.

    Args:
        subdomain: The new site subdomain
        site_data: Complete site record being created
    """
    # Your plugin logic here
    import logfire
    logfire.info("Site created", subdomain=subdomain, site_data=site_data)
```

**Use cases:**
- Log new site creation for auditing
- Initialize external resources (DNS, hosting, etc.)
- Send notifications to admins
- Set up monitoring for new sites

**Example: Setup External Resources**

```python
@hookimpl
def create_site(self, subdomain: str, site_data: dict):
    """Initialize hosting and DNS for new site."""
    # Create DNS record
    create_dns_record(subdomain)

    # Initialize hosting directory
    setup_hosting_directory(subdomain)

    # Send notification
    notify_admin(f"New site created: {subdomain}")
```
```

**Step 2: Commit**

```bash
git add docs/plugin-development.md
git commit -m "docs: add update_site and create_site hook documentation"
```

---

## Task 11: Create Example Observability Plugin

**Files:**
- Create: `examples/observability_plugin.py`

**Step 1: Create example plugin file**

```python
"""Example observability plugin for Clerk.

This plugin demonstrates how to use update_site and create_site hooks
to add logging, webhooks, and cache invalidation.
"""

import os

import logfire
import requests
from clerk import hookimpl


class ObservabilityPlugin:
    """Plugin that adds observability to database operations."""

    @hookimpl
    def update_site(self, subdomain: str, updates: dict):
        """Log updates and send webhooks for status changes."""
        # Log all updates
        logfire.info(
            "Site updated",
            subdomain=subdomain,
            fields_changed=list(updates.keys()),
            new_values=updates,
        )

        # Send webhook on status changes
        if "status" in updates:
            webhook_url = os.environ.get("CLERK_WEBHOOK_URL")
            if webhook_url:
                try:
                    requests.post(
                        webhook_url,
                        json={
                            "event": "status_change",
                            "subdomain": subdomain,
                            "new_status": updates["status"],
                            "timestamp": updates.get("last_updated"),
                        },
                        timeout=5,
                    )
                except requests.RequestException as e:
                    logfire.error("Webhook failed", error=str(e), subdomain=subdomain)

    @hookimpl
    def create_site(self, subdomain: str, site_data: dict):
        """Log new site creation and notify admins."""
        # Log creation
        logfire.info(
            "Site created",
            subdomain=subdomain,
            municipality=site_data.get("name"),
            state=site_data.get("state"),
        )

        # Send notification
        webhook_url = os.environ.get("CLERK_WEBHOOK_URL")
        if webhook_url:
            try:
                requests.post(
                    webhook_url,
                    json={
                        "event": "site_created",
                        "subdomain": subdomain,
                        "site_data": site_data,
                    },
                    timeout=5,
                )
            except requests.RequestException as e:
                logfire.error("Webhook failed", error=str(e), subdomain=subdomain)


# Auto-register if used as a standalone plugin
if __name__ != "__main__":
    from clerk.utils import pm

    pm.register(ObservabilityPlugin())
```

**Step 2: Commit**

```bash
git add examples/observability_plugin.py
git commit -m "docs: add observability plugin example"
```

---

## Task 12: Run Full Test Suite

**Files:**
- None (verification step)

**Step 1: Run all tests**

```bash
pytest tests/ -v
```

Expected: All tests pass

**Step 2: Run linter**

```bash
just lint
```

Expected: No lint errors

**Step 3: Run type checker**

```bash
just typecheck
```

Expected: No type errors (or acceptable warnings)

**Step 4: Run formatter check**

```bash
just format-check
```

Expected: All files properly formatted

**Step 5: Document completion**

All tests passing, linting clean, ready for review.

---

## Summary

This implementation:

1. ✅ Adds `update_site` and `create_site` hookspecs to `ClerkSpec`
2. ✅ Creates `DefaultDBPlugin` that performs actual SQLite writes
3. ✅ Auto-registers `DefaultDBPlugin` on clerk startup
4. ✅ Replaces all 9 direct database write calls in `cli.py` with hook invocations
5. ✅ Maintains backward compatibility (existing plugins unaffected)
6. ✅ Enables extensibility for logging, webhooks, cache invalidation, etc.
7. ✅ Includes comprehensive tests for hooks and plugins
8. ✅ Updates documentation with examples

**Next Steps:** Use @superpowers:executing-plans or @superpowers:subagent-driven-development to implement this plan.
