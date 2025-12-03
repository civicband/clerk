"""Tests for plugin directory discovery."""

import click
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


class TestPluginLoaderErrors:
    """Tests for error handling in plugin loader."""

    def test_fails_on_syntax_error(self, plugins_dir):
        """Test that syntax errors in plugins cause failure."""
        bad_plugin = plugins_dir / "bad_syntax.py"
        bad_plugin.write_text("def broken(\n")  # Syntax error

        with pytest.raises(click.ClickException, match="Error loading plugin"):
            load_plugins_from_directory(str(plugins_dir))

    def test_fails_on_import_error(self, plugins_dir):
        """Test that import errors in plugins cause failure."""
        bad_plugin = plugins_dir / "bad_import.py"
        bad_plugin.write_text("import nonexistent_module_12345\n")

        with pytest.raises(click.ClickException, match="Error loading plugin"):
            load_plugins_from_directory(str(plugins_dir))

    def test_fails_on_instantiation_error(self, plugins_dir):
        """Test that plugin instantiation errors cause failure."""
        bad_plugin = plugins_dir / "bad_init.py"
        bad_plugin.write_text('''
from clerk import hookimpl

class BadPlugin:
    def __init__(self):
        raise RuntimeError("Cannot instantiate")

    @hookimpl
    def fetcher_class(self, label):
        return None
''')

        with pytest.raises(click.ClickException, match="Error instantiating plugin"):
            load_plugins_from_directory(str(plugins_dir))

    def test_fails_if_path_is_file(self, tmp_path):
        """Test that passing a file path raises error."""
        file_path = tmp_path / "not_a_dir.py"
        file_path.write_text("x = 1")

        with pytest.raises(click.ClickException, match="not a directory"):
            load_plugins_from_directory(str(file_path))
