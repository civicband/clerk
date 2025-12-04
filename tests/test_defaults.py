"""Tests for default ETL components."""

import csv
import json
import pytest
from pathlib import Path


class TestIdentityTransformer:
    """Tests for IdentityTransformer default component."""

    def test_identity_transformer_exists(self):
        """Test that IdentityTransformer can be imported."""
        from clerk.defaults import IdentityTransformer

        assert IdentityTransformer is not None

    def test_identity_transformer_interface(self):
        """Test that IdentityTransformer has correct interface."""
        from clerk.defaults import IdentityTransformer

        site = {"subdomain": "test.civic.band"}
        config = {}

        transformer = IdentityTransformer(site, config)

        assert hasattr(transformer, "transform")
        assert callable(transformer.transform)

    def test_identity_transformer_does_nothing(self, tmp_path):
        """Test that IdentityTransformer is a no-op."""
        from clerk.defaults import IdentityTransformer

        site = {"subdomain": "test.civic.band"}
        config = {}

        transformer = IdentityTransformer(site, config)

        # Should not raise
        transformer.transform()


class TestGenericLoader:
    """Tests for GenericLoader default component."""

    def test_generic_loader_exists(self):
        """Test that GenericLoader can be imported."""
        from clerk.defaults import GenericLoader

        assert GenericLoader is not None

    def test_generic_loader_interface(self):
        """Test that GenericLoader has correct interface."""
        from clerk.defaults import GenericLoader

        site = {"subdomain": "test.civic.band"}
        config = {}

        loader = GenericLoader(site, config)

        assert hasattr(loader, "load")
        assert callable(loader.load)

    def test_generic_loader_loads_csv(self, tmp_path, monkeypatch):
        """Test that GenericLoader loads CSV files to tables."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        from clerk.defaults import GenericLoader

        subdomain = "test.civic.band"
        site = {"subdomain": subdomain}
        config = {}

        # Create transformed directory with CSV file
        transformed_dir = tmp_path / subdomain / "transformed"
        transformed_dir.mkdir(parents=True)

        csv_file = transformed_dir / "budget.csv"
        csv_file.write_text("department,amount\nParks,1000\nFire,2000\n")

        loader = GenericLoader(site, config)
        loader.load()

        # Check database was created with table
        import sqlite_utils

        db_path = tmp_path / subdomain / "data.db"
        assert db_path.exists()

        db = sqlite_utils.Database(db_path)
        assert "budget" in db.table_names()

        rows = list(db["budget"].rows)
        assert len(rows) == 2
        assert rows[0]["department"] == "Parks"

    def test_generic_loader_loads_json(self, tmp_path, monkeypatch):
        """Test that GenericLoader loads JSON files to tables."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        from clerk.defaults import GenericLoader

        subdomain = "test.civic.band"
        site = {"subdomain": subdomain}
        config = {}

        # Create transformed directory with JSON file
        transformed_dir = tmp_path / subdomain / "transformed"
        transformed_dir.mkdir(parents=True)

        json_file = transformed_dir / "items.json"
        json_file.write_text(json.dumps([
            {"name": "Item 1", "value": 100},
            {"name": "Item 2", "value": 200},
        ]))

        loader = GenericLoader(site, config)
        loader.load()

        import sqlite_utils

        db_path = tmp_path / subdomain / "data.db"
        db = sqlite_utils.Database(db_path)

        assert "items" in db.table_names()
        rows = list(db["items"].rows)
        assert len(rows) == 2

    def test_generic_loader_skips_empty_directory(self, tmp_path, monkeypatch):
        """Test that GenericLoader handles missing/empty transformed dir."""
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

        from clerk.defaults import GenericLoader

        subdomain = "test.civic.band"
        site = {"subdomain": subdomain}
        config = {}

        # Don't create transformed directory
        loader = GenericLoader(site, config)

        # Should not raise
        loader.load()
