"""Custom fetcher implementation example.

This demonstrates how to create a custom fetcher for a specific data source.
"""

import time
from pathlib import Path


class BasicFetcher:
    """A basic fetcher implementation.

    This example shows the required interface for custom fetchers.
    Replace the placeholder implementations with your actual logic.
    """

    def __init__(self, site: dict, start_year: int, all_agendas: bool):
        """Initialize the fetcher.

        Args:
            site: Site configuration from civic.db
            start_year: Year to start fetching from
            all_agendas: Whether to fetch all agendas
        """
        self.site = site
        self.start_year = start_year
        self.all_agendas = all_agendas
        self.subdomain = site["subdomain"]

        # Storage paths
        import os

        storage_dir = os.environ.get("STORAGE_DIR", "../sites")
        self.base_dir = Path(storage_dir) / self.subdomain
        self.pdf_dir = self.base_dir / "pdfs"
        self.minutes_txt_dir = self.base_dir / "txt"
        self.agendas_txt_dir = self.base_dir / "_agendas" / "txt"

    def fetch_events(self):
        """Download meeting data.

        This method should:
        1. Connect to your data source (API, web scraper, etc.)
        2. Download meeting PDFs or documents
        3. Save them to self.pdf_dir
        """
        print(f"[BasicFetcher] Fetching events for {self.subdomain}")

        # Example: Fetch from an API
        # import requests
        #
        # api_url = f"https://example.com/api/meetings/{self.subdomain}"
        # response = requests.get(api_url, params={"since": self.start_year})
        # meetings = response.json()
        #
        # for meeting in meetings:
        #     pdf_url = meeting['pdf_url']
        #     pdf_path = self.pdf_dir / f"{meeting['date']}.pdf"
        #     pdf_path.parent.mkdir(parents=True, exist_ok=True)
        #
        #     pdf_data = requests.get(pdf_url).content
        #     pdf_path.write_bytes(pdf_data)

        # Placeholder implementation
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        print(f"  - Would download PDFs to {self.pdf_dir}")
        print(f"  - Starting from year {self.start_year}")
        print(f"  - Fetch agendas: {self.all_agendas}")

    def ocr(self):
        """Extract text from downloaded documents.

        This method should:
        1. Process PDFs in self.pdf_dir
        2. Extract text using OCR or PDF parsing
        3. Save text files to:
           - self.minutes_txt_dir/{meeting}/{date}/{page}.txt
           - self.agendas_txt_dir/{meeting}/{date}/{page}.txt
        """
        print(f"[BasicFetcher] Running OCR for {self.subdomain}")

        # Example: Use pdf2image and pytesseract
        # from pdf2image import convert_from_path
        # import pytesseract
        #
        # for pdf_path in self.pdf_dir.glob("*.pdf"):
        #     images = convert_from_path(pdf_path)
        #
        #     for page_num, image in enumerate(images, 1):
        #         text = pytesseract.image_to_string(image)
        #
        #         meeting_name = "City Council"
        #         date = pdf_path.stem
        #         txt_path = self.minutes_txt_dir / meeting_name / date / f"{page_num}.txt"
        #         txt_path.parent.mkdir(parents=True, exist_ok=True)
        #         txt_path.write_text(text)

        # Placeholder implementation
        self.minutes_txt_dir.mkdir(parents=True, exist_ok=True)
        print(f"  - Would extract text to {self.minutes_txt_dir}")

        if self.all_agendas:
            self.agendas_txt_dir.mkdir(parents=True, exist_ok=True)
            print(f"  - Would extract agendas to {self.agendas_txt_dir}")

    def transform(self):
        """Build database from extracted text.

        This method should:
        1. Call clerk's build_db_from_text_internal()
        2. Optionally perform additional transformations
        """
        print(f"[BasicFetcher] Transforming data for {self.subdomain}")

        # Import and call clerk's database builder
        from clerk.cli import build_db_from_text_internal

        build_db_from_text_internal(self.subdomain)

        print(f"  - Built meetings.db for {self.subdomain}")


class AdvancedFetcher(BasicFetcher):
    """An advanced fetcher with additional features.

    This demonstrates how to extend the basic fetcher with custom logic.
    """

    def __init__(self, site: dict, start_year: int, all_agendas: bool):
        """Initialize with additional configuration."""
        super().__init__(site, start_year, all_agendas)

        # Get extra configuration from plugin
        self.api_key = site.get("extra", {}).get("api_key")
        self.base_url = site.get("extra", {}).get("base_url")

    def fetch_events(self):
        """Fetch with rate limiting and retries."""

        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                print(f"[AdvancedFetcher] Attempt {attempt + 1}/{max_retries}")
                self._fetch_with_rate_limit()
                break
            except Exception as e:
                print(f"  - Error: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    raise

    def _fetch_with_rate_limit(self):
        """Fetch with rate limiting."""
        # Example: Respect API rate limits
        # import requests
        # from time import sleep
        #
        # events = self.get_events_list()
        #
        # for i, event in enumerate(events):
        #     if i > 0 and i % 10 == 0:
        #         sleep(1)  # Rate limit: 10 requests per second
        #
        #     self.download_event(event)

        print("  - Fetching with rate limiting")

    def ocr(self):
        """OCR with parallel processing."""
        # Example: Use multiprocessing for faster OCR
        # from multiprocessing import Pool
        #
        # pdf_files = list(self.pdf_dir.glob("*.pdf"))
        #
        # with Pool(processes=4) as pool:
        #     pool.map(self.process_pdf, pdf_files)

        print("  - Running parallel OCR")
        super().ocr()

    def transform(self):
        """Transform with validation."""
        print("  - Validating data before transform")

        # Example: Validate text files exist
        # if not any(self.minutes_txt_dir.rglob("*.txt")):
        #     raise ValueError("No text files found")

        super().transform()

        # Example: Post-transform validation
        # self.validate_database()

    def validate_database(self):
        """Validate the built database."""
        # Example: Check database integrity
        # import sqlite_utils
        #
        # db_path = self.base_dir / "meetings.db"
        # db = sqlite_utils.Database(db_path)
        #
        # minutes_count = db["minutes"].count
        # if minutes_count == 0:
        #     raise ValueError("No minutes in database")

        print("  - Database validation passed")


if __name__ == "__main__":
    # Example usage
    sample_site = {
        "subdomain": "example.civic.band",
        "name": "Example City",
        "scraper": "basic_scraper",
        "start_year": 2020,
        "extra": {"api_key": "xxx", "base_url": "https://api.example.com"},
    }

    # Test basic fetcher
    print("=== Basic Fetcher ===")
    basic = BasicFetcher(sample_site, start_year=2020, all_agendas=False)
    basic.fetch_events()
    basic.ocr()
    basic.transform()

    print("\n=== Advanced Fetcher ===")
    advanced = AdvancedFetcher(sample_site, start_year=2020, all_agendas=True)
    advanced.fetch_events()
    advanced.ocr()
    advanced.transform()
