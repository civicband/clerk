"""Tests for clerk.extract_cli module."""

from click.testing import CliRunner

from clerk.extract_cli import extract


class TestExtractCommandGroup:
    """Tests for the extract command group."""

    def test_extract_group_exists(self):
        """The extract command group should exist."""
        runner = CliRunner()
        result = runner.invoke(extract, ["--help"])
        assert result.exit_code == 0
        assert "entities" in result.output
        assert "votes" in result.output
        assert "all" in result.output

    def test_entities_subcommand_requires_subdomain_or_next_site(self):
        """entities subcommand should error without --subdomain or --next-site."""
        runner = CliRunner()
        result = runner.invoke(extract, ["entities"])
        assert result.exit_code != 0

    def test_votes_subcommand_requires_subdomain_or_next_site(self):
        """votes subcommand should error without --subdomain or --next-site."""
        runner = CliRunner()
        result = runner.invoke(extract, ["votes"])
        assert result.exit_code != 0

    def test_all_subcommand_requires_subdomain_or_next_site(self):
        """all subcommand should error without --subdomain or --next-site."""
        runner = CliRunner()
        result = runner.invoke(extract, ["all"])
        assert result.exit_code != 0
