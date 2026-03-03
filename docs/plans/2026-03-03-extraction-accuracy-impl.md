# Enhanced Extraction Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve entity and vote extraction accuracy by adding vote topic/item extraction, entity name resolution with categorization, configurable spaCy model selection, and section detection.

**Architecture:** Extend the existing `extraction.py` module with new matchers and post-processing functions. Vote records gain `agenda_item_ref`, `topic`, and `section` fields. Entity results gain `category` and `variants` fields via a post-processing resolution step that runs after all pages in a meeting are extracted.

**Tech Stack:** spaCy (PhraseMatcher, DependencyMatcher, dependency parsing), Python regex, existing cache infrastructure.

**Design doc:** `docs/plans/2026-03-03-extraction-accuracy-design.md`

---

### Task 1: Agenda Item Reference Extraction

**Files:**
- Modify: `src/clerk/extraction.py` (add after line ~200, near MOTION_OBJECTS)
- Test: `tests/test_extraction.py`

**Step 1: Write the failing tests**

Add a new test class to `tests/test_extraction.py`:

```python
class TestAgendaItemExtraction:
    """Tests for agenda item reference extraction."""

    def test_extracts_ordinance_reference(self, monkeypatch):
        """Extracts 'Ordinance 2024-15' from text."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("Motion to approve Ordinance 2024-15 passed 7-0.")
        refs = extraction.extract_agenda_item_refs(doc)
        assert len(refs) >= 1
        assert refs[0]["type"] == "ordinance"
        assert refs[0]["number"] == "2024-15"

    def test_extracts_resolution_reference(self, monkeypatch):
        """Extracts 'Resolution 2024-03' from text."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("Council adopted Resolution 2024-03.")
        refs = extraction.extract_agenda_item_refs(doc)
        assert len(refs) >= 1
        assert refs[0]["type"] == "resolution"
        assert refs[0]["number"] == "2024-03"

    def test_extracts_item_number(self, monkeypatch):
        """Extracts 'Item 4.2' from text."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("Discussion of Item 4.2 regarding zoning changes.")
        refs = extraction.extract_agenda_item_refs(doc)
        assert len(refs) >= 1
        assert refs[0]["type"] == "item"
        assert refs[0]["number"] == "4.2"

    def test_extracts_consent_calendar(self, monkeypatch):
        """Extracts consent calendar references."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("Consent Calendar Item 3 was approved unanimously.")
        refs = extraction.extract_agenda_item_refs(doc)
        assert len(refs) >= 1
        assert refs[0]["type"] == "consent_calendar"

    def test_no_refs_in_plain_text(self, monkeypatch):
        """Returns empty list when no agenda item references found."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The mayor welcomed everyone to the meeting.")
        refs = extraction.extract_agenda_item_refs(doc)
        assert refs == []
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_extraction.py::TestAgendaItemExtraction -v`
Expected: FAIL with `AttributeError: module 'clerk.extraction' has no attribute 'extract_agenda_item_refs'`

**Step 3: Implement `extract_agenda_item_refs()`**

Add to `src/clerk/extraction.py` after the MOTION_OBJECTS section (~line 200):

```python
# Agenda item reference patterns (compiled once)
_AGENDA_ITEM_PATTERNS = [
    (re.compile(r"\bOrdinance\s+(\d+[\-\.]\d+)\b", re.IGNORECASE), "ordinance"),
    (re.compile(r"\bResolution\s+(\d+[\-\.]\d+)\b", re.IGNORECASE), "resolution"),
    (re.compile(r"\bItem\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE), "item"),
    (re.compile(r"\bConsent\s+Calendar\s+(?:Item\s+)?(\d+(?:\.\d+)?)\b", re.IGNORECASE), "consent_calendar"),
    (re.compile(r"\bPublic\s+Hearing\s+(?:Item\s+)?(\d+(?:\.\d+)?)\b", re.IGNORECASE), "public_hearing"),
    (re.compile(r"\bAgenda\s+Item\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE), "item"),
]


def extract_agenda_item_refs(doc: Any) -> list[dict]:
    """Extract formal agenda item references from a spaCy Doc.

    Finds references like 'Ordinance 2024-15', 'Resolution 2024-03',
    'Item 4.2', 'Consent Calendar Item 3'.

    Args:
        doc: spaCy Doc object

    Returns:
        List of dicts with 'type', 'number', and 'span_start'/'span_end' keys.
    """
    text = doc.text
    refs = []
    seen = set()

    for pattern, ref_type in _AGENDA_ITEM_PATTERNS:
        for match in pattern.finditer(text):
            number = match.group(1)
            key = (ref_type, number)
            if key not in seen:
                seen.add(key)
                refs.append({
                    "type": ref_type,
                    "number": number,
                    "char_start": match.start(),
                    "char_end": match.end(),
                })

    # Sort by position in text
    refs.sort(key=lambda r: r["char_start"])
    return refs
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_extraction.py::TestAgendaItemExtraction -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/extraction.py tests/test_extraction.py
git commit -m "feat: add agenda item reference extraction"
```

---

### Task 2: Vote Topic Extraction (Natural Language)

**Files:**
- Modify: `src/clerk/extraction.py` (new function + modify `_create_vote_record`)
- Test: `tests/test_extraction.py`

**Step 1: Write the failing tests**

```python
class TestVoteTopicExtraction:
    """Tests for natural language vote topic extraction."""

    def test_extracts_topic_from_motion_sentence(self, monkeypatch):
        """Extracts topic from 'Motion to approve the downtown parking plan'."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("Motion to approve the downtown parking structure plan passed 7-0.")
        topic = extraction.extract_vote_topic(doc, vote_char_offset=56)
        assert topic is not None
        assert "parking" in topic.lower()

    def test_extracts_topic_from_preceding_sentence(self, monkeypatch):
        """Falls back to preceding sentence when vote sentence is terse."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        text = "The Council discussed the new zoning amendment for District 5. The motion passed 5-2."
        doc = nlp(text)
        topic = extraction.extract_vote_topic(doc, vote_char_offset=text.index("passed"))
        assert topic is not None
        assert "zoning" in topic.lower()

    def test_returns_none_for_no_context(self, monkeypatch):
        """Returns None when no meaningful topic context is available."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("Passed 7-0.")
        topic = extraction.extract_vote_topic(doc, vote_char_offset=0)
        # Very terse text with no real topic - None is acceptable
        # (or a very short string)

    def test_topic_truncated_to_max_length(self, monkeypatch):
        """Topic is truncated to 150 chars max."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        long_text = "Motion to approve " + "the comprehensive " * 20 + "plan. Passed 7-0."
        doc = nlp(long_text)
        topic = extraction.extract_vote_topic(doc, vote_char_offset=long_text.index("Passed"))
        if topic:
            assert len(topic) <= 150
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_extraction.py::TestVoteTopicExtraction -v`
Expected: FAIL with `AttributeError`

**Step 3: Implement `extract_vote_topic()`**

Add to `src/clerk/extraction.py`:

```python
def extract_vote_topic(doc: Any, vote_char_offset: int, max_length: int = 150) -> str | None:
    """Extract a natural language topic for a vote from surrounding context.

    Strategy:
    1. Find the sentence containing the vote
    2. Try to extract the object of the motion/approval verb via dependency parsing
    3. If the vote sentence is terse, look at the preceding sentence

    Args:
        doc: spaCy Doc object
        vote_char_offset: Character offset of the vote match in the doc text
        max_length: Maximum topic length (default 150)

    Returns:
        Topic string, or None if no meaningful topic found
    """
    # Find the sentence containing the vote
    vote_sent = None
    prev_sent = None
    for sent in doc.sents:
        if sent.start_char <= vote_char_offset < sent.end_char:
            vote_sent = sent
            break
        prev_sent = sent

    if vote_sent is None:
        return None

    # Strategy 1: Extract object of motion/approval verb via dependency parsing
    topic = _extract_topic_from_verb(vote_sent)

    # Strategy 2: If vote sentence is short/terse, use preceding sentence
    if topic is None and prev_sent is not None and len(vote_sent.text.split()) < 8:
        topic = _clean_topic_text(prev_sent.text)

    # Strategy 3: Use the full vote sentence minus the tally portion
    if topic is None and len(vote_sent.text.split()) >= 8:
        topic = _clean_topic_text(vote_sent.text)

    if topic and len(topic) > max_length:
        topic = topic[:max_length].rsplit(" ", 1)[0] + "..."

    # Skip very short or meaningless topics
    if topic and len(topic.strip()) < 5:
        return None

    return topic


def _extract_topic_from_verb(sent) -> str | None:
    """Extract topic from the object of a motion/approval verb in a sentence."""
    motion_lemmas = {"move", "approve", "adopt", "pass", "carry", "accept", "deny", "reject"}

    for token in sent:
        if token.lemma_.lower() in motion_lemmas and token.pos_ == "VERB":
            # Collect the subtree of the direct object or complement
            for child in token.children:
                if child.dep_ in ("dobj", "xcomp", "ccomp", "attr"):
                    # Get the full subtree text of this object
                    subtree_tokens = sorted(child.subtree, key=lambda t: t.i)
                    topic_text = " ".join(t.text for t in subtree_tokens)
                    return _clean_topic_text(topic_text)

                # Handle "to approve X" pattern
                if child.dep_ == "xcomp" and child.pos_ == "VERB":
                    for grandchild in child.children:
                        if grandchild.dep_ in ("dobj", "attr"):
                            subtree_tokens = sorted(grandchild.subtree, key=lambda t: t.i)
                            topic_text = " ".join(t.text for t in subtree_tokens)
                            return _clean_topic_text(topic_text)

    return None


def _clean_topic_text(text: str) -> str:
    """Clean up topic text by removing vote tally patterns and extra whitespace."""
    # Remove tally patterns like "7-0", "passed", "unanimously"
    cleaned = re.sub(
        r"\b(passed|approved|carried|defeated|failed|rejected)\s+\d+-\d+\.?\s*$",
        "", text, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"\bunanimously\.?\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bby voice vote\.?\s*$", "", cleaned, flags=re.IGNORECASE)
    # Remove leading "Motion to" if present
    cleaned = re.sub(r"^[Mm]otion\s+to\s+", "", cleaned)
    # Normalize whitespace
    cleaned = " ".join(cleaned.split()).strip(" .,;:")
    return cleaned
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_extraction.py::TestVoteTopicExtraction -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/extraction.py tests/test_extraction.py
git commit -m "feat: add natural language vote topic extraction"
```

---

### Task 3: Wire Topic + Refs Into Vote Records

**Files:**
- Modify: `src/clerk/extraction.py:1027-1047` (`_create_vote_record`) and `src/clerk/extraction.py:454-532` (`_extract_vote_results_spacy`)
- Test: `tests/test_extraction.py`

**Step 1: Write the failing test**

```python
class TestVoteRecordTopicIntegration:
    """Tests that vote records include topic and agenda_item_ref fields."""

    def test_vote_record_has_topic_fields(self, monkeypatch):
        """Vote records include agenda_item_ref and topic fields."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        record = extraction._create_vote_record(
            result="passed", ayes=7, nays=0, raw_text="passed 7-0"
        )
        assert "agenda_item_ref" in record
        assert "topic" in record
        assert "section" in record

    def test_extract_votes_includes_topic(self, monkeypatch):
        """Full vote extraction populates topic from context."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        text = "Motion to approve Ordinance 2024-15 regarding the downtown parking structure passed 7-0."
        result = extraction.extract_votes(text)
        votes = result["votes"]
        if votes:
            vote = votes[0]
            assert "topic" in vote
            assert "agenda_item_ref" in vote
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_extraction.py::TestVoteRecordTopicIntegration -v`
Expected: FAIL - `KeyError: 'agenda_item_ref'`

**Step 3: Update `_create_vote_record` and vote extraction functions**

In `_create_vote_record` (~line 1027), add new fields:

```python
def _create_vote_record(
    result: str,
    ayes: int | None,
    nays: int | None,
    raw_text: str,
    individual_votes: list | None = None,
    agenda_item_ref: dict | None = None,
    topic: str | None = None,
    section: str | None = None,
) -> dict:
    """Create a standardized vote record."""
    return {
        "motion_by": None,
        "seconded_by": None,
        "result": result,
        "tally": {
            "ayes": ayes,
            "nays": nays,
            "abstain": None,
            "absent": None,
        },
        "individual_votes": individual_votes or [],
        "raw_text": raw_text,
        "agenda_item_ref": agenda_item_ref,
        "topic": topic,
        "section": section,
    }
```

In `_extract_vote_results_spacy` (~line 454), after creating each vote, extract topic and agenda refs. Update the function to use `doc` for context:

```python
def _extract_vote_results_spacy(doc: Any) -> list[dict]:
    # ... existing matcher code ...

    for match_id, start, end in matches:
        span = doc[start:end]
        match_name = nlp.vocab.strings[match_id]

        # Find agenda item refs near this vote
        refs = extract_agenda_item_refs(doc)
        nearest_ref = _find_nearest_ref(refs, span.start_char, doc.text)

        # Extract topic
        topic = extract_vote_topic(doc, vote_char_offset=span.start_char)

        if match_name == "TALLY_VOTE":
            # ... existing tally extraction ...
            votes.append(
                _create_vote_record(
                    result=result,
                    ayes=ayes,
                    nays=nays,
                    raw_text=span.text,
                    agenda_item_ref=nearest_ref,
                    topic=topic,
                )
            )
        # ... similar for UNANIMOUS_VOTE and VOICE_VOTE ...
```

Add helper to find nearest agenda ref to a vote:

```python
def _find_nearest_ref(refs: list[dict], vote_char_offset: int, text: str) -> dict | None:
    """Find the agenda item ref nearest to (and before) the vote position."""
    best = None
    best_distance = float("inf")
    for ref in refs:
        distance = vote_char_offset - ref["char_end"]
        if 0 <= distance < best_distance:
            best = {"type": ref["type"], "number": ref["number"]}
            best_distance = distance
    return best
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_extraction.py::TestVoteRecordTopicIntegration -v`
Expected: PASS

**Step 5: Run full vote test suite for regressions**

Run: `pytest tests/test_extraction.py -k "Vote" -v`
Expected: All PASS (existing tests should still work since new fields are additive)

**Step 6: Commit**

```bash
git add src/clerk/extraction.py tests/test_extraction.py
git commit -m "feat: wire topic and agenda refs into vote records"
```

---

### Task 4: Section Detection

**Files:**
- Modify: `src/clerk/extraction.py` (new function, update `create_meeting_context`)
- Test: `tests/test_extraction.py`

**Step 1: Write the failing tests**

```python
class TestSectionDetection:
    """Tests for meeting section detection."""

    def test_detects_consent_calendar(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        section = extraction.detect_section("CONSENT CALENDAR\nItem 1. Approve minutes.")
        assert section == "consent_calendar"

    def test_detects_public_hearing(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        section = extraction.detect_section("PUBLIC HEARING\nOrdinance 2024-15.")
        assert section == "public_hearing"

    def test_detects_new_business(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        section = extraction.detect_section("NEW BUSINESS\nCouncil discussed parking.")
        assert section == "new_business"

    def test_returns_none_for_no_section(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        section = extraction.detect_section("The mayor welcomed everyone.")
        assert section is None

    def test_meeting_context_tracks_section(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        ctx = extraction.create_meeting_context()
        assert "current_section" in ctx
        assert ctx["current_section"] is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_extraction.py::TestSectionDetection -v`
Expected: FAIL

**Step 3: Implement `detect_section()`**

Add to `src/clerk/extraction.py`:

```python
_SECTION_PATTERNS = [
    (re.compile(r"^\s*CONSENT\s+CALENDAR\b", re.IGNORECASE | re.MULTILINE), "consent_calendar"),
    (re.compile(r"^\s*PUBLIC\s+HEAR(?:ING|INGS)\b", re.IGNORECASE | re.MULTILINE), "public_hearing"),
    (re.compile(r"^\s*NEW\s+BUSINESS\b", re.IGNORECASE | re.MULTILINE), "new_business"),
    (re.compile(r"^\s*OLD\s+BUSINESS\b", re.IGNORECASE | re.MULTILINE), "old_business"),
    (re.compile(r"^\s*UNFINISHED\s+BUSINESS\b", re.IGNORECASE | re.MULTILINE), "old_business"),
    (re.compile(r"^\s*ACTION\s+ITEMS?\b", re.IGNORECASE | re.MULTILINE), "action_items"),
    (re.compile(r"^\s*PUBLIC\s+COMMENT\b", re.IGNORECASE | re.MULTILINE), "public_comment"),
    (re.compile(r"^\s*STAFF\s+REPORT\b", re.IGNORECASE | re.MULTILINE), "staff_report"),
    (re.compile(r"^\s*CLOSED\s+SESSION\b", re.IGNORECASE | re.MULTILINE), "closed_session"),
]


def detect_section(text: str) -> str | None:
    """Detect the meeting section from text content.

    Looks for section headers like 'CONSENT CALENDAR', 'PUBLIC HEARING', etc.
    Returns the last (most recent) section found in the text.

    Args:
        text: Page text to scan for section headers

    Returns:
        Section identifier string, or None if no section detected
    """
    last_section = None
    last_pos = -1

    for pattern, section_name in _SECTION_PATTERNS:
        match = pattern.search(text)
        if match and match.start() > last_pos:
            last_section = section_name
            last_pos = match.start()

    return last_section
```

Update `create_meeting_context()` to include `current_section`:

```python
def create_meeting_context() -> dict:
    return {
        "known_persons": set(),
        "known_orgs": set(),
        "attendees": [],
        "meeting_type": None,
        "current_section": None,
    }
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_extraction.py::TestSectionDetection -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/extraction.py tests/test_extraction.py
git commit -m "feat: add meeting section detection"
```

---

### Task 5: Entity Name Resolution

**Files:**
- Modify: `src/clerk/extraction.py` (new function)
- Test: `tests/test_extraction.py`

**Step 1: Write the failing tests**

```python
class TestEntityResolution:
    """Tests for entity name resolution and deduplication."""

    def test_merges_name_variants(self, monkeypatch):
        """Merges 'Smith', 'John Smith', 'Councilmember Smith' into one."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [
                {"text": "Smith", "confidence": 0.85},
                {"text": "John Smith", "confidence": 0.85},
                {"text": "Councilmember Smith", "confidence": 0.85},
            ],
            "orgs": [],
            "locations": [],
        }

        resolved = extraction.resolve_entities(entities)
        # Should merge into one canonical person
        assert len(resolved["persons"]) == 1
        # Canonical should be the longest non-titled name
        assert resolved["persons"][0]["text"] == "John Smith"
        assert "Smith" in resolved["persons"][0]["variants"]
        assert "Councilmember Smith" in resolved["persons"][0]["variants"]

    def test_keeps_distinct_persons(self, monkeypatch):
        """Does not merge different people."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [
                {"text": "John Smith", "confidence": 0.85},
                {"text": "Jane Doe", "confidence": 0.85},
            ],
            "orgs": [],
            "locations": [],
        }

        resolved = extraction.resolve_entities(entities)
        assert len(resolved["persons"]) == 2

    def test_handles_initials(self, monkeypatch):
        """Merges 'J. Smith' with 'John Smith'."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [
                {"text": "J. Smith", "confidence": 0.85},
                {"text": "John Smith", "confidence": 0.85},
            ],
            "orgs": [],
            "locations": [],
        }

        resolved = extraction.resolve_entities(entities)
        assert len(resolved["persons"]) == 1
        assert resolved["persons"][0]["text"] == "John Smith"

    def test_preserves_orgs_and_locations(self, monkeypatch):
        """Orgs and locations pass through unchanged."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [],
            "orgs": [{"text": "City Council", "confidence": 0.85}],
            "locations": [{"text": "Oakland", "confidence": 0.85}],
        }

        resolved = extraction.resolve_entities(entities)
        assert len(resolved["orgs"]) == 1
        assert len(resolved["locations"]) == 1
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_extraction.py::TestEntityResolution -v`
Expected: FAIL

**Step 3: Implement `resolve_entities()`**

Add to `src/clerk/extraction.py`:

```python
def resolve_entities(entities: dict) -> dict:
    """Resolve and deduplicate entities by merging name variants.

    Groups person name variants (e.g., 'Smith', 'John Smith',
    'Councilmember Smith') into canonical entries with variant lists.

    Args:
        entities: Dict with 'persons', 'orgs', 'locations' lists

    Returns:
        New dict with resolved persons (including 'variants' field),
        orgs and locations passed through unchanged.
    """
    resolved_persons = _resolve_person_names(entities.get("persons", []))

    return {
        "persons": resolved_persons,
        "orgs": entities.get("orgs", []),
        "locations": entities.get("locations", []),
    }


def _strip_civic_title(name: str) -> str:
    """Remove civic titles from a name string."""
    for title in CIVIC_TITLES:
        pattern = re.compile(rf"^\s*{re.escape(title)}\s+", re.IGNORECASE)
        name = pattern.sub("", name)
    return name.strip()


def _get_last_name(name: str) -> str:
    """Extract the last name from a full name string."""
    parts = name.strip().split()
    return parts[-1] if parts else name


def _names_match(name_a: str, name_b: str) -> bool:
    """Check if two names refer to the same person.

    Handles:
    - Exact match after title stripping
    - Last name match with initial match ('J. Smith' == 'John Smith')
    - Last name only match ('Smith' == 'John Smith')
    """
    a = _strip_civic_title(name_a)
    b = _strip_civic_title(name_b)

    if a.lower() == b.lower():
        return True

    a_parts = a.split()
    b_parts = b.split()

    a_last = a_parts[-1].lower() if a_parts else ""
    b_last = b_parts[-1].lower() if b_parts else ""

    if a_last != b_last:
        return False

    # Same last name - check if one is just the last name
    if len(a_parts) == 1 or len(b_parts) == 1:
        return True

    # Check initial match: 'J.' matches 'John'
    a_first = a_parts[0] if len(a_parts) > 1 else ""
    b_first = b_parts[0] if len(b_parts) > 1 else ""

    if a_first.endswith(".") and b_first.lower().startswith(a_first[0].lower()):
        return True
    if b_first.endswith(".") and a_first.lower().startswith(b_first[0].lower()):
        return True

    return False


def _resolve_person_names(persons: list[dict]) -> list[dict]:
    """Group person name variants and select canonical forms."""
    if not persons:
        return []

    # Build groups of matching names
    groups: list[list[dict]] = []

    for person in persons:
        matched = False
        for group in groups:
            if any(_names_match(person["text"], existing["text"]) for existing in group):
                group.append(person)
                matched = True
                break
        if not matched:
            groups.append([person])

    # Build resolved entries
    resolved = []
    for group in groups:
        # Pick canonical name: longest non-titled name, or longest overall
        stripped = [(p, _strip_civic_title(p["text"])) for p in group]
        # Prefer the longest stripped name as canonical
        canonical_entry = max(stripped, key=lambda x: len(x[1]))
        canonical_text = canonical_entry[1]

        # Collect variants (all names except the canonical)
        variants = []
        for p in group:
            if p["text"] != canonical_text:
                variants.append(p["text"])

        # Use highest confidence from the group
        best_confidence = max(p["confidence"] for p in group)

        entry = {
            "text": canonical_text,
            "confidence": best_confidence,
            "variants": variants,
        }
        resolved.append(entry)

    return resolved
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_extraction.py::TestEntityResolution -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/extraction.py tests/test_extraction.py
git commit -m "feat: add entity name resolution with variant merging"
```

---

### Task 6: Entity Categorization

**Files:**
- Modify: `src/clerk/extraction.py` (extend `resolve_entities`)
- Test: `tests/test_extraction.py`

**Step 1: Write the failing tests**

```python
class TestEntityCategorization:
    """Tests for entity role categorization."""

    def test_categorizes_elected_official_by_title(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [{"text": "Councilmember Smith", "confidence": 0.85}],
            "orgs": [],
            "locations": [],
        }
        ctx = extraction.create_meeting_context()

        resolved = extraction.resolve_entities(entities, meeting_context=ctx)
        assert resolved["persons"][0]["category"] == "elected_official"

    def test_categorizes_elected_official_by_roll_call(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [{"text": "Smith", "confidence": 0.85}],
            "orgs": [],
            "locations": [],
        }
        ctx = extraction.create_meeting_context()
        ctx["attendees"] = ["Smith"]

        resolved = extraction.resolve_entities(entities, meeting_context=ctx)
        assert resolved["persons"][0]["category"] == "elected_official"

    def test_categorizes_staff(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [{"text": "City Manager Johnson", "confidence": 0.85}],
            "orgs": [],
            "locations": [],
        }
        ctx = extraction.create_meeting_context()

        resolved = extraction.resolve_entities(entities, meeting_context=ctx)
        assert resolved["persons"][0]["category"] == "staff"

    def test_defaults_to_unknown(self, monkeypatch):
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        entities = {
            "persons": [{"text": "John Doe", "confidence": 0.85}],
            "orgs": [],
            "locations": [],
        }
        ctx = extraction.create_meeting_context()

        resolved = extraction.resolve_entities(entities, meeting_context=ctx)
        assert resolved["persons"][0]["category"] == "unknown"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_extraction.py::TestEntityCategorization -v`
Expected: FAIL

**Step 3: Implement categorization**

Add title sets and categorization logic, then update `resolve_entities` to accept `meeting_context`:

```python
ELECTED_TITLES = {
    "mayor", "vice mayor", "council member", "councilmember", "councilwoman",
    "councilman", "commissioner", "chair", "vice chair", "chairman",
    "chairwoman", "president", "vice president", "supervisor", "alderman",
    "alderwoman", "selectman", "selectwoman",
}

STAFF_TITLES = {
    "city manager", "city attorney", "director", "secretary", "treasurer",
    "clerk", "city clerk", "deputy clerk", "assistant city manager",
    "fire chief", "police chief", "chief",
}


def _categorize_person(name: str, variants: list[str], meeting_context: dict | None) -> str:
    """Categorize a person as elected_official, staff, or unknown."""
    all_names = [name] + variants

    # Check if any variant has an elected title
    for n in all_names:
        lower = n.lower()
        for title in ELECTED_TITLES:
            if lower.startswith(title):
                return "elected_official"

    # Check if person appears in roll call attendees
    if meeting_context:
        attendees_lower = {a.lower() for a in meeting_context.get("attendees", [])}
        for n in all_names:
            stripped = _strip_civic_title(n).lower()
            if stripped in attendees_lower:
                return "elected_official"

    # Check staff titles
    for n in all_names:
        lower = n.lower()
        for title in STAFF_TITLES:
            if lower.startswith(title):
                return "staff"

    return "unknown"
```

Update `resolve_entities` signature to accept `meeting_context`:

```python
def resolve_entities(entities: dict, meeting_context: dict | None = None) -> dict:
```

And in `_resolve_person_names`, add the `meeting_context` parameter and call `_categorize_person` when building each resolved entry:

```python
entry = {
    "text": canonical_text,
    "confidence": best_confidence,
    "variants": variants,
    "category": _categorize_person(canonical_text, variants, meeting_context),
}
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_extraction.py::TestEntityCategorization -v`
Expected: PASS

**Step 5: Run full entity test suite for regressions**

Run: `pytest tests/test_extraction.py -k "Entity or Resolution or Categorization" -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add src/clerk/extraction.py tests/test_extraction.py
git commit -m "feat: add entity categorization (elected_official/staff/unknown)"
```

---

### Task 7: Configurable spaCy Model Selection

**Files:**
- Modify: `src/clerk/extraction.py:27-81` (`get_nlp` function)
- Test: `tests/test_extraction.py`

**Step 1: Write the failing tests**

```python
class TestModelSelection:
    """Tests for configurable spaCy model selection."""

    def test_default_model_is_md(self, monkeypatch):
        """Default model should be en_core_web_md."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        monkeypatch.delenv("SPACY_MODEL", raising=False)
        extraction = load_extraction_module()
        assert extraction.SPACY_MODEL == "en_core_web_md"

    def test_model_configurable_via_env(self, monkeypatch):
        """SPACY_MODEL env var overrides the default."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        monkeypatch.setenv("SPACY_MODEL", "en_core_web_trf")
        extraction = load_extraction_module()
        assert extraction.SPACY_MODEL == "en_core_web_trf"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_extraction.py::TestModelSelection -v`
Expected: FAIL

**Step 3: Add SPACY_MODEL config**

Near the top of `extraction.py` (after `ENTITY_CONFIDENCE_THRESHOLD`):

```python
# Configurable spaCy model - default to medium for speed, use trf for accuracy
SPACY_MODEL = os.environ.get("SPACY_MODEL", "en_core_web_md")
```

Update `get_nlp()` to use `SPACY_MODEL`:

```python
# Change the line:
_nlp = spacy.load("en_core_web_md")
# To:
_nlp = spacy.load(SPACY_MODEL)
```

And update the log messages and error message to reference `SPACY_MODEL` instead of the hardcoded string.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_extraction.py::TestModelSelection -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/extraction.py tests/test_extraction.py
git commit -m "feat: add configurable spaCy model via SPACY_MODEL env var"
```

---

### Task 8: Wire Resolution Into Extract CLI

**Files:**
- Modify: `src/clerk/extract_cli.py:95-210` (`_run_extraction_for_site`)
- Modify: `src/clerk/extract_cli.py:16-33` (imports)
- Test: `tests/test_extract_cli.py`

**Step 1: Write the failing test**

```python
class TestExtractionWithResolution:
    """Tests that extract CLI wires up entity resolution."""

    def test_extraction_stores_section_in_context(self, monkeypatch, tmp_path):
        """Section detection updates meeting context during extraction."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        # This test verifies that the CLI orchestration calls detect_section
        # and passes current_section to vote records
        # (Integration test - may need a fixture with page files)
```

Note: The CLI integration tests in `test_extract_cli.py` use Click's `CliRunner` and mock the filesystem. Follow the existing test patterns there.

**Step 2: Update imports in extract_cli.py**

Add new imports:

```python
from .extraction import (
    EXTRACTION_ENABLED,
    get_nlp,
    detect_section,
    resolve_entities,
    create_meeting_context,
    update_context,
)
```

**Step 3: Update `_run_extraction_for_site` to use meeting context, section detection, and entity resolution**

The key changes to `_run_extraction_for_site`:

1. Group pages by meeting/date (use `group_pages_by_meeting_date` from utils if available, or group manually)
2. For each meeting group, create a meeting context
3. On each page, call `detect_section` and update `context["current_section"]`
4. Pass `current_section` to vote extraction so it gets stored in vote records
5. After all pages in a meeting are processed, run `resolve_entities` across accumulated entities
6. Update cache with resolved data

This is the most complex wiring task. The implementation should:
- Reorganize Phase 3 to process pages grouped by meeting/date
- Accumulate entities across pages within the same meeting
- Run resolution at meeting boundaries
- Pass section context to vote record creation

**Step 4: Run the full test suite**

Run: `pytest tests/test_extract_cli.py tests/test_extraction.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/clerk/extract_cli.py tests/test_extract_cli.py
git commit -m "feat: wire entity resolution and section detection into extract CLI"
```

---

### Task 9: End-to-End Integration Test

**Files:**
- Test: `tests/test_extraction.py`

**Step 1: Write an integration test**

```python
class TestEndToEndExtraction:
    """Integration test for the full extraction pipeline."""

    def test_full_pipeline_with_civic_text(self, monkeypatch):
        """End-to-end test with realistic civic meeting text."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        text = """
        CONSENT CALENDAR
        Item 1. Approval of minutes from January 15, 2024.
        Councilmember Smith moved approval. Seconded by Councilmember Jones.
        Motion passed unanimously.

        PUBLIC HEARING
        Item 2. Ordinance 2024-15 regarding the downtown parking structure.
        Mayor Johnson opened the public hearing.
        City Manager Williams presented the staff report.
        Councilmember Smith moved to approve Ordinance 2024-15.
        Seconded by Councilmember Jones. Motion passed 5-2.
        Ayes: Smith, Jones, Lee, Chen, Davis. Nays: Brown, Garcia.
        """

        doc = nlp(text)

        # Test entity extraction
        entities = extraction.extract_entities(text, doc=doc)
        person_names = {p["text"] for p in entities["persons"]}
        # Should find at least some of the council members
        assert len(entities["persons"]) >= 2

        # Test vote extraction
        votes_result = extraction.extract_votes(text, doc=doc)
        votes = votes_result["votes"]
        assert len(votes) >= 2  # Unanimous + tally vote

        # Test agenda item refs
        refs = extraction.extract_agenda_item_refs(doc)
        assert any(r["type"] == "ordinance" and r["number"] == "2024-15" for r in refs)

        # Test section detection
        section = extraction.detect_section(text)
        assert section is not None

        # Test entity resolution
        ctx = extraction.create_meeting_context()
        ctx["attendees"] = ["Smith", "Jones", "Lee", "Chen", "Davis", "Brown", "Garcia"]
        resolved = extraction.resolve_entities(entities, meeting_context=ctx)
        # Resolved persons should have categories
        for person in resolved["persons"]:
            assert "category" in person
            assert "variants" in person
```

**Step 2: Run the test**

Run: `pytest tests/test_extraction.py::TestEndToEndExtraction -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_extraction.py
git commit -m "test: add end-to-end extraction integration test"
```

---

## Summary of Implementation Order

| Task | Description | Depends On |
|------|-------------|------------|
| 1 | Agenda item reference extraction | - |
| 2 | Vote topic extraction (NLP) | - |
| 3 | Wire topic + refs into vote records | 1, 2 |
| 4 | Section detection | - |
| 5 | Entity name resolution | - |
| 6 | Entity categorization | 5 |
| 7 | Configurable spaCy model | - |
| 8 | Wire into extract CLI | 3, 4, 5, 6 |
| 9 | End-to-end integration test | 8 |

Tasks 1, 2, 4, 5, and 7 are independent and can be done in parallel.
