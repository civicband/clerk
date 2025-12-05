"""Tests for ETL pipeline orchestration."""

import json

import pluggy
import pytest

from clerk.hookspecs import ClerkSpec, hookimpl


class MockExtractor:
    def __init__(self, site, config):
        self.site = site

    def extract(self):
        pass


class MockTransformer:
    def __init__(self, site, config):
        self.site = site

    def transform(self):
        pass


class MockLoader:
    def __init__(self, site, config):
        self.site = site

    def load(self):
        pass


class MockETLPlugin:
    @hookimpl
    def extractor_class(self, label):
        if label == "mock_extractor":
            return MockExtractor
        return None

    @hookimpl
    def transformer_class(self, label):
        if label == "mock_transformer":
            return MockTransformer
        return None

    @hookimpl
    def loader_class(self, label):
        if label == "mock_loader":
            return MockLoader
        return None


@pytest.fixture
def etl_plugin_manager():
    """Create a plugin manager with mock ETL plugin."""
    pm = pluggy.PluginManager("civicband.clerk")
    pm.add_hookspecs(ClerkSpec)
    pm.register(MockETLPlugin())
    return pm


class TestLookupFunctions:
    """Tests for ETL component lookup functions."""

    def test_lookup_extractor_found(self, etl_plugin_manager, monkeypatch):
        """Test looking up an extractor that exists."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        result = pipeline.lookup_extractor("mock_extractor")
        assert result is MockExtractor

    def test_lookup_extractor_not_found(self, etl_plugin_manager, monkeypatch):
        """Test looking up an extractor that doesn't exist."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        result = pipeline.lookup_extractor("nonexistent")
        assert result is None

    def test_lookup_transformer_found(self, etl_plugin_manager, monkeypatch):
        """Test looking up a transformer that exists."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        result = pipeline.lookup_transformer("mock_transformer")
        assert result is MockTransformer

    def test_lookup_transformer_not_found(self, etl_plugin_manager, monkeypatch):
        """Test looking up a transformer that doesn't exist."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        result = pipeline.lookup_transformer("nonexistent")
        assert result is None

    def test_lookup_loader_found(self, etl_plugin_manager, monkeypatch):
        """Test looking up a loader that exists."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        result = pipeline.lookup_loader("mock_loader")
        assert result is MockLoader

    def test_lookup_loader_not_found(self, etl_plugin_manager, monkeypatch):
        """Test looking up a loader that doesn't exist."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        result = pipeline.lookup_loader("nonexistent")
        assert result is None


class TestGetPipelineComponents:
    """Tests for get_pipeline_components function."""

    def test_returns_components_from_pipeline_json(self, etl_plugin_manager, monkeypatch):
        """Test getting components from pipeline JSON."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        site = {
            "subdomain": "test.civic.band",
            "pipeline": json.dumps({
                "extractor": "mock_extractor",
                "transformer": "mock_transformer",
                "loader": "mock_loader",
            }),
        }

        components = pipeline.get_pipeline_components(site)

        assert components["extractor"] is MockExtractor
        assert components["transformer"] is MockTransformer
        assert components["loader"] is MockLoader

    def test_uses_defaults_for_missing_components(self, etl_plugin_manager, monkeypatch):
        """Test that defaults are used when components not specified."""
        from clerk import pipeline
        from clerk.defaults import GenericLoader, IdentityTransformer

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        site = {
            "subdomain": "test.civic.band",
            "pipeline": json.dumps({
                "extractor": "mock_extractor",
                # transformer and loader not specified
            }),
        }

        components = pipeline.get_pipeline_components(site)

        assert components["extractor"] is MockExtractor
        assert components["transformer"] is IdentityTransformer
        assert components["loader"] is GenericLoader

    def test_raises_if_extractor_not_found(self, etl_plugin_manager, monkeypatch):
        """Test that error is raised if extractor not found."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        site = {
            "subdomain": "test.civic.band",
            "pipeline": json.dumps({
                "extractor": "nonexistent",
            }),
        }

        with pytest.raises(ValueError, match="Extractor 'nonexistent' not found"):
            pipeline.get_pipeline_components(site)

    def test_returns_adapter_for_scraper_only(self, etl_plugin_manager, monkeypatch):
        """Test that FetcherAdapter is returned for scraper-only sites."""
        from clerk import pipeline
        from clerk.adapter import FetcherAdapter

        # Create a mock old-style fetcher
        class MockOldFetcher:
            def __init__(self, site, start_year, all_agendas):
                pass

            def fetch_events(self):
                pass

            def ocr(self):
                pass

            def transform(self):
                pass

        class OldStylePlugin:
            @hookimpl
            def fetcher_class(self, label):
                if label == "old_scraper":
                    return MockOldFetcher
                return None

        pm = pluggy.PluginManager("civicband.clerk")
        pm.add_hookspecs(ClerkSpec)
        pm.register(OldStylePlugin())
        monkeypatch.setattr(pipeline, "pm", pm)

        site = {
            "subdomain": "test.civic.band",
            "scraper": "old_scraper",
            "start_year": 2020,
            "last_updated": None,
            # No pipeline field
        }

        result = pipeline.get_pipeline_components(site)

        assert isinstance(result, FetcherAdapter)

    def test_raises_if_no_pipeline_or_scraper(self, etl_plugin_manager, monkeypatch):
        """Test error when site has neither pipeline nor scraper."""
        from clerk import pipeline

        monkeypatch.setattr(pipeline, "pm", etl_plugin_manager)

        site = {
            "subdomain": "test.civic.band",
            # No pipeline, no scraper
        }

        with pytest.raises(ValueError, match="must have pipeline or scraper"):
            pipeline.get_pipeline_components(site)
