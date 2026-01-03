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
