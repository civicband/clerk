"""Tests for database plugin hooks."""

import sqlite_utils

from clerk.hookspecs import ClerkSpec


def test_update_site_hookspec_exists():
    """Test that update_site hookspec is defined."""
    assert hasattr(ClerkSpec, "update_site")


def test_create_site_hookspec_exists():
    """Test that create_site hookspec is defined."""
    assert hasattr(ClerkSpec, "create_site")


def test_default_plugin_update_site(tmp_path, monkeypatch):
    """Test that DefaultDBPlugin updates site in database."""
    # Setup test database
    db_path = tmp_path / "civic.db"
    db = sqlite_utils.Database(db_path)
    db["sites"].insert({"subdomain": "test.civic.band", "status": "deployed"}, pk="subdomain")

    # Use monkeypatch instead of direct assignment
    monkeypatch.setattr("clerk.utils.assert_db_exists", lambda: db)

    # Call hook
    from clerk.plugins import DefaultDBPlugin
    plugin = DefaultDBPlugin()
    plugin.update_site("test.civic.band", {"status": "needs_extraction"})

    # Verify update
    site = db["sites"].get("test.civic.band")
    assert site["status"] == "needs_extraction"


def test_default_plugin_create_site(tmp_path, monkeypatch):
    """Test that DefaultDBPlugin creates site in database."""
    # Setup test database
    db_path = tmp_path / "civic.db"
    db = sqlite_utils.Database(db_path)
    db["sites"].create({"subdomain": str, "status": str}, pk="subdomain")

    # Use monkeypatch instead of direct assignment
    monkeypatch.setattr("clerk.utils.assert_db_exists", lambda: db)

    # Call hook
    from clerk.plugins import DefaultDBPlugin
    plugin = DefaultDBPlugin()
    plugin.create_site("new.civic.band", {"subdomain": "new.civic.band", "status": "new"})

    # Verify creation
    site = db["sites"].get("new.civic.band")
    assert site["subdomain"] == "new.civic.band"
    assert site["status"] == "new"


def test_default_db_plugin_registered():
    """Test that DefaultDBPlugin is auto-registered."""
    from clerk.utils import pm

    # Check that update_site hook is available
    assert pm.hook.update_site
    assert pm.hook.create_site

    # Check that at least one plugin implements these hooks
    update_impls = pm.hook.update_site.get_hookimpls()
    create_impls = pm.hook.create_site.get_hookimpls()

    assert len(update_impls) > 0
    assert len(create_impls) > 0
