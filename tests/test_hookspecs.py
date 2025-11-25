"""Integration tests for clerk.hookspecs module."""

import pluggy

from clerk.hookspecs import ClerkSpec, hookimpl


class TestPluginIntegration:
    """Integration tests for the plugin system."""

    def test_plugin_manager_with_spec(self):
        """Test creating a plugin manager with ClerkSpec."""
        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)

        # Check that hooks are registered
        assert pm.hook is not None

    def test_plugin_registration(self):
        """Test registering a plugin implementation."""
        from tests.mocks.mock_plugins import TestPlugin

        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)
        pm.register(TestPlugin())

        # Test calling a hook
        result = pm.hook.fetcher_extra(label="test_scraper")
        assert result == [{"test_key": "test_value"}]

    def test_multiple_plugins(self):
        """Test registering multiple plugins."""
        from tests.mocks.mock_plugins import NoOpPlugin, TestPlugin

        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)
        pm.register(TestPlugin())
        pm.register(NoOpPlugin())

        # Both plugins should be registered
        plugins = pm.get_plugins()
        assert len(plugins) == 2

    def test_hook_firstresult(self):
        """Test that hooks can return first non-None result."""

        class Plugin1:
            @hookimpl
            def fetcher_class(self, label):
                if label == "plugin1_scraper":
                    return "Plugin1Fetcher"
                return None

        class Plugin2:
            @hookimpl
            def fetcher_class(self, label):
                if label == "plugin2_scraper":
                    return "Plugin2Fetcher"
                return None

        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)
        pm.register(Plugin1())
        pm.register(Plugin2())

        # Each plugin should handle its own scraper
        results = pm.hook.fetcher_class(label="plugin1_scraper")
        assert "Plugin1Fetcher" in results

        results = pm.hook.fetcher_class(label="plugin2_scraper")
        assert "Plugin2Fetcher" in results
