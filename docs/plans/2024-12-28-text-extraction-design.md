# Text Extraction Pipeline Design

## Overview

Add entity and vote extraction to the clerk text processing pipeline. Extract names, organizations, locations, and vote records as structured JSON during the existing `build_table_from_text()` flow.

## Goals

- Extract persons, organizations, and locations using spaCy NER
- Extract vote records (motions, tallies, individual votes) using regex
- Maintain O(Cn) time complexity (linear scaling, ~2x current time acceptable)
- Include confidence scores for entity extraction
- Support iterative tuning without code changes

## Architecture

### Inline Extraction

Extraction happens during `build_table_from_text()` as each page is read. No separate pass needed.

### New Columns

Add to minutes/agendas tables:
- `entities_json TEXT` - Names, organizations, locations with confidence scores
- `votes_json TEXT` - Vote records with tallies and individual votes

### Why JSON Columns

- Single pass through text = O(n)
- SQLite JSON functions allow querying
- Easy to iterate on format without migrations
- Can normalize into separate tables later if needed

## Entity Extraction

### Model

Use `en_core_web_trf` (transformer model):
- ~400MB model, one-time download
- ~150ms per page (acceptable)
- Confidence scores included

### Output Format

```json
{
  "persons": [
    {"text": "Kathy Weber", "confidence": 0.94},
    {"text": "Tito Villasenor", "confidence": 0.89}
  ],
  "orgs": [
    {"text": "Downtown Alameda Businesses Association", "confidence": 0.87}
  ],
  "locations": [
    {"text": "Park St", "confidence": 0.62}
  ]
}
```

### Configurable Threshold

`ENTITY_CONFIDENCE_THRESHOLD` env var (default 0.7) for filtering.

## Vote Extraction

### Patterns

- Simple: `"passed 7-0"`, `"approved 5-2"`, `"motion carried unanimously"`
- Roll call: `"Ayes: Smith, Jones, Lee. Nays: Brown."`
- Verbose: `"Member Smith: Aye. Member Jones: Aye. Member Brown: Nay."`

### Output Format

```json
{
  "votes": [
    {
      "motion_by": "Teague",
      "seconded_by": "Curtis",
      "result": "passed",
      "tally": {
        "ayes": 7,
        "nays": 0,
        "abstain": null,
        "absent": null
      },
      "individual_votes": [
        {"name": "Teague", "vote": "aye"},
        {"name": "Curtis", "vote": "aye"},
        {"name": "Smith", "vote": "nay"}
      ],
      "raw_text": "A roll call vote was taken and the motion passed 7-0."
    }
  ]
}
```

## Meeting Context

### Problem

Council members are often defined in a roll call early in the document, but votes happen later. Context helps resolve partial names and validate vote attributions.

### Solution

Accumulate context as pages are processed within each meeting:

```python
meeting_context = {
    "known_persons": set(),      # Names seen so far
    "known_orgs": set(),         # Organizations mentioned
    "attendees": [],             # From roll call detection
    "meeting_type": None,        # "City Council", etc.
}
```

### Roll Call Detection

Patterns like:
- `"Present: Smith, Jones, Lee, Brown, Garcia"`
- `"Roll Call: Members present were..."`
- `"Attending: Council Member Smith, Council Member Jones..."`

When detected, populate `attendees` list with higher confidence than general PERSON extraction.

### Context Usage

Vote extraction cross-references names against known attendees for better matching.

## Integration

### Code Location

New file `src/clerk/extraction.py`:
- `get_nlp()` - Lazy model loader
- `extract_entities(text, threshold=0.7)` - spaCy NER
- `extract_votes(text, meeting_context)` - Regex + context matching
- `detect_roll_call(text)` - Returns attendees list

### Flow in build_table_from_text()

```python
for meeting_date in meeting_dates:
    meeting_context = {"known_persons": set(), "attendees": []}

    for page in sorted(pages):
        text = page_file.read()

        entities = extract_entities(text)
        meeting_context["known_persons"].update(
            p["text"] for p in entities["persons"]
        )

        votes = extract_votes(text, meeting_context)

        key_hash.update({
            # ... existing fields ...
            "entities_json": json.dumps(entities),
            "votes_json": json.dumps(votes),
        })
```

### Model Loading

Load once at module level, not per-page:

```python
_nlp = None

def get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_trf")
    return _nlp
```

## Error Handling

- spaCy fails to load → Log error, skip extraction, still save text
- Regex finds no votes → `votes_json` = `{"votes": []}` (empty, not null)
- Confidence below threshold → Store with `"filtered": true` flag

## Dependencies

```toml
[project.optional-dependencies]
extraction = [
    "spacy>=3.5.0",
]
```

Post-install: `python -m spacy download en_core_web_trf`

## Testing

### Unit Tests

- Entity extraction with sample text
- Vote patterns (simple, roll call, verbose)
- Roll call detection
- Context accumulation across pages

### Performance

- Verify <200ms per page average
- No memory leaks from model reloading

### Feature Flag

`ENABLE_EXTRACTION=1` env var to toggle during rollout. Default off.

## Future Iterations

- Track "current agenda item" from headers
- Normalize to separate tables if query patterns demand it
- Fine-tune spaCy model on civic meeting data if accuracy needs improvement
