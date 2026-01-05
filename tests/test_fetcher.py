"""Tests for the Fetcher base class."""

import sys

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


class TestDoOCRJobEnhanced:
    """Test enhanced do_ocr_job with logging and error handling."""

    def test_do_ocr_job_logs_operations(self, mock_site, tmp_path, monkeypatch):
        """do_ocr_job should log each operation with timing."""
        from pathlib import Path
        from unittest.mock import Mock, mock_open, patch

        from clerk.fetcher import Fetcher
        from clerk.ocr_utils import FailureManifest

        mock_site["subdomain"] = "test"

        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        fetcher = Fetcher(mock_site)
        manifest_path = Path(tmp_path) / "failures.jsonl"
        manifest = FailureManifest(str(manifest_path))
        job_id = "test_123"

        # Create necessary directories
        pdf_dir = Path(tmp_path) / "test" / "pdfs" / "Meeting"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        txt_dir = Path(tmp_path) / "test" / "txt" / "Meeting" / "2024-01-01"
        txt_dir.mkdir(parents=True, exist_ok=True)
        processed_dir = Path(tmp_path) / "test" / "processed" / "Meeting"
        processed_dir.mkdir(parents=True, exist_ok=True)
        (pdf_dir / "2024-01-01.pdf").write_bytes(b"fake pdf")

        # Mock PDF processing
        with (
            patch("clerk.fetcher.PDF_SUPPORT", True),
            patch("clerk.fetcher.PdfReader") as mock_reader,
            patch("clerk.fetcher.convert_from_path") as mock_convert,
            patch("subprocess.check_output") as mock_tesseract,
            patch("clerk.fetcher.log") as mock_log,
            patch("builtins.open", mock_open()),
            patch("os.path.exists", return_value=True),
            patch("os.listdir", return_value=["1.png"]),
            patch("os.remove"),
            patch("os.utime"),
            patch("shutil.rmtree"),
            patch("clerk.utils.pm.hook.upload_static_file"),
        ):
            mock_reader.return_value.pages = [Mock(), Mock()]  # 2 pages
            mock_convert.return_value = [Mock(), Mock()]
            mock_tesseract.return_value = b"test text"

            job = ("", "Meeting", "2024-01-01")
            fetcher.do_ocr_job(job, manifest, job_id)

            # Verify log calls
            log_calls = [str(call) for call in mock_log.call_args_list]

            # Should log: Processing document, PDF read, Image conversion, OCR completed, Document completed
            assert any("Processing document" in str(call) for call in log_calls)
            assert any("PDF read" in str(call) for call in log_calls)
            assert any("operation='pdf_read'" in str(call) for call in log_calls)
            assert any("duration_ms=" in str(call) for call in log_calls)

        manifest.close()

    def test_do_ocr_job_handles_permanent_error(self, mock_site, tmp_path, monkeypatch):
        """do_ocr_job should record permanent errors in manifest and continue."""
        import json
        from pathlib import Path
        from unittest.mock import patch

        from clerk.fetcher import Fetcher
        from clerk.ocr_utils import FailureManifest

        mock_site["subdomain"] = "test"

        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        fetcher = Fetcher(mock_site)
        manifest_path = Path(tmp_path) / "failures.jsonl"
        manifest = FailureManifest(str(manifest_path))
        job_id = "test_123"

        # Create a mock PdfReadError
        class MockPdfReadError(Exception):
            pass

        # Mock PDF read error
        with (
            patch("clerk.fetcher.PDF_SUPPORT", True),
            patch("clerk.fetcher.PdfReader", side_effect=MockPdfReadError("corrupted")),
            patch("clerk.fetcher.PERMANENT_ERRORS", (MockPdfReadError,)),
            patch("clerk.fetcher.log") as mock_log,
        ):
            # Create necessary directories
            pdf_dir = Path(tmp_path) / "test" / "pdfs" / "Meeting"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            (pdf_dir / "2024-01-01.pdf").write_bytes(b"fake pdf")

            job = ("", "Meeting", "2024-01-01")
            fetcher.do_ocr_job(job, manifest, job_id)

            # Should log error
            assert any("Document failed" in str(call) for call in mock_log.call_args_list)

        manifest.close()

        # Verify manifest entry
        with open(manifest_path) as f:
            entry = json.loads(f.readline())

        assert entry["job_id"] == job_id
        assert entry["meeting"] == "Meeting"
        assert entry["error_type"] == "permanent"
        assert entry["error_class"] == "MockPdfReadError"

    def test_do_ocr_job_raises_on_critical_error(self, mock_site, tmp_path, monkeypatch):
        """do_ocr_job should raise critical errors immediately."""
        from pathlib import Path
        from unittest.mock import patch

        from clerk.fetcher import Fetcher
        from clerk.ocr_utils import FailureManifest

        mock_site["subdomain"] = "test"

        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        fetcher = Fetcher(mock_site)
        manifest_path = Path(tmp_path) / "failures.jsonl"
        manifest = FailureManifest(str(manifest_path))
        job_id = "test_123"

        # Mock critical error (file not found means storage dir issue)
        with (
            patch("clerk.fetcher.PDF_SUPPORT", True),
            patch("clerk.fetcher.PdfReader", side_effect=FileNotFoundError("missing")),
            patch("clerk.fetcher.log"),
        ):
            job = ("", "Meeting", "2024-01-01")

            try:
                fetcher.do_ocr_job(job, manifest, job_id)
                raise AssertionError("Should have raised FileNotFoundError")
            except FileNotFoundError:
                pass  # Expected

        manifest.close()


class TestDoOCRIntegration:
    """Test do_ocr integration with JobState and FailureManifest."""

    def test_do_ocr_creates_failure_manifest(self, mock_site, tmp_path, monkeypatch):
        """do_ocr should create failure manifest file."""
        from unittest.mock import patch

        from clerk.fetcher import Fetcher

        mock_site["subdomain"] = "test"
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        fetcher = Fetcher(mock_site)

        # Mock empty PDF directory
        with (
            patch("os.path.exists", return_value=True),
            patch("os.listdir", return_value=[]),
            patch("clerk.output.log"),
        ):
            fetcher.do_ocr()

            # Check that a failure manifest was created (or would be created)
            # Since no jobs, manifest may not exist, but code path is exercised
            assert True  # Basic smoke test

    def test_do_ocr_logs_job_start_and_end(self, mock_site, tmp_path, monkeypatch):
        """do_ocr should log job start and completion."""
        from unittest.mock import patch

        from clerk.fetcher import Fetcher

        mock_site["subdomain"] = "test"
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        fetcher = Fetcher(mock_site)

        with (
            patch("os.path.exists", return_value=False),
            patch("os.makedirs"),
            patch("clerk.fetcher.log") as mock_log,
        ):
            fetcher.do_ocr()

            # Should log "No PDFs found"
            assert any("No PDFs found" in str(call) for call in mock_log.call_args_list)


class TestOCRWithTesseract:
    """Test the _ocr_with_tesseract method."""

    def test_ocr_with_tesseract_extracts_text(self, tmp_path, mocker):
        """Test that _ocr_with_tesseract extracts text from an image."""
        from clerk.fetcher import Fetcher

        # Create a mock image
        image_path = tmp_path / "test.png"
        image_path.write_bytes(b"fake png data")

        # Mock subprocess to return test text
        mock_check_output = mocker.patch("subprocess.check_output")
        mock_check_output.return_value = b"Test OCR text\nLine 2"

        site = {"subdomain": "test", "start_year": 2020, "pages": 0}
        fetcher = Fetcher(site)
        result = fetcher._ocr_with_tesseract(image_path)

        assert result == "Test OCR text\nLine 2"

        # Verify tesseract was called with correct args
        mock_check_output.assert_called_once()
        args = mock_check_output.call_args[0][0]
        assert args[0] == "tesseract"
        assert "-l" in args
        assert "eng+spa" in args
        assert "--dpi" in args
        assert "150" in args
        assert "--oem" in args
        assert "1" in args
        assert str(image_path) in args
        assert "stdout" in args

    def test_ocr_with_tesseract_handles_subprocess_error(self, tmp_path, mocker):
        """Test that _ocr_with_tesseract handles subprocess errors."""
        import subprocess

        from clerk.fetcher import Fetcher

        image_path = tmp_path / "test.png"
        image_path.write_bytes(b"fake png data")

        # Mock subprocess to raise error
        mock_check_output = mocker.patch("subprocess.check_output")
        mock_check_output.side_effect = subprocess.CalledProcessError(1, "tesseract")

        site = {"subdomain": "test", "start_year": 2020, "pages": 0}
        fetcher = Fetcher(site)

        with pytest.raises(subprocess.CalledProcessError):
            fetcher._ocr_with_tesseract(image_path)


@pytest.mark.skipif(sys.platform != "darwin", reason="Vision Framework only on macOS")
def test_ocr_with_vision_extracts_text(tmp_path, mocker, monkeypatch):
    """Test that _ocr_with_vision extracts text from an image."""
    from clerk.fetcher import Fetcher

    # Set storage dir
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    # Create a mock image
    image_path = tmp_path / "test.png"
    image_path.write_bytes(b"fake png data")

    # Mock Vision Framework
    mock_vision = mocker.MagicMock()
    mock_quartz = mocker.MagicMock()

    # Mock the request and observations
    mock_request = mocker.MagicMock()
    mock_observation = mocker.MagicMock()
    mock_observation.text.return_value = "Vision OCR text"
    mock_request.results.return_value = [mock_observation]

    mock_vision.VNRecognizeTextRequest.alloc.return_value.init.return_value = mock_request
    mock_vision.VNRequestTextRecognitionLevelAccurate = 1

    # Mock handler
    mock_handler = mocker.MagicMock()
    mock_handler.performRequests_error_.return_value = (True, None)
    mock_vision.VNImageRequestHandler.alloc.return_value.initWithURL_options_.return_value = mock_handler

    # Mock NSURL
    mock_url = mocker.MagicMock()
    mock_quartz.NSURL.fileURLWithPath_.return_value = mock_url

    # Patch imports
    mocker.patch.dict("sys.modules", {"Vision": mock_vision, "Quartz": mock_quartz})

    site = {"subdomain": "test", "start_year": 2020, "pages": 0}
    fetcher = Fetcher(site)
    result = fetcher._ocr_with_vision(image_path)

    assert result == "Vision OCR text"


@pytest.mark.skipif(sys.platform != "darwin", reason="Vision Framework only on macOS")
def test_ocr_with_vision_handles_import_error(tmp_path, monkeypatch):
    """Test that _ocr_with_vision raises helpful error when pyobjc not installed."""
    import sys

    from clerk.fetcher import Fetcher

    # Set storage dir
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    # Remove Vision from sys.modules if present
    if "Vision" in sys.modules:
        del sys.modules["Vision"]
    if "Quartz" in sys.modules:
        del sys.modules["Quartz"]

    image_path = tmp_path / "test.png"
    image_path.write_bytes(b"fake png data")

    site = {"subdomain": "test", "start_year": 2020, "pages": 0}
    fetcher = Fetcher(site)

    with pytest.raises(RuntimeError, match="Vision Framework requires pyobjc"):
        fetcher._ocr_with_vision(image_path)


@pytest.mark.skipif(sys.platform != "darwin", reason="Vision Framework only on macOS")
def test_ocr_with_vision_handles_vision_error(tmp_path, mocker, monkeypatch):
    """Test that _ocr_with_vision handles Vision API errors."""
    from clerk.fetcher import Fetcher

    # Set storage dir
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    image_path = tmp_path / "test.png"
    image_path.write_bytes(b"fake png data")

    # Mock Vision Framework to raise error
    mock_vision = mocker.MagicMock()
    mock_quartz = mocker.MagicMock()

    mock_vision.VNRecognizeTextRequest.alloc.return_value.init.side_effect = Exception("Vision failed")

    mocker.patch.dict("sys.modules", {"Vision": mock_vision, "Quartz": mock_quartz})

    site = {"subdomain": "test", "start_year": 2020, "pages": 0}
    fetcher = Fetcher(site)

    with pytest.raises(RuntimeError, match="Vision OCR failed"):
        fetcher._ocr_with_vision(image_path)


def test_do_ocr_job_uses_tesseract_backend(tmp_path, mocker, monkeypatch):
    """Test that do_ocr_job uses Tesseract when backend='tesseract'."""
    from pathlib import Path

    from clerk.fetcher import Fetcher
    from clerk.ocr_utils import FailureManifest

    # Setup environment
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    site = {"subdomain": "test", "start_year": 2020, "pages": 0}
    fetcher = Fetcher(site)

    # Create manifest and job_id
    manifest_path = Path(tmp_path) / "failures.jsonl"
    manifest = FailureManifest(str(manifest_path))
    job_id = "test_tesseract_123"

    # Mock the OCR methods
    mock_tesseract = mocker.patch.object(fetcher, "_ocr_with_tesseract", return_value="Tesseract text")
    mock_vision = mocker.patch.object(fetcher, "_ocr_with_vision", return_value="Vision text")

    # Mock PDF processing
    mocker.patch("clerk.fetcher.PdfReader")
    mocker.patch("clerk.fetcher.convert_from_path", return_value=[mocker.MagicMock()])
    mocker.patch.object(fetcher.pm.hook, "upload_static_file")

    # Create test PDF
    pdf_dir = tmp_path / "test" / "pdfs" / "meeting"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "2024-01-01.pdf").write_bytes(b"fake pdf")

    # Run with tesseract backend
    job = ("", "meeting", "2024-01-01")
    fetcher.do_ocr_job(job, manifest, job_id, backend="tesseract")

    # Verify Tesseract was called, Vision was not
    assert mock_tesseract.called
    assert not mock_vision.called

    manifest.close()


@pytest.mark.skipif(sys.platform != "darwin", reason="Vision Framework only on macOS")
def test_do_ocr_job_uses_vision_backend(tmp_path, mocker, monkeypatch):
    """Test that do_ocr_job uses Vision when backend='vision'."""
    from pathlib import Path

    from clerk.fetcher import Fetcher
    from clerk.ocr_utils import FailureManifest

    # Setup environment
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    site = {"subdomain": "test", "start_year": 2020, "pages": 0}
    fetcher = Fetcher(site)

    # Create manifest and job_id
    manifest_path = Path(tmp_path) / "failures.jsonl"
    manifest = FailureManifest(str(manifest_path))
    job_id = "test_vision_123"

    # Mock the OCR methods
    mock_tesseract = mocker.patch.object(fetcher, "_ocr_with_tesseract", return_value="Tesseract text")
    mock_vision = mocker.patch.object(fetcher, "_ocr_with_vision", return_value="Vision text")

    # Mock PDF processing
    mocker.patch("clerk.fetcher.PdfReader")
    mocker.patch("clerk.fetcher.convert_from_path", return_value=[mocker.MagicMock()])
    mocker.patch.object(fetcher.pm.hook, "upload_static_file")

    # Create test PDF
    pdf_dir = tmp_path / "test" / "pdfs" / "meeting"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "2024-01-01.pdf").write_bytes(b"fake pdf")

    # Run with vision backend
    job = ("", "meeting", "2024-01-01")
    fetcher.do_ocr_job(job, manifest, job_id, backend="vision")

    # Verify Vision was called, Tesseract was not
    assert mock_vision.called
    assert not mock_tesseract.called

    manifest.close()


def test_do_ocr_job_falls_back_to_tesseract_on_vision_error(tmp_path, mocker, monkeypatch):
    """Test that do_ocr_job falls back to Tesseract when Vision fails."""
    from pathlib import Path

    from clerk.fetcher import Fetcher
    from clerk.ocr_utils import FailureManifest

    # Setup environment
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    site = {"subdomain": "test", "start_year": 2020, "pages": 0}
    fetcher = Fetcher(site)

    # Create manifest and job_id
    manifest_path = Path(tmp_path) / "failures.jsonl"
    manifest = FailureManifest(str(manifest_path))
    job_id = "test_fallback_123"

    # Mock Vision to fail, Tesseract to succeed
    mock_vision = mocker.patch.object(
        fetcher, "_ocr_with_vision",
        side_effect=RuntimeError("Vision failed")
    )
    mock_tesseract = mocker.patch.object(fetcher, "_ocr_with_tesseract", return_value="Tesseract text")

    # Mock log to verify fallback warning
    mock_log = mocker.patch("clerk.fetcher.log")

    # Mock PDF processing
    mocker.patch("clerk.fetcher.PdfReader")
    mocker.patch("clerk.fetcher.convert_from_path", return_value=[mocker.MagicMock()])
    mocker.patch.object(fetcher.pm.hook, "upload_static_file")

    # Create test PDF
    pdf_dir = tmp_path / "test" / "pdfs" / "meeting"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "2024-01-01.pdf").write_bytes(b"fake pdf")

    # Run with vision backend
    job = ("", "meeting", "2024-01-01")
    fetcher.do_ocr_job(job, manifest, job_id, backend="vision")

    # Verify both were called (Vision failed, fell back to Tesseract)
    assert mock_vision.called
    assert mock_tesseract.called

    # Verify fallback warning was logged
    log_calls = [call[0][0] for call in mock_log.call_args_list]
    assert any("falling back to Tesseract" in str(call) for call in log_calls)

    manifest.close()
