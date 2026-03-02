"""Tests for clerk.extract_cli module."""

import json
from unittest.mock import MagicMock, patch

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


class TestRunExtraction:
    """Tests for the extraction orchestration logic."""

    def test_run_extraction_entities_only_creates_cache(self, tmp_path):
        """Extracting entities only should cache entities, leave votes empty."""
        from clerk.extract_cli import _run_extraction_for_site

        meeting_dir = tmp_path / "txt" / "city-council" / "2024-01-15"
        meeting_dir.mkdir(parents=True)
        (meeting_dir / "0001.txt").write_text("Mayor Smith called the meeting to order.")

        with patch("clerk.extract_cli.EXTRACTION_ENABLED", True), \
             patch("clerk.extract_cli._extract_entities") as mock_extract, \
             patch("clerk.extract_cli.get_nlp") as mock_nlp:
            mock_nlp.return_value = MagicMock()
            mock_nlp.return_value.pipe = MagicMock(return_value=[MagicMock()])
            mock_extract.return_value = {"persons": [{"name": "Smith"}], "orgs": [], "locations": []}

            _run_extraction_for_site(
                subdomain="test-site",
                txt_dir=str(tmp_path / "txt"),
                mode="entities",
                rebuild=False,
            )

        cache_file = meeting_dir / "0001.txt.extracted.json"
        assert cache_file.exists()
        cache_data = json.loads(cache_file.read_text())
        assert "entities" in cache_data
        assert cache_data["entities"]["persons"][0]["name"] == "Smith"

    def test_run_extraction_votes_only_creates_cache(self, tmp_path):
        """Extracting votes only should cache votes, leave entities empty."""
        from clerk.extract_cli import _run_extraction_for_site

        meeting_dir = tmp_path / "txt" / "city-council" / "2024-01-15"
        meeting_dir.mkdir(parents=True)
        (meeting_dir / "0001.txt").write_text("Motion passed 5-2.")

        with patch("clerk.extract_cli.EXTRACTION_ENABLED", True), \
             patch("clerk.extract_cli._extract_votes") as mock_votes, \
             patch("clerk.extract_cli.get_nlp") as mock_nlp:
            mock_nlp.return_value = MagicMock()
            mock_nlp.return_value.pipe = MagicMock(return_value=[MagicMock()])
            mock_votes.return_value = {"votes": [{"result": "passed", "tally": {"ayes": 5, "nays": 2}}]}

            _run_extraction_for_site(
                subdomain="test-site",
                txt_dir=str(tmp_path / "txt"),
                mode="votes",
                rebuild=False,
            )

        cache_file = meeting_dir / "0001.txt.extracted.json"
        assert cache_file.exists()
        cache_data = json.loads(cache_file.read_text())
        assert "votes" in cache_data
        assert cache_data["votes"]["votes"][0]["result"] == "passed"

    def test_run_extraction_rebuild_ignores_existing_cache(self, tmp_path):
        """--rebuild should ignore existing cache and re-extract."""
        from clerk.extract_cli import _run_extraction_for_site

        meeting_dir = tmp_path / "txt" / "city-council" / "2024-01-15"
        meeting_dir.mkdir(parents=True)
        text = "Mayor Smith called the meeting to order."
        (meeting_dir / "0001.txt").write_text(text)

        from clerk.utils import hash_text_content
        cache_file = meeting_dir / "0001.txt.extracted.json"
        cache_file.write_text(json.dumps({
            "content_hash": hash_text_content(text),
            "entities": {"persons": [{"name": "Old"}], "orgs": [], "locations": []},
            "votes": {"votes": []},
        }))

        with patch("clerk.extract_cli.EXTRACTION_ENABLED", True), \
             patch("clerk.extract_cli._extract_entities") as mock_extract, \
             patch("clerk.extract_cli.get_nlp") as mock_nlp:
            mock_nlp.return_value = MagicMock()
            mock_nlp.return_value.pipe = MagicMock(return_value=[MagicMock()])
            mock_extract.return_value = {"persons": [{"name": "New"}], "orgs": [], "locations": []}

            _run_extraction_for_site(
                subdomain="test-site",
                txt_dir=str(tmp_path / "txt"),
                mode="entities",
                rebuild=True,
            )

        cache_data = json.loads(cache_file.read_text())
        assert cache_data["entities"]["persons"][0]["name"] == "New"

    def test_run_extraction_preserves_other_section_on_rebuild(self, tmp_path):
        """Rebuilding entities should preserve existing votes in cache."""
        from clerk.extract_cli import _run_extraction_for_site

        meeting_dir = tmp_path / "txt" / "city-council" / "2024-01-15"
        meeting_dir.mkdir(parents=True)
        text = "Mayor Smith called the meeting to order."
        (meeting_dir / "0001.txt").write_text(text)

        from clerk.utils import hash_text_content
        cache_file = meeting_dir / "0001.txt.extracted.json"
        cache_file.write_text(json.dumps({
            "content_hash": hash_text_content(text),
            "entities": {"persons": [], "orgs": [], "locations": []},
            "votes": {"votes": [{"result": "passed"}]},
        }))

        with patch("clerk.extract_cli.EXTRACTION_ENABLED", True), \
             patch("clerk.extract_cli._extract_entities") as mock_extract, \
             patch("clerk.extract_cli.get_nlp") as mock_nlp:
            mock_nlp.return_value = MagicMock()
            mock_nlp.return_value.pipe = MagicMock(return_value=[MagicMock()])
            mock_extract.return_value = {"persons": [{"name": "Smith"}], "orgs": [], "locations": []}

            _run_extraction_for_site(
                subdomain="test-site",
                txt_dir=str(tmp_path / "txt"),
                mode="entities",
                rebuild=True,
            )

        cache_data = json.loads(cache_file.read_text())
        # Entities should be updated
        assert cache_data["entities"]["persons"][0]["name"] == "Smith"
        # Votes should be preserved from existing cache
        assert cache_data["votes"]["votes"][0]["result"] == "passed"
