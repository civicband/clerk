# Extraction Caching Design

**Date:** 2025-12-31
**Status:** Approved
**Problem:** spaCy extraction takes 2 hours for 547k pages on every database rebuild
**Solution:** Content-hash-based extraction cache using `.extracted.json` files

## Overview

### The Problem

Currently, `build_db_from_text` runs spaCy extraction on every page every time, even when text hasn't changed. For the largest municipality (547k pages), this takes 2 hours per rebuild. Since 95% of updates are just adding new meetings, we're re-processing hundreds of thousands of unchanged pages unnecessarily.

### The Solution

Implement a content-hash-based extraction cache using `.extracted.json` files stored alongside text files. When building the database:

1. Hash each text file's content
2. Check if a matching `.extracted.json` cache file exists with the same hash
3. If yes: load cached entities/votes (instant)
4. If no: run spaCy extraction and create cache file
5. Batch all uncached pages through `nlp.pipe()` for efficiency

### Key Benefits

- **First run:** Same 2-hour cost, creates all cache files
- **Subsequent runs:** Only process new/changed pages (typically minutes instead of hours)
- **95% of updates:** ~100x faster (only new meetings processed)
- **5% bulk reprocessing:** Handled automatically (hash mismatch triggers re-extraction)
- **Cache survives database rebuilds:** Lives next to source data
- **Simple rollback:** Delete `.extracted.json` files to revert to full processing

## Cache File Format & Storage

### File Location

Cache files live alongside text files with `.extracted.json` extension:

```
{subdomain}/txt/2024-01-15-meeting-page-001.txt
{subdomain}/txt/2024-01-15-meeting-page-001.txt.extracted.json
{subdomain}/_agendas/txt/agenda-page-001.txt
{subdomain}/_agendas/txt/agenda-page-001.txt.extracted.json
```

### Cache File Structure

```json
{
  "content_hash": "abc123def456...",
  "model_version": "en_core_web_md",
  "extracted_at": "2025-12-31T12:00:00Z",
  "entities": {
    "persons": ["John Doe", "Jane Smith"],
    "orgs": ["City Council"],
    "locations": ["City Hall"]
  },
  "votes": {
    "votes": [
      {
        "motion": "Approve budget",
        "result": "passed",
        "voters": {...}
      }
    ]
  }
}
```

### Hashing Strategy

Reuse existing approach - hash the text content (same as record ID generation):

```python
content_hash = sha256(text.encode('utf-8')).hexdigest()
```

This means:
- When text changes, both record ID and cache hash change
- Consistent with existing behavior
- Simple implementation

### Cache Invalidation Triggers

- Text content changes (hash mismatch)
- Cache file missing or corrupted JSON
- spaCy model version changes (optional - use `--force-extraction` instead)
- Manual `--force-extraction` flag

## Processing Flow

### Phase 1: Scan and Categorize Pages

```python
cached_pages = []      # Has valid .extracted.json with matching hash
uncached_pages = []    # Needs spaCy processing

for page_file in text_files:
    text = read_file(page_file)
    content_hash = sha256(text.encode('utf-8')).hexdigest()
    cache_file = f"{page_file}.extracted.json"

    if cache_exists_and_valid(cache_file, content_hash):
        # Load cached extraction
        cached_data = load_cache(cache_file)
        cached_pages.append({...cached_data, text, page_num...})
    else:
        # Needs extraction
        uncached_pages.append({text, page_num, cache_file, hash...})
```

### Phase 2: Batch Process Uncached Pages

```python
if uncached_pages:
    texts = [p['text'] for p in uncached_pages]
    docs = nlp.pipe(texts, batch_size=500, n_process=N)  # Fast batch processing

    for page_data, doc in zip(uncached_pages, docs):
        entities = extract_entities(text, doc=doc)
        votes = extract_votes(text, doc=doc, context=ctx)

        # Write cache file
        save_cache(page_data['cache_file'], {
            'content_hash': page_data['hash'],
            'model_version': nlp.meta['version'],
            'extracted_at': now(),
            'entities': entities,
            'votes': votes
        })
```

### Phase 3: Merge and Insert

Combine cached + newly extracted pages, insert into database as before.

## Testability, Observability & Scale

### Testability

- **Unit tests:** Mock file I/O, test cache validation logic independently
- **Integration tests:** Create temp text files + cache files, verify cache hit/miss behavior
- **Test helpers:** `create_cache_file(text, entities, votes)` for easy test setup
- **Parameterized tests:** Test with cache hit, cache miss, corrupted cache, hash mismatch
- **Extraction toggle:** Works with existing `ENABLE_EXTRACTION` flag

### Observability

Use the centralized `log()` function from `.output`:

```python
log(f"Scanning {total_files} text files...", subdomain=subdomain)

# Progress during scan (every 5000 files):
log(f"Scanned {scanned}/{total_files} files, {cache_hits} cached...",
    subdomain=subdomain)

log(f"Cache hits: {len(cached_pages)}, needs extraction: {len(uncached_pages)}",
    subdomain=subdomain,
    cache_hits=len(cached_pages),
    needs_extraction=len(uncached_pages))

log(f"Processing {len(uncached_pages)} pages with spaCy...", subdomain=subdomain)

# Every 1000 pages during extraction:
log(f"Extracted {processed}/{total_uncached} pages...",
    subdomain=subdomain,
    progress=f"{processed}/{total_uncached}")

log(f"Build completed in {elapsed:.2f}s ({cached_pct}% from cache)",
    subdomain=subdomain,
    elapsed_time=f"{elapsed:.2f}",
    cache_hit_rate=cached_pct)
```

Debug logging for cache issues:
```python
logger.debug(f"Cache miss for {file}: {reason}")
```

### Memory Management

- **Stream through pages:** Load cache on-demand, don't hold all in memory
- **Process uncached pages in chunks:** If > 100k uncached pages, batch in chunks of 10k through spaCy
- **Reuse existing batching pattern:** Already batching with progress updates every 1000 pages

## Error Handling & Edge Cases

### Cache File Corruption

```python
def load_cache(cache_file, expected_hash):
    try:
        with open(cache_file) as f:
            data = json.load(f)

        # Validate structure
        required_keys = {'content_hash', 'entities', 'votes'}
        if not required_keys.issubset(data.keys()):
            logger.debug(f"Cache invalid: missing keys in {cache_file}")
            return None

        # Validate hash match
        if data['content_hash'] != expected_hash:
            logger.debug(f"Cache invalid: hash mismatch in {cache_file}")
            return None

        return data
    except (json.JSONDecodeError, FileNotFoundError, KeyError) as e:
        logger.debug(f"Cache invalid: {e} in {cache_file}")
        return None
```

### Partial Extraction Failures

If spaCy fails on individual pages during batch processing:

- Use centralized logging: `log(f"Entity extraction failed for {page_file}", subdomain=subdomain, level="warning", error=str(e))`
- Store empty extraction in cache: `{"entities": {"persons": [], "orgs": [], "locations": []}, "votes": {"votes": []}}`
- Don't fail entire rebuild - continue with remaining pages
- Cache the failure so we don't retry same broken page every time (unless text changes)

### Disk Space Management

- Cache files are small (~1-5KB each for typical pages)
- 547k pages × 3KB average = ~1.6GB cache storage
- No automatic cleanup (cache files are valuable!)
- Manual cleanup: delete `.extracted.json` files if needed

### `--force-extraction` Flag

```bash
clerk build-db-from-text --subdomain example.civic.band --force-extraction
```

Behavior:
- Ignores all cache files
- Processes every page with spaCy
- Overwrites existing cache files with fresh results
- Use cases: model upgrade, debugging, suspected cache corruption

## Migration & Deployment

### Backwards Compatibility

- No database schema changes needed
- Works with existing text file structure
- `ENABLE_EXTRACTION` flag behavior unchanged
- If extraction disabled, no cache files created (graceful degradation)

### First Run After Deployment

For each site:
1. No `.extracted.json` files exist yet
2. `build_table_from_text` processes all pages with spaCy (normal 2-hour cost)
3. Creates cache files for all pages
4. Database built as normal

### Subsequent Runs

1. Scan finds most pages have valid cache (95%+ cache hit rate for typical updates)
2. Only new/changed pages processed with spaCy (minutes instead of hours)
3. New cache files created only for uncached pages

### Deployment Strategy

- **No migration script needed** - feature is opt-in via presence of cache files
- **Gradual rollout:** Deploy to one site first, verify performance improvement
- **Monitoring:** Watch logs for cache hit rates, extraction times
- **Rollback:** If issues arise, delete `.extracted.json` files (system falls back to full processing)

### Cache Lifecycle

- **Created:** During `build_table_from_text` when page needs extraction
- **Updated:** When text content changes (hash mismatch)
- **Deleted:** Manual cleanup only (or `--force-extraction` overwrites)
- **Never expires:** Cache valid indefinitely unless text/model changes

## Implementation Notes

### Files to Modify

- `src/clerk/utils.py` - Update `build_table_from_text()` with cache logic
- `src/clerk/cli.py` - Add `--force-extraction` flag to `build-db-from-text` command
- `tests/test_utils.py` - Add cache validation tests
- `tests/test_integration.py` - Add end-to-end cache behavior tests

### Key Functions to Add

- `load_extraction_cache(cache_file, expected_hash) -> dict | None`
- `save_extraction_cache(cache_file, data) -> None`
- `hash_text_content(text) -> str`

### Performance Expectations

- **First run (547k pages):** 2 hours (unchanged)
- **Typical update (500 new pages):** ~1-2 minutes (vs 2 hours)
- **Bulk reprocess (50k changed pages):** ~10-15 minutes (vs 2 hours)
- **Cache overhead:** Negligible (1.6GB disk, instant file reads)

## Success Criteria

- First database rebuild creates cache files for all pages
- Subsequent rebuilds skip cached pages (verified via logs)
- Cache hit rate > 95% for typical updates
- Processing time reduced from hours to minutes for incremental updates
- All existing tests pass
- New tests cover cache hit/miss/corruption scenarios
