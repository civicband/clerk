import json
import logging
import os
import shutil
import time
from hashlib import sha256

import click
import pluggy
import sqlite_utils

from .extraction import (
    create_meeting_context,
    detect_roll_call,
    extract_entities,
    extract_votes,
    parse_texts_batch,
    update_context,
)
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
            # Create fresh context for each meeting date
            meeting_context = create_meeting_context()

            # Sort pages to ensure context accumulates in order
            pages = sorted(os.listdir(f"{txt_dir}/{meeting}/{meeting_date}"))

            # Collect all page data first for batch processing
            page_data = []
            for page in pages:
                if not page.endswith(".txt"):
                    continue
                page_file_path = f"{txt_dir}/{meeting}/{meeting_date}/{page}"
                with open(page_file_path) as page_file:
                    text = page_file.read()
                    page_number = int(page.split(".")[0])
                    page_image_path = f"/{meeting}/{meeting_date}/{page.split('.')[0]}.png"
                    if table_name == "agendas":
                        page_image_path = (
                            f"/_agendas/{meeting}/{meeting_date}/{page.split('.')[0]}.png"
                        )
                    page_data.append(
                        {
                            "text": text,
                            "page_number": page_number,
                            "page_image_path": page_image_path,
                            "page_file_path": page_file_path,
                        }
                    )

            # Batch parse all texts for this meeting date
            texts = [p["text"] for p in page_data]
            docs = parse_texts_batch(texts)

            # Now process each page with its pre-parsed doc
            for i, pdata in enumerate(page_data):
                text = pdata["text"]
                doc = docs[i]
                page_number = pdata["page_number"]
                page_image_path = pdata["page_image_path"]
                page_file_path = pdata["page_file_path"]

                key_hash = {"kind": "minutes" if table_name != "agendas" else "agenda"}

                # Extract entities and update context
                try:
                    entities = extract_entities(text, doc=doc)
                    update_context(meeting_context, entities=entities)
                except Exception as e:
                    logger.warning(f"Entity extraction failed for {page_file_path}: {e}")
                    entities = {"persons": [], "orgs": [], "locations": []}

                # Detect roll call and update context
                try:
                    attendees = detect_roll_call(text)
                    if attendees:
                        update_context(meeting_context, attendees=attendees)
                except Exception as e:
                    logger.warning(f"Roll call detection failed for {page_file_path}: {e}")

                # Extract votes with context
                try:
                    votes = extract_votes(text, doc=doc, meeting_context=meeting_context)
                except Exception as e:
                    logger.warning(f"Vote extraction failed for {page_file_path}: {e}")
                    votes = {"votes": []}

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
                        "entities_json": json.dumps(entities),
                        "votes_json": json.dumps(votes),
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
            "entities_json": str,
            "votes_json": str,
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
            "entities_json": str,
            "votes_json": str,
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
