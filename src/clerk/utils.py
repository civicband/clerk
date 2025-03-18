import pluggy
import sqlite_utils

from .hookspecs import ClerkSpec

pm = pluggy.PluginManager("civicband.clerk")
pm.add_hookspecs(ClerkSpec)

STORAGE_DIR = "sites"


def assert_db_exists():
    db = sqlite_utils.Database("civic.db")
    if not db["sites"].exists():
        db["sites"].create(
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
            },
            pk="subdomain",
        )
    if not db["feed_entries"].exists():
        db["feed_entries"].create(
            {"subdomain": str, "date": str, "kind": str, "name": str},
        )
    db["sites"].transform(drop={"ocr_class"})
    db["sites"].transform(drop={"docker_port"})
    db["sites"].transform(drop={"save_agendas"})
    db["sites"].transform(drop={"site_db"})
    return db
