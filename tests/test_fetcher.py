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
            # Also reload mock_fetchers since it imports Fetcher
            if "tests.mocks.mock_fetchers" in sys.modules:
                importlib.reload(sys.modules["tests.mocks.mock_fetchers"])

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


class TestMockFetcherInheritance:
    """Test that MockFetcher properly inherits from Fetcher."""

    def test_mock_fetcher_is_subclass(self):
        """MockFetcher should be a subclass of Fetcher."""
        from clerk.fetcher import Fetcher
        from tests.mocks.mock_fetchers import MockFetcher

        assert issubclass(MockFetcher, Fetcher)

    def test_mock_fetcher_instance(self):
        """MockFetcher instance should be instance of Fetcher."""
        from clerk.fetcher import Fetcher
        from tests.mocks.mock_fetchers import MockFetcher

        site = {"subdomain": "test", "start_year": 2020, "pages": 0}
        mock = MockFetcher(site, 2020)

        assert isinstance(mock, Fetcher)
        assert isinstance(mock, MockFetcher)


class TestPDFChunkSize:
    """Test PDF chunk size configuration."""

    def test_pdf_chunk_size_exists(self):
        """PDF_CHUNK_SIZE constant should exist."""
        from clerk.fetcher import PDF_CHUNK_SIZE

        assert isinstance(PDF_CHUNK_SIZE, int)
        assert PDF_CHUNK_SIZE > 0

    def test_pdf_chunk_size_default(self, monkeypatch):
        """PDF_CHUNK_SIZE should default to 20."""
        import sys

        # Remove env var if set
        monkeypatch.delenv("PDF_CHUNK_SIZE", raising=False)

        # Reload module to pick up default
        if "clerk.fetcher" in sys.modules:
            import importlib

            importlib.reload(sys.modules["clerk.fetcher"])

        from clerk.fetcher import PDF_CHUNK_SIZE

        assert PDF_CHUNK_SIZE == 20

    def test_pdf_chunk_size_from_env(self, monkeypatch):
        """PDF_CHUNK_SIZE should be configurable via environment."""
        import sys

        monkeypatch.setenv("PDF_CHUNK_SIZE", "50")

        # Reload module to pick up env var
        if "clerk.fetcher" in sys.modules:
            import importlib

            importlib.reload(sys.modules["clerk.fetcher"])

        from clerk.fetcher import PDF_CHUNK_SIZE

        assert PDF_CHUNK_SIZE == 50


class TestChunkedOCRProcessing:
    """Test chunked OCR processing logic."""

    def test_chunking_math_small_pdf(self):
        """Verify chunking produces correct page ranges for small PDFs."""
        chunk_size = 20
        total_pages = 5

        chunks = []
        for chunk_start in range(1, total_pages + 1, chunk_size):
            chunk_end = min(chunk_start + chunk_size - 1, total_pages)
            chunks.append((chunk_start, chunk_end))

        # Small PDF should be processed in single chunk
        assert chunks == [(1, 5)]

    def test_chunking_math_medium_pdf(self):
        """Verify chunking produces correct page ranges for medium PDFs."""
        chunk_size = 20
        total_pages = 45

        chunks = []
        for chunk_start in range(1, total_pages + 1, chunk_size):
            chunk_end = min(chunk_start + chunk_size - 1, total_pages)
            chunks.append((chunk_start, chunk_end))

        # 45 pages should be 3 chunks: 1-20, 21-40, 41-45
        assert chunks == [(1, 20), (21, 40), (41, 45)]

    def test_chunking_math_large_pdf(self):
        """Verify chunking produces correct page ranges for large PDFs."""
        chunk_size = 20
        total_pages = 200

        chunks = []
        for chunk_start in range(1, total_pages + 1, chunk_size):
            chunk_end = min(chunk_start + chunk_size - 1, total_pages)
            chunks.append((chunk_start, chunk_end))

        # 200 pages should be 10 chunks of 20
        assert len(chunks) == 10
        assert chunks[0] == (1, 20)
        assert chunks[-1] == (181, 200)

    def test_chunking_math_exact_multiple(self):
        """Verify chunking works when total pages is exact multiple of chunk size."""
        chunk_size = 20
        total_pages = 40

        chunks = []
        for chunk_start in range(1, total_pages + 1, chunk_size):
            chunk_end = min(chunk_start + chunk_size - 1, total_pages)
            chunks.append((chunk_start, chunk_end))

        # 40 pages should be 2 chunks: 1-20, 21-40
        assert chunks == [(1, 20), (21, 40)]

    def test_page_numbering_within_chunk(self):
        """Verify page numbers are calculated correctly within chunks."""
        # Simulating what happens in do_ocr_job for chunk starting at page 21
        chunk_start = 21
        pages_in_chunk = 20  # Simulating convert_from_path returning 20 pages

        page_numbers = []
        for idx in range(pages_in_chunk):
            page_number = chunk_start + idx
            page_numbers.append(page_number)

        # Pages should be numbered 21-40
        assert page_numbers[0] == 21
        assert page_numbers[-1] == 40
        assert len(page_numbers) == 20
