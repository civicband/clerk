import json
import logging
import os
import shutil
import time
from hashlib import sha256

import click
import pluggy
import sqlite_utils

from .hookspecs import ClerkSpec

logger = logging.getLogger(__name__)

pm = pluggy.PluginManager("civicband.clerk")
pm.add_hookspecs(ClerkSpec)

STORAGE_DIR = os.environ.get("STORAGE_DIR", "../sites")


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
            },
            pk="subdomain",
        )
    if not db["feed_entries"].exists():
        db["feed_entries"].create(  # pyright: ignore[reportAttributeAccessIssue]
            {"subdomain": str, "date": str, "kind": str, "name": str},
        )

    # Only drop deprecated columns if they still exist
    # Running transform unconditionally creates orphan tables on failure
    existing_columns = {col.name for col in db["sites"].columns}
    deprecated_columns = {"ocr_class", "docker_port", "save_agendas", "site_db"}
    columns_to_drop = existing_columns & deprecated_columns

    if columns_to_drop:
        db["sites"].transform(drop=columns_to_drop)  # pyright: ignore[reportAttributeAccessIssue]

    return db


def build_table_from_text(subdomain, txt_dir, db, table_name, municipality=None):
    logger.info(
        "Building table from text subdomain=%s table_name=%s municipality=%s",
        subdomain,
        table_name,
        municipality,
    )
    directories = [
        directory for directory in sorted(os.listdir(txt_dir)) if directory != ".DS_Store"
    ]
    for meeting in directories:
        click.echo(click.style(subdomain, fg="cyan") + ": " + f"Processing {meeting}")
        meeting_dates = [
            meeting_date
            for meeting_date in sorted(os.listdir(f"{txt_dir}/{meeting}"))
            if meeting_date != ".DS_Store"
        ]
        entries = []
        for meeting_date in meeting_dates:
            for page in os.listdir(f"{txt_dir}/{meeting}/{meeting_date}"):
                if not page.endswith(".txt"):
                    continue
                key_hash = {"kind": "minutes"}
                page_file_path = f"{txt_dir}/{meeting}/{meeting_date}/{page}"
                with open(page_file_path) as page_file:
                    page_image_path = f"/{meeting}/{meeting_date}/{page.split('.')[0]}.png"
                    if table_name == "agendas":
                        key_hash["kind"] = "agenda"
                        page_image_path = (
                            f"/_agendas/{meeting}/{meeting_date}/{page.split('.')[0]}.png"
                        )
                    text = page_file.read()
                    page_number = int(page.split(".")[0])
                    key_hash.update(
                        {
                            "meeting": meeting,
                            "date": meeting_date,
                            "page": page_number,
                            "text": text,
                        }
                    )
                    if municipality:
                        key_hash.update({"subdomain": subdomain, "municipality": municipality})
                    key = sha256(json.dumps(key_hash, sort_keys=True).encode("utf-8")).hexdigest()
                    key = key[:12]
                    key_hash.update(
                        {
                            "id": key,
                            "text": text,
                            "page_image": page_image_path,
                        }
                    )
                    del key_hash["kind"]
                    entries.append(key_hash)
        db[table_name].insert_all(entries)


def build_db_from_text_internal(subdomain):
    st = time.time()
    logger.info("Building database from text subdomain=%s", subdomain)
    minutes_txt_dir = f"{STORAGE_DIR}/{subdomain}/txt"
    agendas_txt_dir = f"{STORAGE_DIR}/{subdomain}/_agendas/txt"
    database = f"{STORAGE_DIR}/{subdomain}/meetings.db"
    db_backup = f"{STORAGE_DIR}/{subdomain}/meetings.db.bk"
    shutil.copy(database, db_backup)
    os.remove(database)
    db = sqlite_utils.Database(database)
    db["minutes"].create(
        {
            "id": str,
            "meeting": str,
            "date": str,
            "page": int,
            "text": str,
            "page_image": str,
        },
        pk=("id"),
    )
    db["agendas"].create(
        {
            "id": str,
            "meeting": str,
            "date": str,
            "page": int,
            "text": str,
            "page_image": str,
        },
        pk=("id"),
    )
    if os.path.exists(minutes_txt_dir):
        build_table_from_text(subdomain, minutes_txt_dir, db, "minutes")
    if os.path.exists(agendas_txt_dir):
        build_table_from_text(subdomain, agendas_txt_dir, db, "agendas")
    et = time.time()
    elapsed_time = et - st
    logger.info("Database build completed subdomain=%s elapsed_time=%.2f", subdomain, elapsed_time)
    click.echo(f"Execution time: {elapsed_time} seconds")
