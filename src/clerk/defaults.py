"""Default ETL components for clerk."""

import csv
import json
import os
from pathlib import Path

import sqlite_utils

STORAGE_DIR = os.environ.get("STORAGE_DIR", "../sites")


class IdentityTransformer:
    """Default transformer that passes data through unchanged.

    Use this when extracted data is already in the desired format
    and no transformation is needed.
    """

    def __init__(self, site: dict, config: dict):
        """Initialize the transformer.

        Args:
            site: Site configuration dictionary.
            config: Additional configuration from site's extra field.
        """
        self.site = site
        self.config = config

    def transform(self) -> None:
        """No-op transformation - data passes through unchanged."""
        pass


class GenericLoader:
    """Default loader that creates tables from CSV/JSON files.

    Reads files from the transformed/ directory and creates
    database tables based on filename (e.g., budget.csv -> budget table).
    """

    def __init__(self, site: dict, config: dict):
        """Initialize the loader.

        Args:
            site: Site configuration dictionary.
            config: Additional configuration from site's extra field.
        """
        self.site = site
        self.config = config
        self.storage_dir = os.environ.get("STORAGE_DIR", STORAGE_DIR)

    def load(self) -> None:
        """Load all CSV/JSON files from transformed/ directory to database."""
        subdomain = self.site["subdomain"]
        transformed_dir = Path(self.storage_dir) / subdomain / "transformed"

        if not transformed_dir.exists():
            return

        db_path = Path(self.storage_dir) / subdomain / "data.db"
        db = sqlite_utils.Database(db_path)

        # Process CSV files
        for csv_file in transformed_dir.glob("*.csv"):
            table_name = csv_file.stem
            with open(csv_file) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                if rows:
                    db[table_name].insert_all(rows, alter=True)

        # Process JSON files
        for json_file in transformed_dir.glob("*.json"):
            table_name = json_file.stem
            with open(json_file) as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    db[table_name].insert_all(data, alter=True)
