"""Tests for the PaddleOCR backend."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from clerk.fetcher import _ocr_with_paddleocr


class TestPaddleOCRBackend:
    """Test the PaddleOCR OCR backend."""

    def test_paddleocr_success(self):
        """Should extract text from image using PaddleOCR."""
        mock_ocr_instance = Mock()
        # PaddleOCR returns: [detections_for_image_1, detections_for_image_2, ...]
        # Each detection is: [box_coordinates, (text, confidence)]
        # We pass one image, so result has 1 element.
        mock_ocr_instance.ocr.return_value = [
            [  # result[0]: List of detections for the first image
                [  # Detection 1
                    [[0, 0], [100, 0], [100, 50], [0, 50]],  # box
                    ("Hello World", 0.95),  # (text, confidence)
                ],
                [  # Detection 2
                    [[0, 60], [100, 60], [100, 110], [0, 110]],
                    ("Second Line", 0.92),
                ],
            ]
        ]

        mock_paddleocr_class = Mock(return_value=mock_ocr_instance)
        mock_paddleocr_module = Mock()
        mock_paddleocr_module.PaddleOCR = mock_paddleocr_class

        with patch.dict("sys.modules", {"paddleocr": mock_paddleocr_module}):
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
        # PaddleOCR returns None or an empty list when no text is found
        mock_ocr_instance.ocr.return_value = None

        mock_paddleocr_class = Mock(return_value=mock_ocr_instance)
        mock_paddleocr_module = Mock()
        mock_paddleocr_module.PaddleOCR = mock_paddleocr_class

        with patch.dict("sys.modules", {"paddleocr": mock_paddleocr_module}):
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
        mock_paddleocr_module = Mock()
        mock_paddleocr_module.PaddleOCR = mock_paddleocr_class

        with patch.dict("sys.modules", {"paddleocr": mock_paddleocr_module}):
            with tempfile.TemporaryDirectory() as tmpdir:
                dummy_image = Path(tmpdir) / "test.png"
                dummy_image.touch()

                with pytest.raises(RuntimeError, match="PaddleOCR processing failed"):
                    _ocr_with_paddleocr(dummy_image)

    def test_paddleocr_import_error(self):
        """Should raise ImportError when paddleocr is not installed."""
        with patch.dict("sys.modules", {"paddleocr": None}):
            with tempfile.TemporaryDirectory() as tmpdir:
                dummy_image = Path(tmpdir) / "test.png"
                dummy_image.touch()

                with pytest.raises(ImportError, match="PaddleOCR backend requires"):
                    _ocr_with_paddleocr(dummy_image)
