from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from hashlib import sha256

import click
import pluggy
import sqlite_utils

from .hookspecs import ClerkSpec
from .output import logger


@dataclass
class PageFile:
    """Represents a single page file with its metadata."""

    meeting: str
    date: str
    page_num: int
    text: str
    page_image_path: str


@dataclass
class MeetingDateGroup:
    """Groups page indices by meeting and date."""

    meeting: str
    date: str
    page_indices: list[int]


@dataclass
class PageData:
    """Page data with cache information for extraction."""

    page_id: str
    text: str
    page_file_path: str
    content_hash: str | None
    cached_extraction: dict | None  # {"entities": ..., "votes": ...}


@dataclass
class PageLink:
    """A hyperlink extracted from a PDF page."""

    source_page_id: str
    source_table: str
    page: int
    link_url: str
    link_type: str


pm = pluggy.PluginManager("civicband.clerk")
pm.add_hookspecs(ClerkSpec)

STORAGE_DIR = os.environ.get("STORAGE_DIR", "../sites")


def group_pages_by_meeting_date(page_files: list[PageFile]) -> list[MeetingDateGroup]:
    """Group page files by (meeting, date) for context management.

    Args:
        page_files: List of PageFile objects

    Returns:
        List of MeetingDateGroup objects with page indices
    """
    if not page_files:
        return []

    groups = []
    current_key = None
    current_indices = []

    for idx, page_file in enumerate(page_files):
        key = (page_file.meeting, page_file.date)

        if key != current_key:
            if current_key is not None:
                groups.append(
                    MeetingDateGroup(
                        meeting=current_key[0], date=current_key[1], page_indices=current_indices
                    )
                )
            current_key = key
            current_indices = [idx]
        else:
            current_indices.append(idx)

    # Don't forget the last group
    if current_key is not None:
        groups.append(
            MeetingDateGroup(
                meeting=current_key[0], date=current_key[1], page_indices=current_indices
            )
        )

    return groups


def create_meetings_schema(db):
    """Create standard schema for meetings database.

    Args:
        db: sqlite_utils.Database instance
    """
    schema = {
        "id": str,
        "meeting": str,
        "date": str,
        "page": int,
        "text": str,
        "page_image": str,
        "entities_json": str,
        "votes_json": str,
    }
    db["minutes"].create(schema, pk=("id"))
    db["agendas"].create(schema, pk=("id"))

    link_schema = {
        "id": int,
        "source_page_id": str,
        "source_table": str,
        "page": int,
        "link_url": str,
        "link_type": str,
    }
    db["document_links"].create(link_schema, pk=("id"))
    db["document_links"].create_index(["source_page_id"])


def collect_page_files(txt_dir: str) -> list[PageFile]:
    """Collect all page files from nested directory structure.

    Flattens meeting/date/page directory structure into a flat list.

    Args:
        txt_dir: Root directory containing meeting subdirectories

    Returns:
        List of PageFile objects sorted by meeting, date, page
    """
    page_files: list[PageFile] = []

    if not os.path.exists(txt_dir):
        return page_files

    logger.log("Started collecting page files")
    meetings = sorted(
        [
            d
            for d in os.listdir(txt_dir)
            if d != ".DS_Store" and os.path.isdir(os.path.join(txt_dir, d))
        ]
    )

    for meeting in meetings:
        logger.log(f"Collecting for {meeting}")
        meeting_path = os.path.join(txt_dir, meeting)
        dates = sorted(
            [
                d
                for d in os.listdir(meeting_path)
                if d != ".DS_Store" and os.path.isdir(os.path.join(meeting_path, d))
            ]
        )

        for date in dates:
            date_path = os.path.join(meeting_path, date)
            pages = sorted([p for p in os.listdir(date_path) if p.endswith(".txt")])

            for page in pages:
                page_path = os.path.join(date_path, page)
                with open(page_path) as f:
                    text = f.read()

                page_num = int(page.split(".")[0])
                page_image_path = f"/{meeting}/{date}/{page.split('.')[0]}.png"

                page_files.append(
                    PageFile(
                        meeting=meeting,
                        date=date,
                        page_num=page_num,
                        text=text,
                        page_image_path=page_image_path,
                    )
                )

    return page_files


def collect_page_links(txt_dir: str) -> dict[tuple[str, str, int], list[dict]]:
    """Collect all link data from _links.json sidecar files.

    Returns a dict keyed by (meeting, date, page_num) mapping to
    a list of link dicts: [{"url": "...", "link_type": "..."}, ...]
    """
    links_by_page: dict[tuple[str, str, int], list[dict]] = {}

    if not os.path.exists(txt_dir):
        return links_by_page

    meetings = sorted(
        d
        for d in os.listdir(txt_dir)
        if d != ".DS_Store" and os.path.isdir(os.path.join(txt_dir, d))
    )

    for meeting in meetings:
        meeting_path = os.path.join(txt_dir, meeting)
        dates = sorted(
            d
            for d in os.listdir(meeting_path)
            if d != ".DS_Store" and os.path.isdir(os.path.join(meeting_path, d))
        )

        for date in dates:
            date_path = os.path.join(meeting_path, date)
            links_file = os.path.join(date_path, "_links.json")
            if not os.path.exists(links_file):
                continue

            try:
                with open(links_file) as f:
                    all_links: list[dict] = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                continue

            for link in all_links:
                page_num = link["page"]
                key = (meeting, date, page_num)
                if key not in links_by_page:
                    links_by_page[key] = []
                links_by_page[key].append(
                    {
                        "url": link["url"],
                        "link_type": link.get("link_type", "other"),
                    }
                )

    return links_by_page


def hash_text_content(text: str) -> str:
    """Hash text content for cache validation.

    Args:
        text: The text content to hash

    Returns:
        SHA256 hash as hex string
    """
    return sha256(text.encode("utf-8")).hexdigest()


def load_extraction_cache(cache_file: str, expected_hash: str) -> dict | None:
    """Load extraction cache if valid.

    Args:
        cache_file: Path to .extracted.json cache file
        expected_hash: Expected content hash

    Returns:
        Cache data dict if valid, None otherwise
    """
    try:
        with open(cache_file) as f:
            data: dict = json.load(f)

        # Validate structure
        required_keys = {"content_hash", "entities", "votes"}
        if not required_keys.issubset(data.keys()):
            logger.log(f"Cache invalid: missing keys in {cache_file}")
            return None

        # Validate hash match
        if data["content_hash"] != expected_hash:
            logger.log(f"Cache invalid: hash mismatch in {cache_file}")
            return None

        return data
    except (json.JSONDecodeError, FileNotFoundError, KeyError) as e:
        logger.log(f"Cache invalid: {e} in {cache_file}")
        return None


def save_extraction_cache(cache_file: str, data: dict) -> None:
    """Save extraction results to cache file.

    Args:
        cache_file: Path to .extracted.json cache file
        data: Cache data to save (must include content_hash, entities, votes)
    """
    try:
        with open(cache_file, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.log(f"Failed to save cache {cache_file}: {e}", level="warning")


def assert_db_exists():
    """Ensure civic.db schema exists using SQLAlchemy abstraction.

    Returns:
        SQLAlchemy engine instance
    """

    from .db import get_civic_db
    from .models import metadata

    engine = get_civic_db()

    # Create tables if they don't exist
    # This works for both SQLite and PostgreSQL
    metadata.create_all(engine, checkfirst=True)

    # Handle deprecated columns for SQLite only
    # PostgreSQL migrations are managed via Alembic
    if "sqlite" in str(engine.url):
        # Use sqlite_utils for backward compatibility with column dropping
        db = sqlite_utils.Database(str(engine.url).replace("sqlite:///", ""))

        # Check for feed_entries table (legacy, create if needed)
        if not db["feed_entries"].exists():
            db["feed_entries"].create({"subdomain": str, "date": str, "kind": str, "name": str})  # type: ignore

        # Only drop deprecated columns if they still exist
        existing_columns = {col.name for col in db["sites"].columns}
        deprecated_columns = {"ocr_class", "docker_port", "save_agendas", "site_db"}
        columns_to_drop = existing_columns & deprecated_columns

        if columns_to_drop:
            db["sites"].transform(drop=columns_to_drop)  # type: ignore

    return engine


def build_table_from_text(
    subdomain,
    txt_dir,
    db,
    table_name,
    municipality=None,
):
    """Build database table from text files, reading cached extraction results.

    This is a pure data-assembly step. It reads cached extraction results
    (produced by `clerk extract run`) but never runs extraction itself.
    Pages without cached results get empty entities/votes.

    Args:
        subdomain: Site subdomain (e.g., "alameda.ca.civic.band")
        txt_dir: Directory containing text files
        db: sqlite_utils Database object
        table_name: Name of table to create ("minutes" or "agendas")
        municipality: Optional municipality name for aggregate database
    """
    st = time.time()
    logger.subdomain = subdomain
    logger.log(
        f"Building table from text table_name={table_name} municipality={municipality}",
    )

    # Phase 1: Collect page files
    page_files = collect_page_files(txt_dir)
    if not page_files:
        return

    # Fix page_image_path for agendas
    if table_name == "agendas":
        for pf in page_files:
            pf.page_image_path = f"/_agendas{pf.page_image_path}"

    # Determine base directory for cache files
    storage_dir = os.environ.get("STORAGE_DIR", "../sites")
    base_txt_dir = f"{storage_dir}/{subdomain}"
    if table_name == "agendas":
        base_txt_dir = f"{base_txt_dir}/_agendas"
    base_txt_dir = f"{base_txt_dir}/txt"

    cache_hits = 0
    cache_misses = 0

    # Phase 2: Process pages grouped by meeting date
    entries = []
    for meeting_date_group in group_pages_by_meeting_date(page_files):
        # Log progress per meeting
        if meeting_date_group.meeting != getattr(build_table_from_text, "_last_meeting", None):
            click.echo(
                click.style(subdomain, fg="cyan")
                + ": "
                + f"Processing {meeting_date_group.meeting}"
            )
            build_table_from_text._last_meeting = meeting_date_group.meeting

        # Process pages for this meeting date
        for idx in meeting_date_group.page_indices:
            pf = page_files[idx]

            # Check cache file for pre-computed extraction results
            cache_file = (
                f"{base_txt_dir}/{pf.meeting}/{pf.date}/{pf.page_num:04d}.txt.extracted.json"
            )
            content_hash = hash_text_content(pf.text)
            cached = load_extraction_cache(cache_file, content_hash)

            if cached:
                cache_hits += 1
                entities_json = json.dumps(cached["entities"])
                votes_json = json.dumps(cached["votes"])
            else:
                cache_misses += 1
                entities_json = json.dumps({"persons": [], "orgs": [], "locations": []})
                votes_json = json.dumps({"votes": []})

            # Build database entry
            key_hash = {
                "kind": "minutes" if table_name != "agendas" else "agenda",
                "meeting": pf.meeting,
                "date": pf.date,
                "page": pf.page_num,
                "text": pf.text,
            }
            if municipality:
                key_hash.update({"subdomain": subdomain, "municipality": municipality})

            key = sha256(json.dumps(key_hash, sort_keys=True).encode("utf-8")).hexdigest()[:12]

            entry = {
                "id": key,
                "meeting": pf.meeting,
                "date": pf.date,
                "page": pf.page_num,
                "text": pf.text,
                "page_image": pf.page_image_path,
                "entities_json": entities_json,
                "votes_json": votes_json,
            }

            if municipality:
                entry["subdomain"] = subdomain
                entry["municipality"] = municipality

            entries.append(entry)

    logger.log(
        f"Cache status: {cache_hits} hits, {cache_misses} misses",
        subdomain=subdomain,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
    )

    # Phase 3: Insert to database
    db[table_name].insert_all(entries)

    # Log performance summary
    et = time.time()
    elapsed = et - st

    logger.log(
        f"Build completed in {elapsed:.2f}s",
        subdomain=subdomain,
        elapsed_time=f"{elapsed:.2f}",
        total_pages=len(page_files),
    )


def build_links_table(subdomain, txt_dir, db, table_name):
    """Populate the document_links table from _links.json sidecar files.

    Reads _links.json files written during OCR and maps each link
    to its source page ID in the minutes or agendas table.

    Args:
        subdomain: Site subdomain
        txt_dir: Directory containing text files
        db: sqlite_utils Database object
        table_name: "minutes" or "agendas"
    """
    links_by_page = collect_page_links(txt_dir)
    if not links_by_page:
        return

    entries = []

    for (_meeting, _date, page_num), links in links_by_page.items():
        for link in links:
            entries.append(
                {
                    "source_page_id": None,
                    "source_table": table_name,
                    "page": page_num,
                    "link_url": link["url"],
                    "link_type": link["link_type"],
                }
            )

    if entries:
        db["document_links"].insert_all(entries)

    logger.log(
        f"Built {len(entries)} document links for {table_name}",
        subdomain=subdomain,
        link_count=len(entries),
    )


def build_db_from_text_internal(subdomain):
    """Build meetings database from text files.

    This is a pure data-assembly step that reads cached extraction results
    but never runs extraction.

    Args:
        subdomain: Site subdomain
    """
    st = time.time()
    logger.subdomain = subdomain
    logger.log("Building database from text")
    minutes_txt_dir = f"{STORAGE_DIR}/{subdomain}/txt"
    agendas_txt_dir = f"{STORAGE_DIR}/{subdomain}/_agendas/txt"
    database = f"{STORAGE_DIR}/{subdomain}/meetings.db"
    db_backup = f"{STORAGE_DIR}/{subdomain}/meetings.db.bk"
    shutil.copy(database, db_backup)
    os.remove(database)
    db = sqlite_utils.Database(database)
    create_meetings_schema(db)
    if os.path.exists(minutes_txt_dir):
        build_table_from_text(
            subdomain,
            minutes_txt_dir,
            db,
            "minutes",
        )
        build_links_table(subdomain, minutes_txt_dir, db, "minutes")
    if os.path.exists(agendas_txt_dir):
        build_table_from_text(
            subdomain,
            agendas_txt_dir,
            db,
            "agendas",
        )
        build_links_table(subdomain, agendas_txt_dir, db, "agendas")

    # Explicitly close database to ensure all writes are flushed
    db.close()

    et = time.time()
    elapsed_time = et - st
    logger.subdomain = subdomain
    logger.log(f"Database build completed elapsed_time={elapsed_time:.2f}")
