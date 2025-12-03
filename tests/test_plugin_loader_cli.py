"""Tests for CLI plugin loading integration."""

import pytest
from click.testing import CliRunner

from clerk.cli import cli


@pytest.fixture
def plugins_dir_with_plugin(tmp_path):
    """Create a plugins directory with a test plugin."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()

    plugin_code = '''
from clerk import hookimpl

class CLITestPlugin:
    @hookimpl
    def fetcher_class(self, label):
        if label == "cli_test":
            return "CLITestFetcher"
        return None
'''
    (plugins / "cli_test_plugin.py").write_text(plugin_code)
    return plugins


class TestCLIPluginLoading:
    """Tests for plugin loading via CLI."""

    def test_plugins_dir_option_exists(self):
        """Test that --plugins-dir option is available."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "--plugins-dir" in result.output

    def test_default_plugins_dir(self, tmp_path, monkeypatch):
        """Test that ./plugins/ is used by default."""
        monkeypatch.chdir(tmp_path)

        # Create default plugins directory
        plugins = tmp_path / "plugins"
        plugins.mkdir()

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        # Should not error even with empty plugins dir
        assert result.exit_code == 0

    def test_custom_plugins_dir(self, tmp_path, plugins_dir_with_plugin, monkeypatch):
        """Test loading plugins from custom directory."""
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--plugins-dir", str(plugins_dir_with_plugin), "--help"]
        )

        assert result.exit_code == 0
