# Extract Command Group Design

## Summary

Rework entity and vote extraction into a standalone `clerk extract` command group, remove inline extraction from DB compilation, and clean up dormant pipeline code.

## Motivation

Currently extraction can happen three ways: standalone CLI command, inline during DB compilation (`--extract-entities`), and via a dormant RQ pipeline job. This creates confusion about when and how extraction runs. The new design makes extraction an explicit, separate step with its own command group, while DB compilation simply picks up cached results.

## New CLI Commands

```
clerk extract entities --subdomain <name> [--rebuild]
clerk extract entities --next-site [--rebuild]
clerk extract votes --subdomain <name> [--rebuild]
clerk extract votes --next-site [--rebuild]
clerk extract all --subdomain <name> [--rebuild]
clerk extract all --next-site [--rebuild]
```

- **entities**: Extract persons, orgs, locations from all text pages
- **votes**: Extract vote records from all text pages
- **all**: Run both entity and vote extraction
- **--rebuild**: Ignore existing `.extracted.json` cache, re-extract everything
- **--subdomain**: Target a specific site
- **--next-site**: Auto-scheduler picks next site needing extraction

### Cache behavior

Cache files (`.extracted.json`) store both entities and votes. When running a single extraction type:
- If cache exists: update only the relevant section while preserving the other
- If no cache: create cache with only the extracted section populated

## DB Compilation Changes

`build-db-from-text` becomes a pure data-assembly step:
- Remove `--extract-entities` flag
- Remove `--ignore-cache` flag
- Always read `.extracted.json` cache if it exists and hash matches
- If no cache or hash mismatch: entities_json and votes_json are empty
- No spaCy imports or extraction calls during compilation

## Code Changes

### New: `src/clerk/extract_cli.py`
- `extract` click group with `entities`, `votes`, `all` subcommands
- Extraction orchestration: iterate text files, check cache, batch parse with spaCy, extract, save cache
- Registered in `cli.py`

### Modified: `src/clerk/utils.py`
- `build_table_from_text()`: remove `extract_entities` and `ignore_cache` params
- Remove Phase 2 (batch spaCy parsing)
- Simplify Phase 3: read cache if exists, otherwise empty entities/votes
- Keep shared cache utilities (`load_extraction_cache`, `hash_text_content`, `save_extraction_cache`)

### Modified: `src/clerk/cli.py`
- Remove `--extract-entities` and `--ignore-cache` from `build-db-from-text`
- Remove standalone `extract-entities` command
- Remove `fix-extraction-stage` command
- Register new `extract` group

### Modified: `src/clerk/workers.py`
- Remove dormant `extraction_job()` function
- Remove commented-out extraction enqueuing from `ocr_complete_coordinator`
- Remove `extract_entities_internal()` if present

### Unchanged: `src/clerk/extraction.py`
- Core extraction logic (spaCy NER, vote pattern matching) stays as-is
