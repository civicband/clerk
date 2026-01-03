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


def test_multiple_plugins_execute_sequentially(tmp_path, monkeypatch):
    """Test that multiple plugins implementing hooks all execute."""
    from clerk.hookspecs import hookimpl
    from clerk.utils import pm

    # Setup test database with existing site
    db_path = tmp_path / "civic.db"
    db = sqlite_utils.Database(db_path)
    db["sites"].insert({"subdomain": "test.civic.band", "status": "deployed"}, pk="subdomain")

    # Use monkeypatch to point to test database
    monkeypatch.setattr("clerk.utils.assert_db_exists", lambda: db)

    call_log = []

    class TestPlugin1:
        @hookimpl
        def update_site(self, subdomain, updates):
            call_log.append(("plugin1", subdomain, updates))

    class TestPlugin2:
        @hookimpl
        def update_site(self, subdomain, updates):
            call_log.append(("plugin2", subdomain, updates))

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
        plugin1_calls = [c for c in call_log if c[0] == "plugin1"]
        plugin2_calls = [c for c in call_log if c[0] == "plugin2"]

        assert len(plugin1_calls) == 1
        assert len(plugin2_calls) == 1
        assert plugin1_calls[0][1] == "test.civic.band"
        assert plugin2_calls[0][1] == "test.civic.band"
    finally:
        # Cleanup
        pm.unregister(plugin1)
        pm.unregister(plugin2)
