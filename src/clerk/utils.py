import os

import logfire
import pluggy
import sqlite_utils

from .hookspecs import ClerkSpec

pm = pluggy.PluginManager("civicband.clerk")
pm.add_hookspecs(ClerkSpec)

STORAGE_DIR = os.environ.get("STORAGE_DIR", "../sites")


@logfire.instrument("assert_db_exists")
def assert_db_exists():
    db = sqlite_utils.Database("civic.db")
    if not db["sites"].exists():
        db["sites"].create(  # pyright: ignore[reportAttributeAccessIssue]
            {
                "subdomain": str,
                "name": str,
                "state": str,
                "country": str,
                "kind": str,
                "scraper": str,
                "pages": int,
                "start_year": int,
                "extra": str,
                "status": str,
                "last_updated": str,
                "lat": str,
                "lng": str,
                "pipeline": str,  # JSON column for ETL pipeline config
            },
            pk="subdomain",
        )
    if not db["feed_entries"].exists():
        db["feed_entries"].create(  # pyright: ignore[reportAttributeAccessIssue]
            {"subdomain": str, "date": str, "kind": str, "name": str},
        )
    # Drop deprecated columns
    db["sites"].transform(drop={"ocr_class"})  # pyright: ignore[reportAttributeAccessIssue]
    db["sites"].transform(drop={"docker_port"})  # pyright: ignore[reportAttributeAccessIssue]
    db["sites"].transform(drop={"save_agendas"})  # pyright: ignore[reportAttributeAccessIssue]
    db["sites"].transform(drop={"site_db"})  # pyright: ignore[reportAttributeAccessIssue]

    # Add pipeline column if it doesn't exist (migration for existing DBs)
    columns = {col.name for col in db["sites"].columns}
    if "pipeline" not in columns:
        db.execute("ALTER TABLE sites ADD COLUMN pipeline TEXT")

    return db
