"""Tests for clerk.extraction module."""

import importlib.util
import os

import pytest


def load_extraction_module():
    """Load extraction module directly without triggering clerk package imports.

    This avoids issues with weasyprint and other heavy dependencies in clerk/__init__.py.
    """
    spec = importlib.util.spec_from_file_location(
        "clerk.extraction",
        os.path.join(os.path.dirname(__file__), "..", "src", "clerk", "extraction.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestExtractionFeatureFlag:
    """Tests for ENABLE_EXTRACTION feature flag."""

    def test_extraction_disabled_by_default(self, monkeypatch):
        """Extraction should be disabled when env var not set."""
        monkeypatch.delenv("ENABLE_EXTRACTION", raising=False)

        extraction = load_extraction_module()
        assert extraction.EXTRACTION_ENABLED is False

    def test_extraction_enabled_when_set(self, monkeypatch):
        """Extraction should be enabled when ENABLE_EXTRACTION=1."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")

        extraction = load_extraction_module()
        assert extraction.EXTRACTION_ENABLED is True

    def test_extraction_disabled_when_zero(self, monkeypatch):
        """Extraction should be disabled when ENABLE_EXTRACTION=0."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "0")

        extraction = load_extraction_module()
        assert extraction.EXTRACTION_ENABLED is False


class TestEntityConfidenceThreshold:
    """Tests for ENTITY_CONFIDENCE_THRESHOLD configuration."""

    def test_default_confidence_threshold(self, monkeypatch):
        """Default confidence threshold should be 0.7."""
        monkeypatch.delenv("ENTITY_CONFIDENCE_THRESHOLD", raising=False)

        extraction = load_extraction_module()
        assert extraction.ENTITY_CONFIDENCE_THRESHOLD == 0.7

    def test_custom_confidence_threshold(self, monkeypatch):
        """Custom confidence threshold should be read from environment."""
        monkeypatch.setenv("ENTITY_CONFIDENCE_THRESHOLD", "0.85")

        extraction = load_extraction_module()
        assert extraction.ENTITY_CONFIDENCE_THRESHOLD == 0.85


class TestGetNlp:
    """Tests for lazy NLP model loading."""

    def test_get_nlp_returns_none_when_spacy_unavailable(self, monkeypatch):
        """get_nlp returns None when spaCy not installed."""
        import builtins

        # Simulate spacy not being installed by making import fail
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "spacy":
                raise ImportError("No module named 'spacy'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        extraction = load_extraction_module()
        result = extraction.get_nlp()
        assert result is None

    def test_get_nlp_caches_model(self):
        """get_nlp should return same instance on repeated calls."""
        extraction = load_extraction_module()

        nlp1 = extraction.get_nlp()
        nlp2 = extraction.get_nlp()

        # If spaCy is available, should be same instance
        # If not available, both should be None
        assert nlp1 is nlp2

    def test_get_nlp_logs_warning_when_spacy_unavailable(self, caplog):
        """get_nlp logs warning when spaCy not installed."""
        import logging

        # This test verifies logging behavior without crashing
        extraction = load_extraction_module()

        with caplog.at_level(logging.WARNING):
            extraction.get_nlp()  # Should not raise