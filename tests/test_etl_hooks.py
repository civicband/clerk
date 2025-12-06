"""Tests for ETL hook specifications."""

import pluggy

from clerk.hookspecs import ClerkSpec


class TestETLHookSpecs:
    """Tests for ETL-related hook specifications."""

    def test_extractor_class_hook_exists(self):
        """Test that extractor_class hookspec is defined."""
        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)

        # Should not raise - hook exists
        assert hasattr(pm.hook, "extractor_class")

    def test_transformer_class_hook_exists(self):
        """Test that transformer_class hookspec is defined."""
        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)

        assert hasattr(pm.hook, "transformer_class")

    def test_loader_class_hook_exists(self):
        """Test that loader_class hookspec is defined."""
        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)

        assert hasattr(pm.hook, "loader_class")

    def test_extractor_class_hook_callable(self):
        """Test that extractor_class hook can be called."""
        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)

        # Should return empty list when no plugins registered
        result = pm.hook.extractor_class(label="test")
        assert result == []

    def test_transformer_class_hook_callable(self):
        """Test that transformer_class hook can be called."""
        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)

        result = pm.hook.transformer_class(label="test")
        assert result == []

    def test_loader_class_hook_callable(self):
        """Test that loader_class hook can be called."""
        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)

        result = pm.hook.loader_class(label="test")
        assert result == []
