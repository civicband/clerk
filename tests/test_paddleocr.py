"""Tests for the PaddleOCR backend."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from clerk.fetcher import _ocr_with_paddleocr


class TestPaddleOCRBackend:
    """Test the PaddleOCR OCR backend."""

    def test_import_error_when_paddleocr_missing(self):
        """Should raise ImportError when paddleocr is not installed."""
        # Simulate missing paddleocr by patching the import to fail
        with patch.dict("sys.modules", {"paddleocr": None}):
            with tempfile.TemporaryDirectory() as tmpdir:
                dummy_image = Path(tmpdir) / "test.png"
                dummy_image.touch()

                with pytest.raises(ImportError, match="PaddleOCR backend requires"):
                    _ocr_with_paddleocr(dummy_image)

    def test_paddleocr_success(self):
        """Should extract text from image using PaddleOCR."""
        # Mock the PaddleOCR class and its ocr method
        mock_ocr_instance = Mock()
        # Simulate PaddleOCR result format: [[box, (text, confidence)], ...]
        mock_ocr_instance.ocr.return_value = [
            [
                [[0, 0], [100, 0], [100, 50], [0, 50]],  # box coordinates
                ("Hello World", 0.95),  # (text, confidence)
            ],
            [
                [[0, 60], [100, 60], [100, 110], [0, 110]],
                ("Second Line", 0.92),
            ],
        ]

        mock_paddleocr_class = Mock(return_value=mock_ocr_instance)

        with patch("clerk.fetcher.PaddleOCR", mock_paddleocr_class):
            with tempfile.TemporaryDirectory() as tmpdir:
                dummy_image = Path(tmpdir) / "test.png"
                dummy_image.touch()

                result = _ocr_with_paddleocr(dummy_image)

        assert result == "Hello World\nSecond Line"
        mock_paddleocr_class.assert_called_once_with(
            use_angle_cls=True, lang="en", use_gpu=False, show_log=False
        )
        mock_ocr_instance.ocr.assert_called_once_with(str(dummy_image), cls=True)

    def test_paddleocr_empty_result(self):
        """Should return empty string when no text is detected."""
        mock_ocr_instance = Mock()
        mock_ocr_instance.ocr.return_value = None  # No text detected

        mock_paddleocr_class = Mock(return_value=mock_ocr_instance)

        with patch("clerk.fetcher.PaddleOCR", mock_paddleocr_class):
            with tempfile.TemporaryDirectory() as tmpdir:
                dummy_image = Path(tmpdir) / "test.png"
                dummy_image.touch()

                result = _ocr_with_paddleocr(dummy_image)

        assert result == ""

    def test_paddleocr_runtime_error(self):
        """Should raise RuntimeError when PaddleOCR processing fails."""
        mock_ocr_instance = Mock()
        mock_ocr_instance.ocr.side_effect = Exception("OCR engine crashed")

        mock_paddleocr_class = Mock(return_value=mock_ocr_instance)

        with patch("clerk.fetcher.PaddleOCR", mock_paddleocr_class):
            with tempfile.TemporaryDirectory() as tmpdir:
                dummy_image = Path(tmpdir) / "test.png"
                dummy_image.touch()

                with pytest.raises(RuntimeError, match="PaddleOCR processing failed"):
                    _ocr_with_paddleocr(dummy_image)
