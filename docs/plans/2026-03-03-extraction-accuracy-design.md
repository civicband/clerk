# Enhanced Extraction Pipeline Design

**Date:** 2026-03-03
**Goal:** Improve entity and vote extraction accuracy — better recall, fewer false positives, name resolution, entity categorization, and vote topic/item extraction.

## Approach: Enhanced spaCy Pipeline + Post-Processing Resolution

Stay local-only (no LLM API calls). Upgrade spaCy usage, add vote topic extraction, and add a post-processing entity resolution step.

---

## 1. Model Upgrade with Smart Selection

- Default to `en_core_web_md` for fast batch processing
- Add `en_core_web_trf` (transformer/RoBERTa) as opt-in via `SPACY_MODEL` env var
- Consider auto-escalation: retry with `trf` on pages where `md` extracts few entities or has low confidence
- Adjust batch sizes for `trf` (~50-100 instead of 500) due to higher memory usage

## 2. Vote Topic/Item Extraction

New fields on vote records: `agenda_item_ref`, `topic`, `section`.

### Agenda Item Reference Extraction
- PhraseMatcher + regex for formal identifiers:
  - `Ordinance \d+-\d+`, `Resolution \d+-\d+`, `Item \d+(\.\d+)?`
  - `Consent Calendar Item \d+`, `Public Hearing \d+`
- Search the sentence containing the vote AND the preceding 2-3 sentences
- Structured output: `{"type": "ordinance", "number": "2024-15"}`

### Natural Language Topic Extraction
- Use spaCy dependency parsing to extract the object of the motion verb (`dobj`/`xcomp` of "moved"/"approved")
- If vote sentence is terse (just "passed 7-0"), look at preceding sentence or paragraph heading
- Truncate to ~150 chars max
- Example: "Motion to approve the downtown parking structure plan" -> topic: "downtown parking structure plan"

### Section Detection
- Regex for section headers: "CONSENT CALENDAR", "PUBLIC HEARING", "NEW BUSINESS", "OLD BUSINESS", "ACTION ITEMS"
- Track current section as state across pages within a meeting
- Associate each vote with its section

## 3. Entity Resolution (Post-Processing)

Run after extracting entities from all pages in a meeting.

### Name Merging
- Strip civic titles to get base names: "Councilmember John Smith" -> "John Smith"
- Group variants by exact last-name match + fuzzy first-name match (handle initials)
- Output: `{"canonical": "John Smith", "variants": ["Smith", "Councilmember Smith"], "count": 14}`

### Entity Categorization
- `elected_official`: appears in roll call or has elected title (Mayor, Councilmember, Supervisor, etc.)
- `staff`: has staff title (City Manager, City Attorney, Director, Clerk)
- `public`: appears only in public comment sections or with no title
- `organization`: ORG entities

## 4. Updated Data Model

### Vote Record (new fields)
```python
{
    "motion_by": "Smith",
    "seconded_by": "Jones",
    "result": "passed",
    "tally": {"ayes": 7, "nays": 0, "abstain": None, "absent": None},
    "individual_votes": [...],
    "raw_text": "...",
    "agenda_item_ref": {"type": "ordinance", "number": "2024-15"},  # NEW
    "topic": "downtown parking structure plan",                       # NEW
    "section": "public_hearing",                                      # NEW
}
```

### Entity Result (new fields)
```python
{
    "persons": [
        {
            "text": "John Smith",
            "confidence": 0.85,
            "category": "elected_official",           # NEW
            "variants": ["Smith", "Councilmember Smith"],  # NEW
        }
    ],
    "orgs": [...],
    "locations": [...],
}
```

Cache format is backward-compatible — new fields are additive.

## 5. Implementation Phases

1. **Vote topic extraction** — highest user value, independent of other changes
2. **Entity resolution** — name merging + categorization post-processing
3. **Model upgrade** — `en_core_web_trf` opt-in with `SPACY_MODEL` env var
4. **Section detection** — lightweight, adds context to votes
5. **Auto-escalation** — retry hard pages with `trf` model (optional/future)

## Files Affected

- `src/clerk/extraction.py` — new matchers, topic extraction, entity resolution
- `src/clerk/extract_cli.py` — wire up resolution post-processing, model selection
- `src/clerk/utils.py` — possible cache format updates
- `tests/test_extraction.py` — new test cases for all features
