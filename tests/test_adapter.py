"""Tests for FetcherAdapter backward compatibility."""



class MockOldStyleFetcher:
    """Mock fetcher with old-style interface."""

    def __init__(self):
        self.fetch_events_called = False
        self.ocr_called = False
        self.transform_called = False

    def fetch_events(self):
        self.fetch_events_called = True

    def ocr(self):
        self.ocr_called = True

    def transform(self):
        self.transform_called = True


class TestFetcherAdapter:
    """Tests for FetcherAdapter."""

    def test_adapter_exists(self):
        """Test that FetcherAdapter can be imported."""
        from clerk.adapter import FetcherAdapter

        assert FetcherAdapter is not None

    def test_adapter_wraps_fetcher(self):
        """Test that adapter wraps an old-style fetcher."""
        from clerk.adapter import FetcherAdapter

        old_fetcher = MockOldStyleFetcher()
        adapter = FetcherAdapter(old_fetcher)

        assert adapter.fetcher is old_fetcher

    def test_extract_calls_fetch_events(self):
        """Test that extract() calls the fetcher's fetch_events()."""
        from clerk.adapter import FetcherAdapter

        old_fetcher = MockOldStyleFetcher()
        adapter = FetcherAdapter(old_fetcher)

        adapter.extract()

        assert old_fetcher.fetch_events_called

    def test_transform_calls_ocr_and_transform(self):
        """Test that transform() calls fetcher's ocr() and transform()."""
        from clerk.adapter import FetcherAdapter

        old_fetcher = MockOldStyleFetcher()
        adapter = FetcherAdapter(old_fetcher)

        adapter.transform()

        assert old_fetcher.ocr_called
        assert old_fetcher.transform_called

    def test_load_is_noop(self):
        """Test that load() is a no-op (old transform writes to DB)."""
        from clerk.adapter import FetcherAdapter

        old_fetcher = MockOldStyleFetcher()
        adapter = FetcherAdapter(old_fetcher)

        # Should not raise
        adapter.load()

    def test_full_pipeline_sequence(self):
        """Test running full ETL pipeline through adapter."""
        from clerk.adapter import FetcherAdapter

        old_fetcher = MockOldStyleFetcher()
        adapter = FetcherAdapter(old_fetcher)

        # Simulate ETL pipeline
        adapter.extract()
        adapter.transform()
        adapter.load()

        assert old_fetcher.fetch_events_called
        assert old_fetcher.ocr_called
        assert old_fetcher.transform_called
