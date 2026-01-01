import datetime
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
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


logger = logging.getLogger(__name__)

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

    for idx, pf in enumerate(page_files):
        key = (pf.meeting, pf.date)

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


def collect_page_files(txt_dir: str) -> list[PageFile]:
    """Collect all page files from nested directory structure.

    Flattens meeting/date/page directory structure into a flat list.

    Args:
        txt_dir: Root directory containing meeting subdirectories

    Returns:
        List of PageFile objects sorted by meeting, date, page
    """
    page_files = []

    if not os.path.exists(txt_dir):
        return page_files

    meetings = sorted(
        [
            d
            for d in os.listdir(txt_dir)
            if d != ".DS_Store" and os.path.isdir(os.path.join(txt_dir, d))
        ]
    )

    for meeting in meetings:
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


def batch_parse_with_spacy(texts: list[str], subdomain: str) -> list:
    """Batch parse texts with spaCy using nlp.pipe().

    Args:
        texts: List of text strings to parse
        subdomain: Site subdomain for logging

    Returns:
        List of spaCy Doc objects (or None if extraction disabled)
    """
    if not texts:
        return []

    if not EXTRACTION_ENABLED:
        return [None] * len(texts)

    nlp = get_nlp()
    if nlp is None:
        return [None] * len(texts)

    total_pages = len(texts)
    click.echo(click.style(subdomain, fg="cyan") + f": Parsing {total_pages} pages...")

    n_process = int(os.environ.get("SPACY_N_PROCESS", "1"))
    pipe_kwargs = {"batch_size": 500}

    if n_process > 1:
        pipe_kwargs["n_process"] = n_process
        click.echo(click.style(subdomain, fg="cyan") + f": Using {n_process} processes for parsing")

    all_docs = []
    progress_interval = 1000

    for i, doc in enumerate(nlp.pipe(texts, **pipe_kwargs)):
        all_docs.append(doc)
        if (i + 1) % progress_interval == 0:
            click.echo(
                click.style(subdomain, fg="cyan") + f": Parsed {i + 1}/{total_pages} pages..."
            )

    return all_docs


def process_page_for_db(
    page_file: PageFile,
    doc,
    context: dict,
    subdomain: str,
    table_name: str,
    municipality: str | None,
) -> dict:
    """Process a single page for database insertion.

    Extracts entities/votes, updates context, formats as DB entry.

    Args:
        page_file: PageFile with page metadata and text
        doc: spaCy Doc object (or None if extraction disabled)
        context: Meeting context dict for accumulating entities
        subdomain: Site subdomain
        table_name: "minutes" or "agendas"
        municipality: Optional municipality name

    Returns:
        Dict ready for db.insert() with all required fields
    """
    text = page_file.text

    # Extract entities and update context
    try:
        entities = extract_entities(text, doc=doc)
        update_context(context, entities=entities)
    except Exception as e:
        logger.warning(
            f"Entity extraction failed for {page_file.meeting}/{page_file.date}/{page_file.page_num}: {e}"
        )
        entities = {"persons": [], "orgs": [], "locations": []}

    # Detect roll call and update context
    try:
        attendees = detect_roll_call(text)
        if attendees:
            update_context(context, attendees=attendees)
    except Exception as e:
        logger.warning(
            f"Roll call detection failed for {page_file.meeting}/{page_file.date}/{page_file.page_num}: {e}"
        )

    # Extract votes with context
    try:
        votes = extract_votes(text, doc=doc, meeting_context=context)
    except Exception as e:
        logger.warning(
            f"Vote extraction failed for {page_file.meeting}/{page_file.date}/{page_file.page_num}: {e}"
        )
        votes = {"votes": []}

    # Build database entry
    key_hash = {
        "kind": "minutes" if table_name != "agendas" else "agenda",
        "meeting": page_file.meeting,
        "date": page_file.date,
        "page": page_file.page_num,
        "text": text,
    }

    if municipality:
        key_hash.update({"subdomain": subdomain, "municipality": municipality})

    key = sha256(json.dumps(key_hash, sort_keys=True).encode("utf-8")).hexdigest()
    key = key[:12]

    entry = {
        "id": key,
        "meeting": page_file.meeting,
        "date": page_file.date,
        "page": page_file.page_num,
        "text": text,
        "page_image": page_file.page_image_path,
        "entities_json": json.dumps(entities),
        "votes_json": json.dumps(votes),
    }

    # Add optional fields for aggregate databases
    if municipality:
        entry["subdomain"] = subdomain
        entry["municipality"] = municipality

    return entry


def load_pages_from_db(subdomain: str, table_name: str) -> list[dict]:
    """Load all page records from site's database.

    Args:
        subdomain: Site subdomain
        table_name: "minutes" or "agendas"

    Returns:
        List of page dicts from database
    """
    storage_dir = os.environ.get("STORAGE_DIR", "../sites")
    site_db_path = f"{storage_dir}/{subdomain}/meetings.db"
    db = sqlite_utils.Database(site_db_path)

    if not db[table_name].exists():
        return []

    return list(db[table_name].rows)


def collect_page_data_with_cache(
    pages: list[dict], subdomain: str, table_name: str, force_extraction: bool
) -> list[PageData]:
    """Collect page data with cache checking.

    Reads text files and checks extraction cache for each page.

    Args:
        pages: List of page dicts from database
        subdomain: Site subdomain
        table_name: "minutes" or "agendas"
        force_extraction: If True, ignore cache

    Returns:
        List of PageData objects with cache information
    """
    from .output import log

    storage_dir = os.environ.get("STORAGE_DIR", "../sites")
    txt_subdir = "txt" if table_name == "minutes" else "_agendas/txt"
    txt_dir = f"{storage_dir}/{subdomain}/{txt_subdir}"

    if not os.path.exists(txt_dir):
        return []

    all_page_data = []
    cache_hits = 0
    cache_misses = 0

    for page in pages:
        meeting = page["meeting"]
        date = page["date"]
        page_num = page["page"]

        # Find corresponding text file
        page_file_path = f"{txt_dir}/{meeting}/{date}/{page_num:04d}.txt"

        if not os.path.exists(page_file_path):
            logger.warning(f"Text file not found: {page_file_path}")
            continue

        with open(page_file_path) as f:
            text = f.read()

        # Check cache
        cached_extraction = None
        content_hash = None

        if not force_extraction:
            content_hash = hash_text_content(text)
            cache_file = f"{page_file_path}.extracted.json"
            cached_extraction = load_extraction_cache(cache_file, content_hash)

            if cached_extraction:
                cache_hits += 1
            else:
                cache_misses += 1
        else:
            cache_misses += 1

        all_page_data.append(
            PageData(
                page_id=page["id"],
                text=text,
                page_file_path=page_file_path,
                content_hash=content_hash,
                cached_extraction=cached_extraction,
            )
        )

    log(
        f"Cache status: {cache_hits} hits, {cache_misses} misses",
        subdomain=subdomain,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
    )

    return all_page_data


def batch_process_uncached_pages(page_data: list[PageData], subdomain: str) -> list:
    """Batch process uncached pages with spaCy.

    Args:
        page_data: List of PageData objects
        subdomain: Site subdomain for logging

    Returns:
        List of Docs parallel to page_data (None for cached pages)
    """
    from .output import log

    uncached_indices = [i for i, p in enumerate(page_data) if p.cached_extraction is None]
    all_docs = [None] * len(page_data)

    if uncached_indices and EXTRACTION_ENABLED:
        uncached_texts = [page_data[i].text for i in uncached_indices]
        nlp = get_nlp()
        if nlp:
            log(
                f"Batch processing {len(uncached_texts)} uncached pages with nlp.pipe()",
                subdomain=subdomain,
            )
            # Single batch process with nlp.pipe()
            for processed, doc in enumerate(nlp.pipe(uncached_texts, batch_size=500)):
                original_idx = uncached_indices[processed]
                all_docs[original_idx] = doc

    return all_docs


def save_extractions_to_db(page_data: list[PageData], docs: list, subdomain: str, table_name: str):
    """Save extractions to database (extract or use cache).

    For each page: use cached extraction OR extract from doc,
    save to cache, update database.

    Args:
        page_data: List of PageData objects
        docs: List of spaCy Docs (parallel to page_data)
        subdomain: Site subdomain
        table_name: "minutes" or "agendas"
    """
    storage_dir = os.environ.get("STORAGE_DIR", "../sites")
    site_db_path = f"{storage_dir}/{subdomain}/meetings.db"
    db = sqlite_utils.Database(site_db_path)

    for i, pdata in enumerate(page_data):
        doc = docs[i]
        cached = pdata.cached_extraction

        if cached:
            entities = cached["entities"]
            votes = cached["votes"]
        else:
            if not EXTRACTION_ENABLED:
                # Set empty structures when extraction is disabled
                entities = {"persons": [], "orgs": [], "locations": []}
                votes = {"votes": []}
            else:
                # Extract entities and votes using pre-parsed doc
                try:
                    entities = extract_entities(pdata.text, doc=doc)
                    votes = extract_votes(pdata.text, doc=doc, meeting_context={})
                except Exception as e:
                    logger.warning(f"Extraction failed for {pdata.page_file_path}: {e}")
                    entities = {"persons": [], "orgs": [], "locations": []}
                    votes = {"votes": []}

            # Write cache
            content_hash = pdata.content_hash
            if content_hash is None:
                content_hash = hash_text_content(pdata.text)
            cache_file = f"{pdata.page_file_path}.extracted.json"
            cache_data = {
                "content_hash": content_hash,
                "extracted_at": datetime.datetime.now().isoformat(),
                "entities": entities,
                "votes": votes,
            }
            save_extraction_cache(cache_file, cache_data)

        # Update database
        db[table_name].update(
            pdata.page_id, {"entities_json": json.dumps(entities), "votes_json": json.dumps(votes)}
        )


# Maximum pages to process in a single spaCy batch before chunking
# Prevents memory spikes on large datasets while maintaining efficiency
SPACY_CHUNK_SIZE = 20_000


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
            logger.debug(f"Cache invalid: missing keys in {cache_file}")
            return None

        # Validate hash match
        if data["content_hash"] != expected_hash:
            logger.debug(f"Cache invalid: hash mismatch in {cache_file}")
            return None

        return data
    except (json.JSONDecodeError, FileNotFoundError, KeyError) as e:
        logger.debug(f"Cache invalid: {e} in {cache_file}")
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
        logger.warning(f"Failed to save cache {cache_file}: {e}")


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


def build_table_from_text(
    subdomain,
    txt_dir,
    db,
    table_name,
    municipality=None,
    skip_extraction=True,
    force_extraction=False,
):
    """Build database table from text files

    Args:
        subdomain: Site subdomain (e.g., "alameda.ca.civic.band")
        txt_dir: Directory containing text files
        db: sqlite_utils Database object
        table_name: Name of table to create ("minutes" or "agendas")
        municipality: Optional municipality name for aggregate database
        skip_extraction: If True, skip entity/vote extraction (default True)
        force_extraction: If True, ignore cache and re-extract all pages (default False)
    """
    st = time.time()
    logger.info(
        "Building table from text subdomain=%s table_name=%s municipality=%s skip_extraction=%s force_extraction=%s",
        subdomain,
        table_name,
        municipality,
        skip_extraction,
        force_extraction,
    )
    # Phase 1: Collect all page files
    page_files = collect_page_files(txt_dir)
    if not page_files:
        return

    # Fix page_image_path for agendas
    if table_name == "agendas":
        for pf in page_files:
            pf.page_image_path = f"/_agendas{pf.page_image_path}"

    # Phase 2: Batch parse all texts with spaCy
    texts = [pf.text for pf in page_files]
    docs = batch_parse_with_spacy(texts, subdomain) if not skip_extraction else [None] * len(texts)

    # Phase 3: Process pages grouped by meeting date (for context)
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

        # Create fresh context for each meeting date
        meeting_context = create_meeting_context()

        # Process pages for this meeting date with their pre-parsed docs
        for idx in meeting_date_group.page_indices:
            entry = process_page_for_db(
                page_files[idx], docs[idx], meeting_context, subdomain, table_name, municipality
            )
            entries.append(entry)

    # Phase 4: Insert to database
    db[table_name].insert_all(entries)

    # Log performance summary
    et = time.time()
    elapsed = et - st
    total_files = len(page_files)

    from .output import log

    log(
        f"Build completed in {elapsed:.2f}s",
        subdomain=subdomain,
        elapsed_time=f"{elapsed:.2f}",
        total_pages=total_files,
    )


def build_db_from_text_internal(subdomain, skip_extraction=True, force_extraction=False):
    st = time.time()
    logger.info(
        "Building database from text subdomain=%s skip_extraction=%s force_extraction=%s",
        subdomain,
        skip_extraction,
        force_extraction,
    )
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
            skip_extraction=skip_extraction,
            force_extraction=force_extraction,
        )
    if os.path.exists(agendas_txt_dir):
        build_table_from_text(
            subdomain,
            agendas_txt_dir,
            db,
            "agendas",
            skip_extraction=skip_extraction,
            force_extraction=force_extraction,
        )

    # Explicitly close database to ensure all writes are flushed
    db.close()

    et = time.time()
    elapsed_time = et - st
    logger.info(
        "Database build completed subdomain=%s elapsed_time=%.2f force_extraction=%s",
        subdomain,
        elapsed_time,
        force_extraction,
    )
    click.echo(f"Execution time: {elapsed_time} seconds")


def extract_table_entities(subdomain: str, table_name: str, force_extraction: bool):
    """Extract entities for one table (minutes or agendas).

    Uses existing helper functions to load pages, check cache, batch process,
    and save extractions.

    Args:
        subdomain: Site subdomain (e.g., "alameda.ca.civic.band")
        table_name: Table to process ("minutes" or "agendas")
        force_extraction: If True, bypass cache and re-extract all pages
    """
    # Load pages from database
    pages = load_pages_from_db(subdomain, table_name)
    if not pages:
        return

    # Collect page data with cache checking
    page_data = collect_page_data_with_cache(pages, subdomain, table_name, force_extraction)
    if not page_data:
        return

    # Batch process uncached pages
    docs = batch_process_uncached_pages(page_data, subdomain)

    # Save extractions to database
    save_extractions_to_db(page_data, docs, subdomain, table_name)


def extract_entities_for_site(subdomain, force_extraction=False):
    """Extract entities for all pages in a site's database

    Reads existing database records, processes uncached pages with spaCy,
    and updates entities_json/votes_json columns.

    Args:
        subdomain: Site subdomain (e.g., "alameda.ca.civic.band")
        force_extraction: If True, bypass cache and re-extract all pages
    """
    from .output import log

    st = time.time()
    logger.info("Extracting entities subdomain=%s force_extraction=%s", subdomain, force_extraction)

    # Process both minutes and agendas
    for table_name in ["minutes", "agendas"]:
        extract_table_entities(subdomain, table_name, force_extraction)

    et = time.time()
    elapsed = et - st
    log(
        f"Total extraction time: {elapsed:.2f}s", subdomain=subdomain, elapsed_time=f"{elapsed:.2f}"
    )
