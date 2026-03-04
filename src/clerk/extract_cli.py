"""CLI commands for entity and vote extraction.

Provides the `clerk extract` command group with subcommands:
- entities: Extract persons, orgs, locations
- votes: Extract vote records
- all: Run both entity and vote extraction
"""

import datetime
import os

import click
from sqlalchemy import update

from .db import civic_db_connection
from .extraction import (
    EXTRACTION_ENABLED,
    create_meeting_context,
    detect_section,
    get_nlp,
    resolve_entities,
    update_context,
)
from .extraction import (
    extract_entities as _extract_entities,
)
from .extraction import (
    extract_votes as _extract_votes,
)
from .models import sites_table
from .output import log
from .utils import (
    collect_page_files,
    group_pages_by_meeting_date,
    hash_text_content,
    load_extraction_cache,
    save_extraction_cache,
)

STORAGE_DIR = os.environ.get("STORAGE_DIR", "../sites")


@click.group()
def extract():
    """Extract entities and votes from site text files."""
    pass


def _validate_site_args(subdomain, next_site):
    """Validate that either --subdomain or --next-site is provided."""
    if not subdomain and not next_site:
        raise click.UsageError("Must specify --subdomain or --next-site")


def _resolve_subdomain(subdomain, next_site):
    """Resolve the subdomain to use for extraction.

    If --next-site is used, queries the database for the next site
    needing extraction. Otherwise, returns the provided subdomain.

    Args:
        subdomain: Explicit subdomain, or None
        next_site: If True, auto-select next site from DB

    Returns:
        Resolved subdomain string

    Raises:
        click.UsageError: If no site can be resolved
    """
    if subdomain:
        return subdomain

    if next_site:
        from sqlalchemy import text as sql_text

        from .utils import assert_db_exists

        engine = assert_db_exists()
        with engine.connect() as conn:
            row = conn.execute(
                sql_text(
                    "SELECT subdomain FROM sites "
                    "WHERE extraction_status IN ('pending', 'failed') "
                    "ORDER BY last_extracted ASC NULLS FIRST "
                    "LIMIT 1"
                )
            ).fetchone()

            if not row:
                log("No sites need extraction")
                return None
            subdomain = row[0]
            log(f"Selected next site: {subdomain}")
            return subdomain

    raise click.UsageError("Must specify --subdomain or --next-site")


def _run_extraction_for_site(subdomain, txt_dir, mode, rebuild):
    """Run extraction for a single site.

    Orchestrates entity and/or vote extraction across all page files
    in the given txt_dir, using caching to avoid redundant work.

    Args:
        subdomain: Site subdomain for logging
        txt_dir: Root directory containing meeting/date/page text files
        mode: One of "entities", "votes", or "all"
        rebuild: If True, ignore existing cache and re-extract
    """
    if not EXTRACTION_ENABLED:
        log(
            "Extraction disabled (set ENABLE_EXTRACTION=1 to enable)",
            subdomain=subdomain,
            level="warning",
        )
        return False

    # Collect all page files
    page_files = collect_page_files(txt_dir)
    if not page_files:
        log("No page files found", subdomain=subdomain, level="warning")
        return

    log(
        f"Found {len(page_files)} pages, mode={mode}, rebuild={rebuild}",
        subdomain=subdomain,
    )

    # Phase 1: Check cache and determine which pages need extraction
    pages_to_extract = []  # (index, page_file, existing_cache_data)
    cached_count = 0

    for idx, pf in enumerate(page_files):
        cache_file = os.path.join(
            txt_dir, pf.meeting, pf.date, f"{pf.page_num:04d}.txt.extracted.json"
        )

        # Always try to load existing cache for preserving other sections
        content_hash = hash_text_content(pf.text)
        existing_cache = load_extraction_cache(cache_file, content_hash)

        if not rebuild and existing_cache is not None:
            # Check if the requested section already exists in cache
            has_entities = existing_cache.get("entities", {}).get("persons") is not None
            has_votes = existing_cache.get("votes", {}).get("votes") is not None

            if mode == "entities" and has_entities:
                cached_count += 1
                continue
            elif mode == "votes" and has_votes:
                cached_count += 1
                continue
            elif mode == "all" and has_entities and has_votes:
                cached_count += 1
                continue

        pages_to_extract.append((idx, pf, existing_cache))

    log(
        f"Cache: {cached_count} hits, {len(pages_to_extract)} to extract",
        subdomain=subdomain,
    )

    if not pages_to_extract:
        log("All pages cached, nothing to extract", subdomain=subdomain)
        return True

    # Phase 2: Batch parse uncached pages with spaCy
    nlp = get_nlp()
    texts_to_parse = [pf.text for _, pf, _ in pages_to_extract]

    if nlp is not None:
        docs = list(nlp.pipe(texts_to_parse))
    else:
        docs = [None] * len(texts_to_parse)

    # Phase 3: Extract and save cache for each page
    # Build a lookup from (meeting, date, page_num) to (doc_index, existing_cache)
    extract_lookup = {}
    for i, (_, pf, existing_cache) in enumerate(pages_to_extract):
        extract_lookup[(pf.meeting, pf.date, pf.page_num)] = (i, existing_cache)

    # Group all pages by meeting/date for context management
    meeting_groups = group_pages_by_meeting_date(page_files)

    for group in meeting_groups:
        meeting_context = create_meeting_context()
        # Track cache files and data for entity resolution post-processing
        group_cache_entries = []  # (cache_file, cache_data) for resolution pass

        for page_idx in group.page_indices:
            pf = page_files[page_idx]
            cache_file = os.path.join(
                txt_dir, pf.meeting, pf.date, f"{pf.page_num:04d}.txt.extracted.json"
            )

            key = (pf.meeting, pf.date, pf.page_num)
            if key not in extract_lookup:
                # This page was cached, skip extraction
                continue

            doc_i, existing_cache = extract_lookup[key]
            doc = docs[doc_i]

            # Start with existing cache data or empty structure
            if existing_cache is not None:
                cache_data = dict(existing_cache)
            else:
                cache_data = {
                    "entities": {"persons": [], "orgs": [], "locations": []},
                    "votes": {"votes": []},
                }

            # Detect section from page text
            section = detect_section(pf.text)
            if section is not None:
                meeting_context["current_section"] = section

            # Extract entities if needed
            if mode in ("entities", "all"):
                entities = _extract_entities(pf.text, doc=doc)
                cache_data["entities"] = entities
                update_context(meeting_context, entities=entities)

            # Extract votes if needed
            if mode in ("votes", "all"):
                votes = _extract_votes(pf.text, doc=doc, meeting_context=meeting_context)
                # Tag votes with current section
                current_section = meeting_context.get("current_section")
                if current_section:
                    for v in votes.get("votes", []):
                        if v.get("section") is None:
                            v["section"] = current_section
                cache_data["votes"] = votes

            # Update hash and timestamp
            cache_data["content_hash"] = hash_text_content(pf.text)
            cache_data["extracted_at"] = datetime.datetime.now().isoformat()

            save_extraction_cache(cache_file, cache_data)
            group_cache_entries.append((cache_file, cache_data))

        # Post-processing: resolve entities across the meeting group
        if mode in ("entities", "all") and group_cache_entries:
            # Accumulate all entities from this meeting group
            all_persons = []
            all_orgs = []
            all_locations = []
            for _, cd in group_cache_entries:
                ents = cd.get("entities", {})
                all_persons.extend(ents.get("persons", []))
                all_orgs.extend(ents.get("orgs", []))
                all_locations.extend(ents.get("locations", []))

            # Filter to entries with required fields for resolution
            valid_persons = [p for p in all_persons if "text" in p and "confidence" in p]
            combined = {
                "persons": valid_persons,
                "orgs": all_orgs,
                "locations": all_locations,
            }
            resolved = resolve_entities(combined, meeting_context=meeting_context)

            # Store resolved entities in a meeting-level cache entry
            # (We update the last page's cache with the resolved data for now)
            last_cache_file, last_cache_data = group_cache_entries[-1]
            last_cache_data["resolved_entities"] = resolved
            save_extraction_cache(last_cache_file, last_cache_data)

    log(
        f"Extraction complete: processed {len(pages_to_extract)} pages",
        subdomain=subdomain,
    )
    return True


def _update_extraction_status(subdomain, status):
    """Update a site's extraction_status and last_extracted in the database."""
    now = datetime.datetime.now().isoformat()
    with civic_db_connection() as conn:
        conn.execute(
            update(sites_table)
            .where(sites_table.c.subdomain == subdomain)
            .values(
                extraction_status=status,
                last_extracted=now,
            )
        )


def _run_extraction_with_status(subdomain, txt_dir, mode, rebuild):
    """Run extraction for a site and update its DB status on completion."""
    try:
        ran = _run_extraction_for_site(
            subdomain=subdomain, txt_dir=txt_dir, mode=mode, rebuild=rebuild
        )
        if ran:
            _update_extraction_status(subdomain, "completed")
    except Exception:
        _update_extraction_status(subdomain, "failed")
        raise


@extract.command()
@click.option("-s", "--subdomain", help="Site subdomain to extract from")
@click.option("-n", "--next-site", is_flag=True, help="Auto-select next site needing extraction")
@click.option("--rebuild", is_flag=True, help="Ignore cache and re-extract everything")
def entities(subdomain, next_site, rebuild):
    """Extract entities (persons, orgs, locations) from site text files."""
    _validate_site_args(subdomain, next_site)
    resolved = _resolve_subdomain(subdomain, next_site)
    if not resolved:
        return
    txt_dir = os.path.join(STORAGE_DIR, resolved, "txt")
    _run_extraction_with_status(
        subdomain=resolved, txt_dir=txt_dir, mode="entities", rebuild=rebuild
    )


@extract.command()
@click.option("-s", "--subdomain", help="Site subdomain to extract from")
@click.option("-n", "--next-site", is_flag=True, help="Auto-select next site needing extraction")
@click.option("--rebuild", is_flag=True, help="Ignore cache and re-extract everything")
def votes(subdomain, next_site, rebuild):
    """Extract vote records from site text files."""
    _validate_site_args(subdomain, next_site)
    resolved = _resolve_subdomain(subdomain, next_site)
    if not resolved:
        return
    txt_dir = os.path.join(STORAGE_DIR, resolved, "txt")
    _run_extraction_with_status(subdomain=resolved, txt_dir=txt_dir, mode="votes", rebuild=rebuild)


@extract.command(name="all")
@click.option("-s", "--subdomain", help="Site subdomain to extract from")
@click.option("-n", "--next-site", is_flag=True, help="Auto-select next site needing extraction")
@click.option("--rebuild", is_flag=True, help="Ignore cache and re-extract everything")
def all_(subdomain, next_site, rebuild):
    """Extract both entities and votes from site text files."""
    _validate_site_args(subdomain, next_site)
    resolved = _resolve_subdomain(subdomain, next_site)
    if not resolved:
        return
    txt_dir = os.path.join(STORAGE_DIR, resolved, "txt")
    _run_extraction_with_status(subdomain=resolved, txt_dir=txt_dir, mode="all", rebuild=rebuild)
