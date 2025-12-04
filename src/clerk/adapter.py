"""Adapter for backward compatibility with old-style fetchers."""


class FetcherAdapter:
    """Adapts old-style fetchers to the new ETL interface.

    Old fetchers implement:
        - fetch_events() - download data
        - ocr() - extract text from documents
        - transform() - build database

    This adapter maps them to the new ETL interface:
        - extract() -> fetch_events()
        - transform() -> ocr() + transform()
        - load() -> no-op (old transform() writes to DB)
    """

    def __init__(self, fetcher):
        """Initialize the adapter.

        Args:
            fetcher: An old-style fetcher instance with fetch_events(),
                     ocr(), and transform() methods.
        """
        self.fetcher = fetcher

    def extract(self) -> None:
        """Extract data by calling the fetcher's fetch_events()."""
        self.fetcher.fetch_events()

    def transform(self) -> None:
        """Transform data by calling fetcher's ocr() and transform()."""
        self.fetcher.ocr()
        self.fetcher.transform()

    def load(self) -> None:
        """No-op - old-style transform() already writes to database."""
        pass
