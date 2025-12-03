"""Tests for plugin directory discovery."""

import pytest

from clerk.plugin_loader import load_plugins_from_directory
from clerk.utils import pm


@pytest.fixture
def plugins_dir(tmp_path):
    """Create a temporary plugins directory with test plugins."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    return plugins


@pytest.fixture
def sample_plugin_file(plugins_dir):
    """Create a sample plugin file."""
    plugin_code = '''
from clerk import hookimpl

class SamplePlugin:
    @hookimpl
    def fetcher_class(self, label):
        if label == "sample":
            return "SampleFetcher"
        return None
'''
    plugin_file = plugins_dir / "sample_plugin.py"
    plugin_file.write_text(plugin_code)
    return plugin_file


class TestLoadPluginsFromDirectory:
    """Tests for load_plugins_from_directory function."""

    def test_loads_plugin_from_directory(self, plugins_dir, sample_plugin_file):
        """Test that plugins are loaded from directory."""
        # Get initial plugin count
        initial_count = len(pm.get_plugins())

        # Load plugins
        load_plugins_from_directory(str(plugins_dir))

        # Should have one more plugin registered
        assert len(pm.get_plugins()) == initial_count + 1

    def test_skips_nonexistent_directory(self):
        """Test that missing directory is handled gracefully."""
        # Should not raise
        load_plugins_from_directory("/nonexistent/path")

    def test_skips_non_plugin_files(self, plugins_dir):
        """Test that files without hookimpl methods are skipped."""
        # Create a file without any plugins
        non_plugin = plugins_dir / "not_a_plugin.py"
        non_plugin.write_text("x = 1\n")

        initial_count = len(pm.get_plugins())
        load_plugins_from_directory(str(plugins_dir))

        # No new plugins should be registered
        assert len(pm.get_plugins()) == initial_count

    def test_skips_dunder_files(self, plugins_dir):
        """Test that __init__.py and similar are skipped."""
        init_file = plugins_dir / "__init__.py"
        init_file.write_text("# init file\n")

        initial_count = len(pm.get_plugins())
        load_plugins_from_directory(str(plugins_dir))

        assert len(pm.get_plugins()) == initial_count
