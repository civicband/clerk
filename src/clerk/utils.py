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
    detect_roll_call,
    extract_entities,
    extract_votes,
    get_nlp,
    update_context,
)
from .hookspecs import ClerkSpec
from .output import log


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
    page_files: list[PageFile] = []

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
        log(
            f"Entity extraction failed for {page_file.meeting}/{page_file.date}/{page_file.page_num}: {e}",
            subdomain=subdomain,
            level="warning",
        )
        entities = {"persons": [], "orgs": [], "locations": []}

    # Detect roll call and update context
    try:
        attendees = detect_roll_call(text)
        if attendees:
            update_context(context, attendees=attendees)
    except Exception as e:
        log(
            f"Roll call detection failed for {page_file.meeting}/{page_file.date}/{page_file.page_num}: {e}",
            subdomain=subdomain,
            level="warning",
        )

    # Extract votes with context
    try:
        votes = extract_votes(text, doc=doc, meeting_context=context)
    except Exception as e:
        log(
            f"Vote extraction failed for {page_file.meeting}/{page_file.date}/{page_file.page_num}: {e}",
            subdomain=subdomain,
            level="warning",
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
        log(f"Failed to save cache {cache_file}: {e}", level="warning")


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


def extract_and_cache(text: str, doc, cache_file: str) -> tuple[dict, dict]:
    """Extract entities and votes, then save to cache.

    Args:
        text: Page text content
        doc: spaCy Doc object
        cache_file: Path to cache file

    Returns:
        Tuple of (entities dict, votes dict)
    """
    try:
        entities = extract_entities(text, doc=doc)
        votes = extract_votes(text, doc=doc, meeting_context={})
    except Exception as e:
        log(f"Extraction failed for {cache_file}: {e}", level="warning")
        entities = {"persons": [], "orgs": [], "locations": []}
        votes = {"votes": []}

    # Save to cache
    content_hash = hash_text_content(text)
    cache_data = {
        "content_hash": content_hash,
        "extracted_at": datetime.datetime.now().isoformat(),
        "entities": entities,
        "votes": votes,
    }
    save_extraction_cache(cache_file, cache_data)

    return entities, votes


def build_table_from_text(
    subdomain,
    txt_dir,
    db,
    table_name,
    municipality=None,
    extract_entities=False,
    ignore_cache=False,
):
    """Build database table from text files with optional entity extraction

    Args:
        subdomain: Site subdomain (e.g., "alameda.ca.civic.band")
        txt_dir: Directory containing text files
        db: sqlite_utils Database object
        table_name: Name of table to create ("minutes" or "agendas")
        municipality: Optional municipality name for aggregate database
        extract_entities: If True, extract entities for uncached pages (default False)
        ignore_cache: If True, ignore cache and extract all (only valid with extract_entities=True)
    """
    st = time.time()
    log(
        f"Building table from text table_name={table_name} municipality={municipality} extract_entities={extract_entities} ignore_cache={ignore_cache}",
        subdomain=subdomain,
    )

    # Phase 1: Collect page files and check cache
    page_files = collect_page_files(txt_dir)
    if not page_files:
        return

    # Fix page_image_path for agendas
    if table_name == "agendas":
        for pf in page_files:
            pf.page_image_path = f"/_agendas{pf.page_image_path}"

    # Check cache for all pages (ignore_cache only matters if extract_entities=True)
    page_data = []
    cache_hits = 0
    cache_misses = 0

    storage_dir = os.environ.get("STORAGE_DIR", "../sites")
    base_txt_dir = f"{storage_dir}/{subdomain}"
    if table_name == "agendas":
        base_txt_dir = f"{base_txt_dir}/_agendas"
    base_txt_dir = f"{base_txt_dir}/txt"

    for pf in page_files:
        # Construct path to cache file
        cache_file = f"{base_txt_dir}/{pf.meeting}/{pf.date}/{pf.page_num:04d}.txt.extracted.json"
        cached_extraction = None

        # Check cache unless ignore_cache is True (and we're extracting)
        if not (extract_entities and ignore_cache):
            content_hash = hash_text_content(pf.text)
            cached_extraction = load_extraction_cache(cache_file, content_hash)

            if cached_extraction:
                cache_hits += 1
            else:
                cache_misses += 1
        else:
            cache_misses += 1

        page_data.append(
            {
                "page_file": pf,
                "cache_file": cache_file,
                "cached_extraction": cached_extraction,
            }
        )

    log(
        f"Cache status: {cache_hits} hits, {cache_misses} misses",
        subdomain=subdomain,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
    )

    # Phase 2: Batch parse uncached pages (if extracting)
    docs = [None] * len(page_data)

    if extract_entities:
        # Find pages that need extraction
        uncached_indices = [i for i, pd in enumerate(page_data) if pd["cached_extraction"] is None]

        if uncached_indices:
            # Extract texts for uncached pages
            uncached_texts = [page_data[i]["page_file"].text for i in uncached_indices]
            uncached_docs = batch_parse_with_spacy(uncached_texts, subdomain)

            # Store docs at correct indices
            for i, doc_idx in enumerate(uncached_indices):
                docs[doc_idx] = uncached_docs[i]

    # Phase 3: Process pages grouped by meeting date
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
            pd = page_data[idx]
            pf = pd["page_file"]
            cached = pd["cached_extraction"]
            doc = docs[idx]

            if cached:
                # Use cached entities/votes
                entities_json = json.dumps(cached["entities"])
                votes_json = json.dumps(cached["votes"])
            elif extract_entities:
                # Extraction enabled - extract and cache (even if doc is None due to missing spaCy)
                entities, votes = extract_and_cache(pf.text, doc, pd["cache_file"])
                entities_json = json.dumps(entities)
                votes_json = json.dumps(votes)
            else:
                # No cache and extraction disabled - empty entities
                entities_json = json.dumps({"persons": [], "orgs": [], "locations": []})
                votes_json = json.dumps({"votes": []})

            # Build database entry (similar to process_page_for_db but with cached data)
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

    # Phase 4: Insert to database
    db[table_name].insert_all(entries)

    # Log performance summary
    et = time.time()
    elapsed = et - st

    log(
        f"Build completed in {elapsed:.2f}s",
        subdomain=subdomain,
        elapsed_time=f"{elapsed:.2f}",
        total_pages=len(page_files),
    )


def build_db_from_text_internal(subdomain, extract_entities=False, ignore_cache=False):
    st = time.time()
    log(
        f"Building database from text extract_entities={extract_entities} ignore_cache={ignore_cache}",
        subdomain=subdomain,
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
            extract_entities=extract_entities,
            ignore_cache=ignore_cache,
        )
    if os.path.exists(agendas_txt_dir):
        build_table_from_text(
            subdomain,
            agendas_txt_dir,
            db,
            "agendas",
            extract_entities=extract_entities,
            ignore_cache=ignore_cache,
        )

    # Explicitly close database to ensure all writes are flushed
    db.close()

    et = time.time()
    elapsed_time = et - st
    log(
        f"Database build completed elapsed_time={elapsed_time:.2f} extract_entities={extract_entities} ignore_cache={ignore_cache}",
        subdomain=subdomain,
    )
    click.echo(f"Execution time: {elapsed_time} seconds")
