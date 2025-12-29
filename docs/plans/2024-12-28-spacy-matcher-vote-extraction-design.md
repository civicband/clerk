# spaCy Matcher Vote Extraction Design

## Overview

Enhance vote extraction to use spaCy's Matcher and DependencyMatcher instead of pure regex. This improves both coverage (handling phrasing variations) and accuracy (understanding sentence structure for attribution).

## Goals

- Capture votes in varied phrasing that regex misses
- Accurately extract who moved/seconded via syntactic analysis
- Maintain graceful degradation when spaCy unavailable
- Single parse per page (optimize by reusing doc from entity extraction)

## Architecture

### Hybrid Approach

**Token Matcher** for vote result detection:
- Structurally simple patterns
- Match on lemmas: "pass/passed/passes" all match `{"LEMMA": "pass"}`
- Handles tally votes, unanimous votes, voice votes

**DependencyMatcher** for motion attribution:
- Syntactic relationship patterns
- Find subject of verbs "move" and "second"
- Disambiguate: "Smith moved approval" vs "Smith moved to Oakland"

### Fallback Logic

```python
def extract_votes(text, doc=None, meeting_context=None):
    if doc is None:
        doc = parse_text(text)

    if doc is not None:
        return _extract_votes_spacy(doc, meeting_context)
    else:
        return _extract_votes_regex(text, meeting_context)
```

## Token Matcher Patterns

### Pattern 1: Tally Votes

Matches: "passed 7-0", "carried 5-2", "was approved 6-1"

```python
[
    {"LEMMA": {"IN": ["pass", "carry", "approve", "defeat", "fail", "reject"]}},
    {"LIKE_NUM": True},
    {"TEXT": "-"},
    {"LIKE_NUM": True},
]
```

### Pattern 2: Unanimous Votes

Matches: "passed unanimously", "was unanimously approved", "carried by unanimous vote"

```python
# Order 1: verb then unanimously
[
    {"LEMMA": {"IN": ["pass", "carry", "approve"]}},
    {"LOWER": "unanimously"},
]

# Order 2: unanimously then verb
[
    {"LOWER": "unanimously"},
    {"LEMMA": {"IN": ["pass", "carry", "approve"]}},
]

# Alternate phrasing
[
    {"LOWER": "unanimous"},
    {"LOWER": "vote"},
]
```

### Pattern 3: Voice Vote

Matches: "by voice vote", "on a voice vote"

```python
[
    {"LOWER": {"IN": ["by", "on"]}},
    {"OP": "?"},  # optional "a"
    {"LOWER": "voice"},
    {"LOWER": "vote"},
]
```

## DependencyMatcher Patterns

### Pattern 1: Active Voice Motion

Matches: "Smith moved approval", "Jones seconded the motion"

```python
[
    {"RIGHT_ID": "verb", "RIGHT_ATTRS": {"LEMMA": {"IN": ["move", "second"]}}},
    {"LEFT_ID": "verb", "REL_OP": ">", "RIGHT_ID": "subject",
     "RIGHT_ATTRS": {"DEP": "nsubj"}},
]
```

### Pattern 2: Passive Voice Motion

Matches: "moved by Smith", "seconded by Councilmember Jones"

```python
[
    {"RIGHT_ID": "verb", "RIGHT_ATTRS": {"LEMMA": {"IN": ["move", "second"]}}},
    {"LEFT_ID": "verb", "REL_OP": ">", "RIGHT_ID": "agent",
     "RIGHT_ATTRS": {"DEP": "agent"}},
]
```

### Disambiguation Filter

After matching, verify the verb's object contains motion-related words:

```python
MOTION_OBJECTS = {
    "motion", "resolution", "approval", "item", "amendment",
    "ordinance", "measure", "recommendation", "action",
}
```

If "move" has object like "to Oakland" → discard match.
If object is "approval" or "the motion" → keep match.

## Single-Parse Optimization

Parse text once and pass doc to all extraction functions:

```python
def parse_text(text: str):
    """Parse text with spaCy, returning doc or None if unavailable."""
    if not EXTRACTION_ENABLED:
        return None
    nlp = get_nlp()
    if nlp is None:
        return None
    try:
        return nlp(text)
    except Exception as e:
        logger.error(f"spaCy processing failed: {e}")
        return None

# Updated signatures
def extract_entities(text: str, doc=None, threshold=None) -> dict:
    ...

def extract_votes(text: str, doc=None, meeting_context=None) -> dict:
    ...

# Usage in build_table_from_text:
doc = parse_text(text)
entities = extract_entities(text, doc=doc)
votes = extract_votes(text, doc=doc, meeting_context=context)
```

## Error Handling

### Matcher Initialization

```python
_vote_matcher = None
_motion_matcher = None

def _get_matchers(nlp):
    """Initialize matchers lazily, once per session."""
    global _vote_matcher, _motion_matcher

    if _vote_matcher is None:
        _vote_matcher = Matcher(nlp.vocab)
        # Add patterns...

        _motion_matcher = DependencyMatcher(nlp.vocab)
        # Add patterns...

    return _vote_matcher, _motion_matcher
```

### Graceful Degradation Chain

1. spaCy available + model loaded → Use Matcher/DependencyMatcher
2. spaCy available but matcher fails → Log warning, fall back to regex
3. spaCy unavailable → Use regex directly
4. Regex fails → Return empty `{"votes": []}`, never crash

### Specific Cases

- DependencyMatcher finds no subject → Record vote without attribution
- Disambiguation filter rejects all matches → Fall through to regex
- Multiple votes on same page → Each extracted independently

## Testing

### Token Matcher Tests

```python
def test_tally_vote_variations():
    cases = [
        ("The motion passed 7-0.", {"result": "passed", "ayes": 7, "nays": 0}),
        ("It was approved 5-2.", {"result": "passed", "ayes": 5, "nays": 2}),
        ("The measure carried 6-1.", {"result": "passed", "ayes": 6, "nays": 1}),
        ("Motion defeated 2-5.", {"result": "failed", "ayes": 2, "nays": 5}),
    ]

def test_unanimous_variations():
    cases = [
        "passed unanimously",
        "was unanimously approved",
        "carried by unanimous vote",
    ]
```

### DependencyMatcher Tests

```python
def test_motion_attribution_active():
    cases = [
        ("Smith moved approval.", {"motion_by": "Smith"}),
        ("Councilmember Jones moved the item.", {"motion_by": "Jones"}),
    ]

def test_motion_attribution_passive():
    cases = [
        ("Moved by Smith.", {"motion_by": "Smith"}),
        ("Seconded by Jones.", {"seconded_by": "Jones"}),
    ]

def test_disambiguation_rejects_non_motions():
    text = "The company moved to Oakland last year."
    result = extract_votes(text)
    assert result["votes"] == []
```

### Fallback Tests

```python
def test_regex_fallback_when_spacy_unavailable(monkeypatch):
    monkeypatch.setattr("clerk.extraction.get_nlp", lambda: None)
    result = extract_votes("passed 7-0")
    assert result["votes"][0]["tally"]["ayes"] == 7
```

## Implementation Status

Implemented. Key components:

- `parse_text()` - Single-parse optimization, parses text once for reuse
- `_get_vote_matcher()` - Token Matcher for vote results (tally, unanimous, voice)
- `_get_motion_matcher()` - DependencyMatcher for motion attribution
- `_extract_vote_results_spacy()` - Token Matcher extraction
- `_extract_motion_attribution_spacy()` - DependencyMatcher extraction with disambiguation
- `_extract_rollcall_votes()` - Shared roll-call extraction (regex, works well)
- `_extract_votes_spacy()` - Integrated spaCy extraction
- `_extract_votes_regex()` - Regex fallback
- `extract_votes()` - Main entry point with doc parameter and fallback logic

### Usage

```python
from clerk.extraction import parse_text, extract_entities, extract_votes

# Parse once, use for both
doc = parse_text(text)
entities = extract_entities(text, doc=doc)
votes = extract_votes(text, doc=doc, meeting_context=context)
```

### Configuration

Same as base extraction:
- `ENABLE_EXTRACTION=1` to enable
- `ENTITY_CONFIDENCE_THRESHOLD=0.7` for entity filtering
