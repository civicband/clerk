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
    EXTRACTION_ENABLED,
    create_meeting_context,
    detect_roll_call,
    extract_entities,
    extract_votes,
    get_nlp,
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

    # Phase 1: Collect ALL page data across all meetings and dates
    # This enables a single large batch parse instead of many small ones
    all_page_data = []
    meeting_date_boundaries = []  # Track where each meeting date starts/ends

    for meeting in directories:
        meeting_dates = [
            meeting_date
            for meeting_date in sorted(os.listdir(f"{txt_dir}/{meeting}"))
            if meeting_date != ".DS_Store"
        ]
        for meeting_date in meeting_dates:
            start_idx = len(all_page_data)
            pages = sorted(os.listdir(f"{txt_dir}/{meeting}/{meeting_date}"))

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
                    all_page_data.append(
                        {
                            "text": text,
                            "page_number": page_number,
                            "page_image_path": page_image_path,
                            "page_file_path": page_file_path,
                            "meeting": meeting,
                            "meeting_date": meeting_date,
                        }
                    )

            end_idx = len(all_page_data)
            if end_idx > start_idx:
                meeting_date_boundaries.append((meeting, meeting_date, start_idx, end_idx))

    if not all_page_data:
        return

    # Phase 2: Single batch parse of ALL texts with progress updates
    total_pages = len(all_page_data)
    click.echo(
        click.style(subdomain, fg="cyan") + f": Parsing {total_pages} pages..."
    )
    all_texts = [p["text"] for p in all_page_data]

    # Parse with progress updates every 1000 pages
    # n_process > 1 enables multiprocessing for ~2-4x speedup on multi-core machines
    n_process = int(os.environ.get("SPACY_N_PROCESS", "1"))
    all_docs = []
    if EXTRACTION_ENABLED:
        nlp = get_nlp()
        if nlp is not None:
            progress_interval = 1000
            pipe_kwargs = {"batch_size": 500}
            if n_process > 1:
                pipe_kwargs["n_process"] = n_process
                click.echo(
                    click.style(subdomain, fg="cyan")
                    + f": Using {n_process} processes for parsing"
                )
            for i, doc in enumerate(nlp.pipe(all_texts, **pipe_kwargs)):
                all_docs.append(doc)
                if (i + 1) % progress_interval == 0:
                    click.echo(
                        click.style(subdomain, fg="cyan")
                        + f": Parsed {i + 1}/{total_pages} pages..."
                    )
        else:
            all_docs = [None] * total_pages
    else:
        all_docs = [None] * total_pages

    # Phase 3: Process pages grouped by meeting date (for context accumulation)
    entries = []
    current_meeting = None

    for meeting, meeting_date, start_idx, end_idx in meeting_date_boundaries:
        # Log progress per meeting (not per date, to reduce noise)
        if meeting != current_meeting:
            click.echo(click.style(subdomain, fg="cyan") + ": " + f"Processing {meeting}")
            current_meeting = meeting

        # Create fresh context for each meeting date
        meeting_context = create_meeting_context()

        # Process pages for this meeting date with their pre-parsed docs
        for i in range(start_idx, end_idx):
            pdata = all_page_data[i]
            doc = all_docs[i]
            text = pdata["text"]
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
