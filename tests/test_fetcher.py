"""Tests for the Fetcher base class."""

import pytest


class TestFetcherImport:
    """Test that Fetcher can be imported."""

    def test_import_fetcher_from_package(self):
        """Fetcher should be importable from clerk package."""
        from clerk import Fetcher

        assert Fetcher is not None

    def test_import_fetcher_from_module(self):
        """Fetcher should be importable from fetcher module."""
        from clerk.fetcher import Fetcher

        assert Fetcher is not None


class TestFetcherPDFGuard:
    """Test PDF dependency guards."""

    def test_pdf_support_flag_exists(self):
        """PDF_SUPPORT flag should exist."""
        from clerk.fetcher import PDF_SUPPORT

        assert isinstance(PDF_SUPPORT, bool)


class TestFetcherContract:
    """Test the Fetcher base class contract."""

    def test_fetch_events_raises_not_implemented(self, tmp_path, monkeypatch):
        """Base Fetcher.fetch_events() should raise NotImplementedError."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        from clerk.fetcher import Fetcher

        # Create required directories
        site_dir = tmp_path / "test-site"
        site_dir.mkdir()
        for subdir in ["_docs/pdfs", "_docs/processed", "_docs/html"]:
            (site_dir / subdir).mkdir(parents=True)

        site = {
            "subdomain": "test-site",
            "start_year": 2020,
            "pages": 0,
        }

        fetcher = Fetcher(site)

        with pytest.raises(NotImplementedError, match="Subclasses must implement"):
            fetcher.fetch_events()


class TestFetcherCheckIfExists:
    """Test the check_if_exists method."""

    def test_returns_false_when_no_files_exist(self, tmp_path, monkeypatch):
        """check_if_exists returns False when no matching files exist."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        from clerk.fetcher import Fetcher

        # Create required directories
        site_dir = tmp_path / "test-site"
        site_dir.mkdir()
        for subdir in ["_docs/pdfs", "_docs/processed", "_docs/html", "pdfs", "processed"]:
            (site_dir / subdir).mkdir(parents=True)

        site = {
            "subdomain": "test-site",
            "start_year": 2020,
            "pages": 0,
        }

        fetcher = Fetcher(site)

        result = fetcher.check_if_exists("CityCouncil", "2024-01-15", "minutes")
        assert result is False

    def test_returns_true_when_pdf_exists(self, tmp_path, monkeypatch):
        """check_if_exists returns True when PDF exists in output dir."""
        import sys

        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        # Reload modules to pick up the new STORAGE_DIR
        if "clerk.utils" in sys.modules:
            import importlib

            importlib.reload(sys.modules["clerk.utils"])
        if "clerk.fetcher" in sys.modules:
            import importlib

            importlib.reload(sys.modules["clerk.fetcher"])

        from clerk.fetcher import Fetcher

        # Create required directories
        site_dir = tmp_path / "test-site"
        site_dir.mkdir()
        for subdir in [
            "_docs/pdfs",
            "_docs/processed",
            "_docs/html",
            "pdfs/CityCouncil",
            "processed",
        ]:
            (site_dir / subdir).mkdir(parents=True)

        # Create the PDF file
        (site_dir / "pdfs" / "CityCouncil" / "2024-01-15.pdf").write_bytes(b"fake pdf")

        site = {
            "subdomain": "test-site",
            "start_year": 2020,
            "pages": 0,
        }

        fetcher = Fetcher(site)

        result = fetcher.check_if_exists("CityCouncil", "2024-01-15", "minutes")
        assert result is True


class TestFetcherSimplifiedMeetingName:
    """Test the simplified_meeting_name method."""

    def test_removes_spaces(self, tmp_path, monkeypatch):
        """simplified_meeting_name removes spaces."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        from clerk.fetcher import Fetcher

        # Create required directories
        site_dir = tmp_path / "test-site"
        site_dir.mkdir()
        for subdir in ["_docs/pdfs", "_docs/processed", "_docs/html"]:
            (site_dir / subdir).mkdir(parents=True)

        site = {
            "subdomain": "test-site",
            "start_year": 2020,
            "pages": 0,
        }

        fetcher = Fetcher(site)

        result = fetcher.simplified_meeting_name("City Council")
        assert result == "CityCouncil"

    def test_replaces_special_chars(self, tmp_path, monkeypatch):
        """simplified_meeting_name replaces special characters."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        from clerk.fetcher import Fetcher

        # Create required directories
        site_dir = tmp_path / "test-site"
        site_dir.mkdir()
        for subdir in ["_docs/pdfs", "_docs/processed", "_docs/html"]:
            (site_dir / subdir).mkdir(parents=True)

        site = {
            "subdomain": "test-site",
            "start_year": 2020,
            "pages": 0,
        }

        fetcher = Fetcher(site)

        result = fetcher.simplified_meeting_name("Parks & Recreation")
        assert result == "ParksAndRecreation"
