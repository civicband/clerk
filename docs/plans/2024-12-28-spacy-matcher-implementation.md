# spaCy Matcher Vote Extraction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace regex-only vote extraction with spaCy Matcher (vote results) and DependencyMatcher (motion attribution), with regex fallback.

**Architecture:** Token Matcher detects vote outcomes (passed 7-0, unanimously). DependencyMatcher extracts who moved/seconded by following syntactic relationships. Single parse per page, shared between entity and vote extraction. Regex fallback when spaCy unavailable.

**Tech Stack:** spaCy Matcher, DependencyMatcher, existing extraction.py module

---

### Task 1: Add parse_text() Function

**Files:**
- Modify: `src/clerk/extraction.py:27-56`
- Test: `tests/test_extraction.py`

**Step 1: Write the failing test**

Add to `tests/test_extraction.py`:

```python
class TestParseText:
    """Tests for parse_text function."""

    def test_returns_none_when_extraction_disabled(self, monkeypatch):
        """parse_text returns None when ENABLE_EXTRACTION=0."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "0")
        extraction = load_extraction_module()
        result = extraction.parse_text("Some text")
        assert result is None

    def test_returns_none_when_nlp_unavailable(self, monkeypatch):
        """parse_text returns None when spaCy not available."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        extraction._nlp = None
        extraction._nlp_load_attempted = True
        result = extraction.parse_text("Some text")
        assert result is None

    def test_returns_doc_when_available(self, monkeypatch):
        """parse_text returns spaCy Doc when available."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()
        # Only test if spaCy is actually available
        if extraction.get_nlp() is not None:
            result = extraction.parse_text("The motion passed.")
            assert result is not None
            assert hasattr(result, "text")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_extraction.py::TestParseText -v`
Expected: FAIL with "module has no attribute 'parse_text'"

**Step 3: Write minimal implementation**

Add to `src/clerk/extraction.py` after `get_nlp()`:

```python
def parse_text(text: str):
    """Parse text with spaCy, returning Doc or None if unavailable.

    Use this to parse once and pass doc to extract_entities() and extract_votes().

    Args:
        text: The text to parse

    Returns:
        spaCy Doc object, or None if extraction disabled or spaCy unavailable
    """
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
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_extraction.py::TestParseText -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/extraction.py tests/test_extraction.py
git commit -m "feat: add parse_text for single-parse optimization"
```

---

### Task 2: Update extract_entities() to Accept Doc Parameter

**Files:**
- Modify: `src/clerk/extraction.py:59-111`
- Test: `tests/test_extraction.py`

**Step 1: Write the failing test**

Add to `tests/test_extraction.py` in `TestExtractEntities`:

```python
    def test_accepts_precomputed_doc(self, monkeypatch):
        """extract_entities can use precomputed doc to avoid re-parsing."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        text = "Mayor Smith attended the meeting."
        doc = nlp(text)

        # Should work with precomputed doc
        result = extraction.extract_entities(text, doc=doc)
        assert "persons" in result
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_extraction.py::TestExtractEntities::test_accepts_precomputed_doc -v`
Expected: FAIL with "unexpected keyword argument 'doc'"

**Step 3: Update implementation**

Modify `extract_entities()` in `src/clerk/extraction.py`:

```python
def extract_entities(text: str, doc=None, threshold: float | None = None) -> dict:
    """Extract named entities from text using spaCy NER.

    Args:
        text: The text to extract entities from
        doc: Optional precomputed spaCy Doc (avoids re-parsing)
        threshold: Minimum confidence score (defaults to ENTITY_CONFIDENCE_THRESHOLD)

    Returns:
        Dict with keys 'persons', 'orgs', 'locations', each containing
        list of {'text': str, 'confidence': float} dicts
    """
    empty_result = {"persons": [], "orgs": [], "locations": []}

    if not EXTRACTION_ENABLED:
        return empty_result

    # Use precomputed doc or parse text
    if doc is None:
        doc = parse_text(text)
    if doc is None:
        return empty_result

    if threshold is None:
        threshold = ENTITY_CONFIDENCE_THRESHOLD

    persons = []
    orgs = []
    locations = []

    for ent in doc.ents:
        confidence = 0.85  # Default for transformer model

        entity_data = {"text": ent.text, "confidence": confidence}

        if confidence < threshold:
            continue

        if ent.label_ == "PERSON":
            persons.append(entity_data)
        elif ent.label_ == "ORG":
            orgs.append(entity_data)
        elif ent.label_ in ("GPE", "LOC", "FAC"):
            locations.append(entity_data)

    return {"persons": persons, "orgs": orgs, "locations": locations}
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_extraction.py::TestExtractEntities -v`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add src/clerk/extraction.py tests/test_extraction.py
git commit -m "feat: extract_entities accepts precomputed doc parameter"
```

---

### Task 3: Add Lazy Matcher Initialization

**Files:**
- Modify: `src/clerk/extraction.py`
- Test: `tests/test_extraction.py`

**Step 1: Write the failing test**

Add to `tests/test_extraction.py`:

```python
class TestMatcherInitialization:
    """Tests for lazy matcher initialization."""

    def test_get_vote_matcher_returns_matcher(self, monkeypatch):
        """_get_vote_matcher returns Matcher when spaCy available."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        matcher = extraction._get_vote_matcher(nlp)
        assert matcher is not None

    def test_get_motion_matcher_returns_matcher(self, monkeypatch):
        """_get_motion_matcher returns DependencyMatcher when spaCy available."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        matcher = extraction._get_motion_matcher(nlp)
        assert matcher is not None

    def test_matchers_are_cached(self, monkeypatch):
        """Matchers should be cached after first initialization."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        matcher1 = extraction._get_vote_matcher(nlp)
        matcher2 = extraction._get_vote_matcher(nlp)
        assert matcher1 is matcher2
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_extraction.py::TestMatcherInitialization -v`
Expected: FAIL with "module has no attribute '_get_vote_matcher'"

**Step 3: Write implementation**

Add to `src/clerk/extraction.py` after `parse_text()`:

```python
# Lazy-loaded matchers
_vote_matcher = None
_motion_matcher = None


def _get_vote_matcher(nlp):
    """Get Token Matcher for vote results, initializing lazily.

    Patterns detect:
    - Tally votes: "passed 7-0", "approved 5-2"
    - Unanimous votes: "passed unanimously", "unanimous vote"
    - Voice votes: "by voice vote"
    """
    global _vote_matcher

    if _vote_matcher is not None:
        return _vote_matcher

    try:
        from spacy.matcher import Matcher
    except ImportError:
        return None

    _vote_matcher = Matcher(nlp.vocab)

    # Pattern 1: Tally votes (passed 7-0, approved 5-2)
    _vote_matcher.add("TALLY_VOTE", [[
        {"LEMMA": {"IN": ["pass", "carry", "approve", "defeat", "fail", "reject"]}},
        {"LIKE_NUM": True},
        {"TEXT": "-"},
        {"LIKE_NUM": True},
    ]])

    # Pattern 2a: Unanimous (verb + unanimously)
    _vote_matcher.add("UNANIMOUS_VOTE", [
        [
            {"LEMMA": {"IN": ["pass", "carry", "approve"]}},
            {"LOWER": "unanimously"},
        ],
        [
            {"LOWER": "unanimously"},
            {"LEMMA": {"IN": ["pass", "carry", "approve"]}},
        ],
        [
            {"LOWER": "unanimous"},
            {"LOWER": "vote"},
        ],
    ])

    # Pattern 3: Voice vote
    _vote_matcher.add("VOICE_VOTE", [[
        {"LOWER": {"IN": ["by", "on"]}},
        {"LOWER": "a", "OP": "?"},
        {"LOWER": "voice"},
        {"LOWER": "vote"},
    ]])

    return _vote_matcher


def _get_motion_matcher(nlp):
    """Get DependencyMatcher for motion attribution, initializing lazily.

    Patterns detect:
    - Active voice: "Smith moved approval"
    - Passive voice: "moved by Smith"
    """
    global _motion_matcher

    if _motion_matcher is not None:
        return _motion_matcher

    try:
        from spacy.matcher import DependencyMatcher
    except ImportError:
        return None

    _motion_matcher = DependencyMatcher(nlp.vocab)

    # Pattern 1: Active voice - "Smith moved/seconded [something]"
    _motion_matcher.add("MOTION_ACTIVE", [[
        {"RIGHT_ID": "verb", "RIGHT_ATTRS": {"LEMMA": {"IN": ["move", "second"]}}},
        {"LEFT_ID": "verb", "REL_OP": ">", "RIGHT_ID": "subject",
         "RIGHT_ATTRS": {"DEP": "nsubj"}},
    ]])

    # Pattern 2: Passive voice - "moved/seconded by Smith"
    _motion_matcher.add("MOTION_PASSIVE", [[
        {"RIGHT_ID": "verb", "RIGHT_ATTRS": {"LEMMA": {"IN": ["move", "second"]}}},
        {"LEFT_ID": "verb", "REL_OP": ">", "RIGHT_ID": "agent",
         "RIGHT_ATTRS": {"DEP": "agent"}},
    ]])

    return _motion_matcher
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_extraction.py::TestMatcherInitialization -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/extraction.py tests/test_extraction.py
git commit -m "feat: add lazy matcher initialization for vote/motion patterns"
```

---

### Task 4: Add Token Matcher Vote Extraction

**Files:**
- Modify: `src/clerk/extraction.py`
- Test: `tests/test_extraction.py`

**Step 1: Write the failing test**

Add to `tests/test_extraction.py`:

```python
class TestTokenMatcherVotes:
    """Tests for Token Matcher vote result extraction."""

    def test_tally_vote_with_matcher(self, monkeypatch):
        """Token Matcher extracts tally votes."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The motion passed 7-0.")
        votes = extraction._extract_vote_results_spacy(doc)

        assert len(votes) == 1
        assert votes[0]["result"] == "passed"
        assert votes[0]["tally"]["ayes"] == 7
        assert votes[0]["tally"]["nays"] == 0

    def test_unanimous_vote_with_matcher(self, monkeypatch):
        """Token Matcher extracts unanimous votes."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The motion carried unanimously.")
        votes = extraction._extract_vote_results_spacy(doc)

        assert len(votes) == 1
        assert votes[0]["result"] == "passed"

    def test_voice_vote_with_matcher(self, monkeypatch):
        """Token Matcher extracts voice votes."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The item was approved by voice vote.")
        votes = extraction._extract_vote_results_spacy(doc)

        assert len(votes) >= 1

    def test_carried_variation(self, monkeypatch):
        """Token Matcher handles 'carried' as pass synonym."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The measure carried 6-1.")
        votes = extraction._extract_vote_results_spacy(doc)

        assert len(votes) == 1
        assert votes[0]["result"] == "passed"
        assert votes[0]["tally"]["ayes"] == 6

    def test_defeated_variation(self, monkeypatch):
        """Token Matcher handles 'defeated' as fail."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The amendment was defeated 2-5.")
        votes = extraction._extract_vote_results_spacy(doc)

        assert len(votes) == 1
        assert votes[0]["result"] == "failed"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_extraction.py::TestTokenMatcherVotes -v`
Expected: FAIL with "module has no attribute '_extract_vote_results_spacy'"

**Step 3: Write implementation**

Add to `src/clerk/extraction.py`:

```python
# Words indicating vote passed
PASS_LEMMAS = {"pass", "carry", "approve"}
# Words indicating vote failed
FAIL_LEMMAS = {"defeat", "fail", "reject"}


def _extract_vote_results_spacy(doc) -> list[dict]:
    """Extract vote results using Token Matcher.

    Args:
        doc: spaCy Doc object

    Returns:
        List of vote record dicts
    """
    nlp = doc.vocab  # Get vocab from doc
    matcher = _get_vote_matcher(doc.vocab.vectors.data if hasattr(doc.vocab, 'vectors') else None)

    # Need to get nlp object for matcher - use global
    nlp_obj = get_nlp()
    if nlp_obj is None:
        return []

    matcher = _get_vote_matcher(nlp_obj)
    if matcher is None:
        return []

    votes = []
    matches = matcher(doc)

    for match_id, start, end in matches:
        span = doc[start:end]
        match_name = nlp_obj.vocab.strings[match_id]

        if match_name == "TALLY_VOTE":
            # Extract numbers from span
            nums = [token.text for token in span if token.like_num]
            if len(nums) >= 2:
                ayes = int(nums[0])
                nays = int(nums[1])
                # Determine result from the verb lemma
                verb_lemma = None
                for token in span:
                    if token.lemma_ in PASS_LEMMAS | FAIL_LEMMAS:
                        verb_lemma = token.lemma_
                        break

                result = "passed" if verb_lemma in PASS_LEMMAS else "failed"

                votes.append(_create_vote_record(
                    result=result,
                    ayes=ayes,
                    nays=nays,
                    raw_text=span.text,
                ))

        elif match_name == "UNANIMOUS_VOTE":
            votes.append(_create_vote_record(
                result="passed",
                ayes=None,
                nays=0,
                raw_text=span.text,
            ))

        elif match_name == "VOICE_VOTE":
            votes.append(_create_vote_record(
                result="passed",
                ayes=None,
                nays=None,
                raw_text=span.text,
            ))

    return votes
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_extraction.py::TestTokenMatcherVotes -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/extraction.py tests/test_extraction.py
git commit -m "feat: add Token Matcher vote result extraction"
```

---

### Task 5: Add DependencyMatcher Motion Attribution

**Files:**
- Modify: `src/clerk/extraction.py`
- Test: `tests/test_extraction.py`

**Step 1: Write the failing test**

Add to `tests/test_extraction.py`:

```python
class TestDependencyMatcherMotions:
    """Tests for DependencyMatcher motion attribution."""

    def test_active_voice_motion(self, monkeypatch):
        """DependencyMatcher extracts 'Smith moved approval'."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("Smith moved approval of the resolution.")
        result = extraction._extract_motion_attribution_spacy(doc)

        assert result is not None
        assert result.get("motion_by") == "Smith"

    def test_passive_voice_motion(self, monkeypatch):
        """DependencyMatcher extracts 'moved by Smith'."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The motion was moved by Smith.")
        result = extraction._extract_motion_attribution_spacy(doc)

        assert result is not None
        assert result.get("motion_by") == "Smith"

    def test_seconded_by(self, monkeypatch):
        """DependencyMatcher extracts 'seconded by Jones'."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The item was seconded by Jones.")
        result = extraction._extract_motion_attribution_spacy(doc)

        assert result is not None
        assert result.get("seconded_by") == "Jones"

    def test_combined_motion_and_second(self, monkeypatch):
        """DependencyMatcher extracts both mover and seconder."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("Smith moved and Jones seconded the motion.")
        result = extraction._extract_motion_attribution_spacy(doc)

        assert result is not None
        # Should get at least one of them
        assert result.get("motion_by") or result.get("seconded_by")

    def test_disambiguation_rejects_relocation(self, monkeypatch):
        """DependencyMatcher rejects 'moved to Oakland' (not a motion)."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        doc = nlp("The company moved to Oakland last year.")
        result = extraction._extract_motion_attribution_spacy(doc)

        # Should not extract motion attribution for relocation
        assert result is None or result.get("motion_by") is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_extraction.py::TestDependencyMatcherMotions -v`
Expected: FAIL with "module has no attribute '_extract_motion_attribution_spacy'"

**Step 3: Write implementation**

Add to `src/clerk/extraction.py`:

```python
# Objects that indicate a parliamentary motion (not relocation)
MOTION_OBJECTS = {
    "motion", "resolution", "approval", "item", "amendment",
    "ordinance", "measure", "recommendation", "action", "adoption",
}


def _is_parliamentary_motion(verb_token) -> bool:
    """Check if a 'move' verb is parliamentary (not relocation).

    Looks at the verb's children to see if it has a motion-related object.
    """
    # Check direct objects
    for child in verb_token.children:
        if child.dep_ in ("dobj", "attr", "xcomp", "ccomp"):
            if child.lemma_.lower() in MOTION_OBJECTS:
                return True
            # Check if child has motion object ("move to approve")
            for grandchild in child.children:
                if grandchild.lemma_.lower() in MOTION_OBJECTS:
                    return True

    # Check for "move to [verb]" pattern (infinitive complement)
    for child in verb_token.children:
        if child.dep_ == "xcomp" and child.pos_ == "VERB":
            # "move to approve" - this is parliamentary
            return True

    # Check for prepositional objects that indicate relocation
    for child in verb_token.children:
        if child.dep_ == "prep" and child.text.lower() == "to":
            for pobj in child.children:
                if pobj.dep_ == "pobj":
                    # "moved to Oakland" - location, not parliamentary
                    if pobj.ent_type_ in ("GPE", "LOC", "FAC"):
                        return False

    # Default: if verb is "second", always parliamentary
    if verb_token.lemma_ == "second":
        return True

    # Default for "move" without clear context: uncertain, be conservative
    return False


def _extract_motion_attribution_spacy(doc) -> dict | None:
    """Extract motion/second attribution using DependencyMatcher.

    Args:
        doc: spaCy Doc object

    Returns:
        Dict with 'motion_by' and/or 'seconded_by', or None if not found
    """
    nlp = get_nlp()
    if nlp is None:
        return None

    matcher = _get_motion_matcher(nlp)
    if matcher is None:
        return None

    matches = matcher(doc)

    motion_by = None
    seconded_by = None

    for match_id, token_ids in matches:
        match_name = nlp.vocab.strings[match_id]

        # Get the matched tokens
        verb_idx = token_ids[0]  # First token is always the verb
        verb_token = doc[verb_idx]

        # Skip if this isn't a parliamentary motion
        if verb_token.lemma_ == "move" and not _is_parliamentary_motion(verb_token):
            continue

        # Find the subject/agent
        subject_idx = token_ids[1] if len(token_ids) > 1 else None
        if subject_idx is not None:
            subject_token = doc[subject_idx]
            name = subject_token.text

            # Try to get full name if it's part of a named entity
            for ent in doc.ents:
                if subject_token.i >= ent.start and subject_token.i < ent.end:
                    name = ent.text
                    break

            if verb_token.lemma_ == "move":
                motion_by = name
            elif verb_token.lemma_ == "second":
                seconded_by = name

    if motion_by or seconded_by:
        return {"motion_by": motion_by, "seconded_by": seconded_by}
    return None
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_extraction.py::TestDependencyMatcherMotions -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/extraction.py tests/test_extraction.py
git commit -m "feat: add DependencyMatcher motion attribution with disambiguation"
```

---

### Task 6: Refactor extract_votes() with spaCy Primary, Regex Fallback

**Files:**
- Modify: `src/clerk/extraction.py:174-252`
- Test: `tests/test_extraction.py`

**Step 1: Write the failing test**

Add to `tests/test_extraction.py`:

```python
class TestExtractVotesWithSpacy:
    """Tests for integrated spaCy + regex vote extraction."""

    def test_uses_spacy_when_available(self, monkeypatch):
        """extract_votes uses spaCy Matcher when available."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        # This phrasing is better handled by Matcher than regex
        text = "The measure carried 6-1."
        result = extraction.extract_votes(text)

        assert len(result["votes"]) == 1
        assert result["votes"][0]["tally"]["ayes"] == 6

    def test_falls_back_to_regex(self, monkeypatch):
        """extract_votes falls back to regex when spaCy unavailable."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        # Force spaCy to be unavailable
        extraction._nlp = None
        extraction._nlp_load_attempted = True

        text = "The motion passed 7-0."
        result = extraction.extract_votes(text)

        # Regex should still work
        assert len(result["votes"]) == 1
        assert result["votes"][0]["tally"]["ayes"] == 7

    def test_accepts_precomputed_doc(self, monkeypatch):
        """extract_votes can use precomputed doc."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        text = "The motion passed 7-0."
        doc = nlp(text)
        result = extraction.extract_votes(text, doc=doc)

        assert len(result["votes"]) == 1

    def test_includes_motion_attribution(self, monkeypatch):
        """extract_votes includes motion/second attribution from DependencyMatcher."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        extraction = load_extraction_module()

        nlp = extraction.get_nlp()
        if nlp is None:
            pytest.skip("spaCy not available")

        text = "Smith moved approval. The motion passed 7-0."
        result = extraction.extract_votes(text)

        assert len(result["votes"]) >= 1
        # Motion attribution should be extracted
        vote = result["votes"][0]
        assert vote.get("motion_by") == "Smith" or vote.get("motion_by") is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_extraction.py::TestExtractVotesWithSpacy -v`
Expected: Some tests may fail due to missing doc parameter handling

**Step 3: Update implementation**

Refactor `extract_votes()` in `src/clerk/extraction.py`:

```python
def extract_votes(text: str, doc=None, meeting_context: dict | None = None) -> dict:
    """Extract vote records from text.

    Uses spaCy Matcher when available, falls back to regex.

    Args:
        text: The text to extract votes from
        doc: Optional precomputed spaCy Doc (avoids re-parsing)
        meeting_context: Optional dict with 'known_persons' and 'attendees'
                        for name resolution

    Returns:
        Dict with 'votes' key containing list of vote records
    """
    if not EXTRACTION_ENABLED:
        return {"votes": []}

    if meeting_context is None:
        meeting_context = {"known_persons": set(), "attendees": []}

    # Try spaCy extraction first
    if doc is None:
        doc = parse_text(text)

    if doc is not None:
        return _extract_votes_spacy(doc, text, meeting_context)
    else:
        return _extract_votes_regex(text, meeting_context)


def _extract_votes_spacy(doc, text: str, meeting_context: dict) -> dict:
    """Extract votes using spaCy Matcher and DependencyMatcher.

    Args:
        doc: spaCy Doc object
        text: Original text (for roll call extraction which uses regex)
        meeting_context: Context dict

    Returns:
        Dict with 'votes' key
    """
    votes = []

    # Get vote results from Token Matcher
    vote_results = _extract_vote_results_spacy(doc)
    votes.extend(vote_results)

    # Also check for roll call pattern (regex, works well)
    rollcall_pattern = r"Ayes?:\s*([^.]+)\.\s*Nays?:\s*([^.]*)"
    for match in re.finditer(rollcall_pattern, text, re.IGNORECASE):
        ayes_section = match.group(1)
        nays_section = match.group(2)

        ayes_names = _extract_names_from_list(ayes_section)
        nays_names = _extract_names_from_list(nays_section)

        individual_votes = []
        for name in ayes_names:
            individual_votes.append({"name": name, "vote": "aye"})
        for name in nays_names:
            individual_votes.append({"name": name, "vote": "nay"})

        vote = _create_vote_record(
            result="passed" if len(ayes_names) > len(nays_names) else "failed",
            ayes=len(ayes_names),
            nays=len(nays_names),
            raw_text=match.group(0),
            individual_votes=individual_votes,
        )
        votes.append(vote)

    # Get motion attribution from DependencyMatcher
    motion_info = _extract_motion_attribution_spacy(doc)

    # Apply motion info to votes (or fall back to regex extraction)
    if motion_info is None:
        motion_info = _extract_motion_info(text)

    for vote in votes:
        if motion_info:
            if vote["motion_by"] is None:
                vote["motion_by"] = motion_info.get("motion_by")
            if vote["seconded_by"] is None:
                vote["seconded_by"] = motion_info.get("seconded_by")

    return {"votes": votes}


def _extract_votes_regex(text: str, meeting_context: dict) -> dict:
    """Extract votes using regex patterns (fallback when spaCy unavailable).

    This is the original regex-based implementation.
    """
    votes = []

    # Pattern 1: Simple tally votes (passed 7-0, approved 5-2, etc.)
    simple_pattern = r"(passed|approved|carried|defeated|failed|rejected)\s+(\d+)-(\d+)"
    for match in re.finditer(simple_pattern, text, re.IGNORECASE):
        result_word = match.group(1).lower()
        ayes = int(match.group(2))
        nays = int(match.group(3))

        result = "passed" if result_word in ("passed", "approved", "carried") else "failed"

        vote = _create_vote_record(
            result=result,
            ayes=ayes,
            nays=nays,
            raw_text=match.group(0),
        )
        votes.append(vote)

    # Pattern 2: Unanimous votes
    unanimous_pattern = r"(passed|approved|carried)\s+unanimously"
    for match in re.finditer(unanimous_pattern, text, re.IGNORECASE):
        vote = _create_vote_record(
            result="passed",
            ayes=None,
            nays=0,
            raw_text=match.group(0),
        )
        votes.append(vote)

    # Pattern 3: Roll call votes (Ayes: Name, Name. Nays: Name.)
    rollcall_pattern = r"Ayes?:\s*([^.]+)\.\s*Nays?:\s*([^.]*)"
    for match in re.finditer(rollcall_pattern, text, re.IGNORECASE):
        ayes_section = match.group(1)
        nays_section = match.group(2)

        ayes_names = _extract_names_from_list(ayes_section)
        nays_names = _extract_names_from_list(nays_section)

        individual_votes = []
        for name in ayes_names:
            individual_votes.append({"name": name, "vote": "aye"})
        for name in nays_names:
            individual_votes.append({"name": name, "vote": "nay"})

        vote = _create_vote_record(
            result="passed" if len(ayes_names) > len(nays_names) else "failed",
            ayes=len(ayes_names),
            nays=len(nays_names),
            raw_text=match.group(0),
            individual_votes=individual_votes,
        )
        votes.append(vote)

    # Try to extract motion/second for each vote
    motion_info = _extract_motion_info(text)
    for vote in votes:
        if motion_info:
            vote["motion_by"] = motion_info.get("motion_by")
            vote["seconded_by"] = motion_info.get("seconded_by")

    return {"votes": votes}
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_extraction.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/clerk/extraction.py tests/test_extraction.py
git commit -m "feat: refactor extract_votes with spaCy primary, regex fallback"
```

---

### Task 7: Update build_table_from_text for Single-Parse Flow

**Files:**
- Modify: `src/clerk/utils.py:92-128`
- Test: `tests/test_utils.py`

**Step 1: Write the failing test**

Update test in `tests/test_utils.py`:

```python
class TestBuildTableFromTextExtraction:
    """Tests for extraction integration in build_table_from_text."""

    def test_extraction_populates_json_columns(self, tmp_path, monkeypatch):
        """Test that extraction populates entities_json and votes_json."""
        # ... existing test code stays the same ...
        pass

    def test_single_parse_optimization(self, tmp_path, monkeypatch, mocker):
        """Test that text is parsed only once for both entity and vote extraction."""
        monkeypatch.setenv("ENABLE_EXTRACTION", "1")
        monkeypatch.chdir(tmp_path)

        # Create test structure
        txt_dir = tmp_path / "txt" / "city-council" / "2024-01-15"
        txt_dir.mkdir(parents=True)
        (txt_dir / "001.txt").write_text("The motion passed 7-0.")

        db = sqlite_utils.Database(tmp_path / "test.db")
        db["minutes"].create({
            "id": str, "meeting": str, "date": str, "page": int,
            "text": str, "page_image": str, "entities_json": str, "votes_json": str,
        }, pk="id")

        # Spy on parse_text to count calls
        from clerk import extraction
        parse_spy = mocker.spy(extraction, "parse_text")

        from clerk.utils import build_table_from_text
        build_table_from_text("test", str(tmp_path / "txt"), db, "minutes")

        # parse_text should be called once per page, not twice
        assert parse_spy.call_count == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_utils.py::TestBuildTableFromTextExtraction::test_single_parse_optimization -v`
Expected: May fail if parse is called multiple times

**Step 3: Update implementation**

Update `build_table_from_text()` in `src/clerk/utils.py`:

```python
from .extraction import (
    create_meeting_context,
    detect_roll_call,
    extract_entities,
    extract_votes,
    parse_text,
    update_context,
)


def build_table_from_text(subdomain, txt_dir, db, table_name, municipality=None):
    # ... existing code until the inner loop ...

    for meeting_date in meeting_dates:
        meeting_context = create_meeting_context()
        pages = sorted(os.listdir(f"{txt_dir}/{meeting}/{meeting_date}"))

        for page in pages:
            if not page.endswith(".txt"):
                continue
            # ... existing code to read text ...

            text = page_file.read()

            # Single parse for both entity and vote extraction
            doc = parse_text(text)

            try:
                entities = extract_entities(text, doc=doc)
                update_context(meeting_context, entities=entities)
            except Exception as e:
                logger.warning(f"Entity extraction failed for {page_file_path}: {e}")
                entities = {"persons": [], "orgs": [], "locations": []}

            try:
                attendees = detect_roll_call(text)
                if attendees:
                    update_context(meeting_context, attendees=attendees)
            except Exception as e:
                logger.warning(f"Roll call detection failed for {page_file_path}: {e}")

            try:
                votes = extract_votes(text, doc=doc, meeting_context=meeting_context)
            except Exception as e:
                logger.warning(f"Vote extraction failed for {page_file_path}: {e}")
                votes = {"votes": []}

            # ... rest of existing code ...
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_utils.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/utils.py tests/test_utils.py
git commit -m "feat: update build_table_from_text for single-parse optimization"
```

---

### Task 8: Update Design Document Status

**Files:**
- Modify: `docs/plans/2024-12-28-spacy-matcher-vote-extraction-design.md`

**Step 1: Update status section**

Replace the "Implementation Status" section:

```markdown
## Implementation Status

Implemented. Key components:
- `parse_text()` - Single-parse optimization
- `_get_vote_matcher()` - Token Matcher for vote results
- `_get_motion_matcher()` - DependencyMatcher for motion attribution
- `_extract_vote_results_spacy()` - Token Matcher extraction
- `_extract_motion_attribution_spacy()` - DependencyMatcher extraction with disambiguation
- `_extract_votes_spacy()` - Integrated spaCy extraction
- `_extract_votes_regex()` - Regex fallback
- `extract_votes()` - Main entry point with fallback logic

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
```

**Step 2: Commit**

```bash
git add docs/plans/2024-12-28-spacy-matcher-vote-extraction-design.md
git commit -m "docs: update spaCy Matcher design with implementation status"
```

---

### Task 9: Run Full Test Suite and Push

**Step 1: Run all tests**

```bash
uv run pytest -v
```

Expected: All tests PASS

**Step 2: Push to PR**

```bash
git push
```
