import sqlite_utils

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
                "ocr_class": str,
            },
            pk="subdomain",
        )
    if not db["feed_entries"].exists():
        db["feed_entries"].create(
            {"subdomain": str, "date": str, "kind": str, "name": str},
        )
    if "country" not in db["sites"].columns_dict:
        db["sites"].add_column("country", str)
    if "status" not in db["sites"].columns_dict:
        db["sites"].add_column("status", str)
    if "last_updated" not in db["sites"].columns_dict:
        db["sites"].add_column("last_updated", str)
    if "ocr_class" not in db["sites"].columns_dict:
        db["sites"].add_column("ocr_class", str)
    if "last_deployed" not in db["sites"].columns_dict:
        db["sites"].add_column("last_deployed", str)
    db["sites"].transform(drop={"processing"})
    if "site_db" not in db["sites"].columns_dict:
        db["sites"].add_column("site_db", str, not_null_default="civic_minutes.db")
    db["sites"].transform(drop={"umami_id"})
    if "lat" not in db["sites"].columns_dict:
        db["sites"].add_column("lat", str)
    if "lng" not in db["sites"].columns_dict:
        db["sites"].add_column("lng", str)
    return db
