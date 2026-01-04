"""Tests for plugin system."""

from clerk.hookspecs import hookimpl
from clerk.utils import pm


def test_multiple_plugins_execute_sequentially():
    """Test that multiple plugins implementing hooks all execute."""
    call_log = []

    class TestPlugin1:
        @hookimpl
        def post_create(self, subdomain):
            call_log.append(("plugin1", subdomain))

    class TestPlugin2:
        @hookimpl
        def post_create(self, subdomain):
            call_log.append(("plugin2", subdomain))

    # Register test plugins
    plugin1 = TestPlugin1()
    plugin2 = TestPlugin2()
    pm.register(plugin1)
    pm.register(plugin2)

    try:
        # Clear call log
        call_log.clear()

        # Call hook
        pm.hook.post_create(subdomain="test.civic.band")

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
