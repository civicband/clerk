"""Text extraction pipeline for entities and votes.

This module provides NER-based entity extraction and regex-based vote extraction
for civic meeting documents. Extraction is feature-flagged via ENABLE_EXTRACTION
environment variable.
"""

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# Feature flag - off by default for safe rollout
EXTRACTION_ENABLED = os.environ.get("ENABLE_EXTRACTION", "0") == "1"

# Confidence threshold for entity filtering
ENTITY_CONFIDENCE_THRESHOLD = float(os.environ.get("ENTITY_CONFIDENCE_THRESHOLD", "0.7"))

# Lazy-loaded spaCy model
_nlp = None
_nlp_load_attempted = False


def get_nlp():
    """Get the spaCy NLP model, loading lazily on first call.

    Returns None if spaCy is not installed or model not downloaded.
    Logs errors but doesn't raise - allows graceful degradation.
    """
    global _nlp, _nlp_load_attempted

    if _nlp_load_attempted:
        return _nlp

    _nlp_load_attempted = True

    try:
        import spacy
    except ImportError:
        logger.warning("spaCy not installed - entity extraction disabled")
        return None

    try:
        _nlp = spacy.load("en_core_web_md")
        logger.info("Loaded spaCy model en_core_web_md")
    except OSError:
        logger.error(
            "spaCy model en_core_web_md not found. Run: python -m spacy download en_core_web_md"
        )
        return None

    # Add EntityRuler for title + name patterns (runs before NER)
    # This helps catch "Councilmember Smith" as PERSON even if NER misses it
    if "entity_ruler" not in _nlp.pipe_names:
        ruler = _nlp.add_pipe("entity_ruler", before="ner")
        _add_title_patterns(ruler)
        logger.info("Added EntityRuler with title patterns")

    return _nlp


# Titles that precede person names in civic documents
CIVIC_TITLES = [
    "Mayor",
    "Vice Mayor",
    "Council Member",
    "Councilmember",
    "Councilwoman",
    "Councilman",
    "Commissioner",
    "Chair",
    "Vice Chair",
    "Chairman",
    "Chairwoman",
    "President",
    "Vice President",
    "Member",
    "Supervisor",
    "Alderman",
    "Alderwoman",
    "Selectman",
    "Selectwoman",
    "Director",
    "Secretary",
    "Treasurer",
    "Clerk",
    "Mr.",
    "Mrs.",
    "Ms.",
    "Dr.",
]


def _add_title_patterns(ruler) -> None:
    """Add patterns for civic titles + proper names to EntityRuler."""
    patterns = []
    for title in CIVIC_TITLES:
        # Pattern: Title + capitalized word (e.g., "Councilmember Smith")
        patterns.append(
            {
                "label": "PERSON",
                "pattern": [
                    {"LOWER": title.lower()},
                    {"IS_TITLE": True},  # Capitalized word
                ],
            }
        )
        # Pattern: Title + two capitalized words (e.g., "Mayor John Smith")
        patterns.append(
            {
                "label": "PERSON",
                "pattern": [
                    {"LOWER": title.lower()},
                    {"IS_TITLE": True},
                    {"IS_TITLE": True},
                ],
            }
        )
    ruler.add_patterns(patterns)


def add_known_persons_to_ruler(known_persons: set[str]) -> None:
    """Add known person names to the EntityRuler for better recognition.

    Call this with names accumulated from previous pages to help
    recognize the same names on subsequent pages.

    Args:
        known_persons: Set of person name strings
    """
    nlp = get_nlp()
    if nlp is None or "entity_ruler" not in nlp.pipe_names:
        return

    ruler = nlp.get_pipe("entity_ruler")

    # Add exact match patterns for known names
    patterns = []
    for name in known_persons:
        # Skip very short names (likely false positives)
        if len(name) < 3:
            continue
        # Add as exact phrase match
        patterns.append(
            {
                "label": "PERSON",
                "pattern": name,
            }
        )

    if patterns:
        ruler.add_patterns(patterns)


# Lazy-loaded matchers
_vote_matcher = None
_motion_matcher = None
_rollcall_matcher = None


# Words indicating vote passed
PASS_LEMMAS = {"pass", "carry", "approve"}
# Words indicating vote failed
FAIL_LEMMAS = {"defeat", "fail", "reject"}

# Objects that indicate a parliamentary motion (not relocation)
MOTION_OBJECTS = {
    "motion",
    "resolution",
    "approval",
    "item",
    "amendment",
    "ordinance",
    "measure",
    "recommendation",
    "action",
    "adoption",
}


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
    _vote_matcher.add(
        "TALLY_VOTE",
        [
            [
                {"LEMMA": {"IN": ["pass", "carry", "approve", "defeat", "fail", "reject"]}},
                {"LIKE_NUM": True},
                {"TEXT": "-"},
                {"LIKE_NUM": True},
            ]
        ],
    )

    # Pattern 2a: Unanimous (verb + unanimously)
    _vote_matcher.add(
        "UNANIMOUS_VOTE",
        [
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
        ],
    )

    # Pattern 3: Voice vote
    _vote_matcher.add(
        "VOICE_VOTE",
        [
            [
                {"LOWER": {"IN": ["by", "on"]}},
                {"LOWER": "a", "OP": "?"},
                {"LOWER": "voice"},
                {"LOWER": "vote"},
            ]
        ],
    )

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
    _motion_matcher.add(
        "MOTION_ACTIVE",
        [
            [
                {"RIGHT_ID": "verb", "RIGHT_ATTRS": {"LEMMA": {"IN": ["move", "second"]}}},
                {
                    "LEFT_ID": "verb",
                    "REL_OP": ">",
                    "RIGHT_ID": "subject",
                    "RIGHT_ATTRS": {"DEP": "nsubj"},
                },
            ]
        ],
    )

    # Pattern 2: Passive voice - "moved/seconded by Smith"
    _motion_matcher.add(
        "MOTION_PASSIVE",
        [
            [
                {"RIGHT_ID": "verb", "RIGHT_ATTRS": {"LEMMA": {"IN": ["move", "second"]}}},
                {
                    "LEFT_ID": "verb",
                    "REL_OP": ">",
                    "RIGHT_ID": "agent",
                    "RIGHT_ATTRS": {"DEP": "agent"},
                },
            ]
        ],
    )

    return _motion_matcher


def _get_rollcall_matcher(nlp):
    """Get Token Matcher for roll call patterns, initializing lazily.

    Patterns detect:
    - "Ayes:" or "Aye:" markers
    - "Nays:" or "Nay:" markers
    """
    global _rollcall_matcher

    if _rollcall_matcher is not None:
        return _rollcall_matcher

    try:
        from spacy.matcher import Matcher
    except ImportError:
        return None

    _rollcall_matcher = Matcher(nlp.vocab)

    # Pattern: "Ayes:" or "Aye:"
    _rollcall_matcher.add(
        "AYES_MARKER",
        [
            [{"LOWER": {"IN": ["ayes", "aye"]}}, {"TEXT": ":"}],
        ],
    )

    # Pattern: "Nays:" or "Nay:"
    _rollcall_matcher.add(
        "NAYS_MARKER",
        [
            [{"LOWER": {"IN": ["nays", "nay"]}}, {"TEXT": ":"}],
        ],
    )

    return _rollcall_matcher


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


def _extract_motion_attribution_spacy(doc: Any) -> dict | None:
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

    for _match_id, token_ids in matches:
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


def _extract_vote_results_spacy(doc: Any) -> list[dict]:
    """Extract vote results using Token Matcher.

    Args:
        doc: spaCy Doc object

    Returns:
        List of vote record dicts
    """
    nlp = get_nlp()
    if nlp is None:
        return []

    matcher = _get_vote_matcher(nlp)
    if matcher is None:
        return []

    votes = []
    matches = matcher(doc)

    for match_id, start, end in matches:
        span = doc[start:end]
        match_name = nlp.vocab.strings[match_id]

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

                if verb_lemma is None:
                    # No matching verb found, skip this match
                    logger.warning("TALLY_VOTE match without recognized verb: %s", span.text)
                    continue

                result = "passed" if verb_lemma in PASS_LEMMAS else "failed"

                votes.append(
                    _create_vote_record(
                        result=result,
                        ayes=ayes,
                        nays=nays,
                        raw_text=span.text,
                    )
                )

        elif match_name == "UNANIMOUS_VOTE":
            votes.append(
                _create_vote_record(
                    result="passed",
                    ayes=None,
                    nays=0,
                    raw_text=span.text,
                )
            )

        elif match_name == "VOICE_VOTE":
            votes.append(
                _create_vote_record(
                    result="passed",
                    ayes=None,
                    nays=None,
                    raw_text=span.text,
                )
            )

    return votes


def parse_text(text: str) -> Any:
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


def parse_texts_batch(
    texts: list[str], batch_size: int = 500, n_process: int = 1
) -> list[Any]:
    """Parse multiple texts with spaCy using nlp.pipe() for efficiency.

    Args:
        texts: List of texts to parse
        batch_size: Number of texts to process at once (default 500)
        n_process: Number of parallel processes (default 1, set higher for multicore)
                   Note: n_process > 1 may have issues on macOS due to fork behavior

    Returns:
        List of spaCy Doc objects (or None for each if unavailable)
    """
    if not EXTRACTION_ENABLED:
        return [None] * len(texts)
    nlp = get_nlp()
    if nlp is None:
        return [None] * len(texts)
    try:
        # nlp.pipe() is much more efficient than calling nlp() repeatedly
        # n_process > 1 enables multiprocessing for additional speedup
        if n_process > 1:
            return list(nlp.pipe(texts, batch_size=batch_size, n_process=n_process))
        else:
            return list(nlp.pipe(texts, batch_size=batch_size))
    except Exception as e:
        logger.error(f"spaCy batch processing failed: {e}")
        return [None] * len(texts)


def extract_entities(text: str, doc: Any = None, threshold: float | None = None) -> dict:
    """Extract named entities from text using spaCy NER.

    Args:
        text: The text to extract entities from
        doc: Optional precomputed spaCy Doc (avoids re-parsing)
        threshold: Minimum confidence score (defaults to ENTITY_CONFIDENCE_THRESHOLD)

    Returns:
        Dict with keys 'persons', 'orgs', 'locations', each containing
        list of {'text': str, 'confidence': float} dicts
    """
    empty_result: dict[str, list] = {"persons": [], "orgs": [], "locations": []}

    if not EXTRACTION_ENABLED:
        return empty_result

    # Use precomputed doc or parse text
    if doc is None:
        doc = parse_text(text)
    if doc is None:
        return empty_result

    if threshold is None:
        threshold = ENTITY_CONFIDENCE_THRESHOLD

    # Use sets to track seen entities for deduplication
    seen_persons = set()
    seen_orgs = set()
    seen_locations = set()

    persons = []
    orgs = []
    locations = []

    for ent in doc.ents:
        # Clean entity text: normalize whitespace and remove line breaks
        cleaned_text = " ".join(ent.text.split())

        # Skip empty or very short entities after cleaning
        if len(cleaned_text) < 2:
            continue

        # spaCy transformer models don't have direct confidence scores,
        # but we can use the model's certainty through the kb_id or similar.
        # For now, we'll use a heuristic based on entity length and type.
        # In practice, transformer models are high-confidence.
        confidence = 0.85  # Default for transformer model

        if confidence < threshold:
            continue

        entity_data = {"text": cleaned_text, "confidence": confidence}

        # Deduplicate by checking if we've seen this text before
        if ent.label_ == "PERSON":
            if cleaned_text not in seen_persons:
                seen_persons.add(cleaned_text)
                persons.append(entity_data)
        elif ent.label_ == "ORG":
            if cleaned_text not in seen_orgs:
                seen_orgs.add(cleaned_text)
                orgs.append(entity_data)
        elif ent.label_ in ("GPE", "LOC", "FAC"):
            if cleaned_text not in seen_locations:
                seen_locations.add(cleaned_text)
                locations.append(entity_data)

    return {"persons": persons, "orgs": orgs, "locations": locations}


def detect_roll_call(text: str) -> list[str] | None:
    """Detect roll call patterns and extract attendee names.

    Looks for patterns like:
    - "Present: Smith, Jones, Lee"
    - "Roll Call: Members present were..."
    - "Attending: Council Member Smith, Council Member Jones"

    Args:
        text: The text to search for roll call patterns

    Returns:
        List of attendee names if roll call found, None otherwise
    """
    patterns = [
        r"(?:Present|Attending|Roll\s*Call)[:\s]+([^\n.]+)",
        r"Members\s+present\s+(?:were|are)[:\s]*([^\n.]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            names_section = match.group(1)
            names = _extract_names_from_list(names_section)
            if names:
                return names

    return None


def _extract_names_from_list(text: str) -> list[str]:
    """Extract names from a comma-separated or 'and'-separated list.

    Handles formats like:
    - "Smith, Jones, Lee"
    - "Smith, Jones, and Lee"
    - "Council Member Smith, Council Member Jones"
    """
    titles = [
        "Mayor",
        "Vice Mayor",
        "Council Member",
        "Councilmember",
        "Councilwoman",
        "Councilman",
        "Commissioner",
        "Chair",
        "Vice Chair",
        "President",
        "Vice President",
        "Member",
    ]

    cleaned = text
    for title in titles:
        cleaned = re.sub(rf"\b{title}\b", "", cleaned, flags=re.IGNORECASE)

    parts = re.split(r",\s*|\s+and\s+", cleaned)

    names = []
    for part in parts:
        name = part.strip()
        name = name.strip(".,;:")
        if name and len(name) > 1:
            names.append(name)

    return names


def extract_votes(text: str, doc: Any = None, meeting_context: dict | None = None) -> dict:
    """Extract vote records from text.

    Uses spaCy Matcher when available, falls back to regex.

    Args:
        text: The text to extract votes from
        doc: Optional precomputed spaCy Doc (avoids re-parsing)
        meeting_context: Optional dict with 'known_persons' and 'attendees'

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


def _extract_rollcall_votes_spacy(doc: Any) -> list[dict]:
    """Extract roll call votes using Token Matcher + NER.

    Uses Token Matcher to find Ayes/Nays structure, then extracts
    PERSON entities from those spans.

    Args:
        doc: spaCy Doc object

    Returns:
        List of vote records, empty if no roll call found
    """
    nlp = get_nlp()
    if nlp is None:
        return []

    matcher = _get_rollcall_matcher(nlp)
    if matcher is None:
        return []

    matches = matcher(doc)
    if not matches:
        return []

    # Find positions of Ayes/Nays markers
    ayes_positions = []
    nays_positions = []

    for match_id, _start, end in matches:
        label = nlp.vocab.strings[match_id]
        if label == "AYES_MARKER":
            ayes_positions.append(end)  # Position after the ":"
        elif label == "NAYS_MARKER":
            nays_positions.append(end)

    if not ayes_positions:
        return []  # No roll call found

    votes = []

    # Process each Ayes marker (could be multiple roll calls on a page)
    for ayes_pos in ayes_positions:
        # Find the corresponding Nays position (next one after this Ayes)
        nays_pos = None
        for np in nays_positions:
            if np > ayes_pos:
                nays_pos = np
                break

        # Find sentence end (period) for the nays section
        nays_end = len(doc)
        for j, token in enumerate(doc):
            if j > (nays_pos if nays_pos else ayes_pos) and token.text == ".":
                nays_end = j
                break

        # Extract PERSON entities in ayes span (from ayes_pos to nays_pos or sentence end)
        ayes_span_end = nays_pos - 2 if nays_pos else nays_end  # -2 to skip "Nays" and ":"
        ayes_names = []
        for ent in doc.ents:
            if ent.label_ == "PERSON" and ent.start >= ayes_pos and ent.end <= ayes_span_end:
                ayes_names.append(ent.text)

        # Extract PERSON entities in nays span (from nays_pos to sentence end)
        nays_names = []
        if nays_pos:
            for ent in doc.ents:
                if ent.label_ == "PERSON" and ent.start >= nays_pos and ent.end <= nays_end:
                    nays_names.append(ent.text)

        # Only create vote record if we found names
        if ayes_names or nays_names:
            individual_votes = []
            for name in ayes_names:
                individual_votes.append({"name": name, "vote": "aye"})
            for name in nays_names:
                individual_votes.append({"name": name, "vote": "nay"})

            # Get raw text for the roll call
            raw_start = ayes_pos - 2  # Include "Ayes:"
            raw_end = nays_end + 1 if nays_end < len(doc) else len(doc)
            raw_text = doc[raw_start:raw_end].text

            vote = _create_vote_record(
                result="passed" if len(ayes_names) > len(nays_names) else "failed",
                ayes=len(ayes_names),
                nays=len(nays_names),
                raw_text=raw_text,
                individual_votes=individual_votes,
            )
            votes.append(vote)

    return votes


def _extract_rollcall_votes_regex(text: str) -> list[dict]:
    """Extract roll call votes using regex pattern.

    Fallback when spaCy extraction returns empty.
    """
    votes = []
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
    return votes


def _extract_votes_spacy(doc: Any, text: str, meeting_context: dict) -> dict:
    """Extract votes using spaCy Matcher and DependencyMatcher."""
    votes = []

    # Get vote results from Token Matcher
    vote_results = _extract_vote_results_spacy(doc)
    votes.extend(vote_results)

    # Try spaCy roll call extraction first
    rollcall_votes = _extract_rollcall_votes_spacy(doc)
    if not rollcall_votes:
        # Fall back to regex if spaCy found no roll call votes
        rollcall_votes = _extract_rollcall_votes_regex(text)
    votes.extend(rollcall_votes)

    # Get motion attribution from DependencyMatcher
    motion_info = _extract_motion_attribution_spacy(doc)

    # Fall back to regex if no spaCy attribution
    if motion_info is None:
        motion_info = _extract_motion_info(text)

    # Apply motion info to votes
    for vote in votes:
        if motion_info:
            if vote["motion_by"] is None:
                vote["motion_by"] = motion_info.get("motion_by")
            if vote["seconded_by"] is None:
                vote["seconded_by"] = motion_info.get("seconded_by")

    return {"votes": votes}


def _extract_votes_regex(text: str, meeting_context: dict) -> dict:
    """Extract votes using regex patterns (fallback when spaCy unavailable)."""
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
    votes.extend(_extract_rollcall_votes_regex(text))

    # Try to extract motion/second for each vote
    motion_info = _extract_motion_info(text)
    for vote in votes:
        if motion_info:
            vote["motion_by"] = motion_info.get("motion_by")
            vote["seconded_by"] = motion_info.get("seconded_by")

    return {"votes": votes}


def _create_vote_record(
    result: str,
    ayes: int | None,
    nays: int | None,
    raw_text: str,
    individual_votes: list | None = None,
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
    }


def _extract_motion_info(text: str) -> dict | None:
    """Extract motion by and seconded by from text."""
    pattern = r"[Mm]otion\s+(?:by|from)\s+(\w+)(?:,?\s+seconded\s+by\s+(\w+))?"
    match = re.search(pattern, text)
    if match:
        return {
            "motion_by": match.group(1),
            "seconded_by": match.group(2) if match.group(2) else None,
        }
    return None


def create_meeting_context() -> dict:
    """Create an empty meeting context for accumulating information across pages.

    Returns:
        Dict with keys for tracking persons, orgs, attendees, and meeting type
    """
    return {
        "known_persons": set(),
        "known_orgs": set(),
        "attendees": [],
        # meeting_type is reserved for future use (e.g., "regular", "special", "closed session")
        "meeting_type": None,
    }


def update_context(
    context: dict,
    entities: dict | None = None,
    attendees: list[str] | None = None,
) -> None:
    """Update meeting context with new information.

    Args:
        context: The meeting context dict to update
        entities: Extracted entities dict from extract_entities()
        attendees: List of attendee names from detect_roll_call()
    """
    if entities:
        for person in entities.get("persons", []):
            context["known_persons"].add(person["text"])
        for org in entities.get("orgs", []):
            context["known_orgs"].add(org["text"])

    if attendees:
        # Accumulate attendees, avoiding duplicates
        existing = set(context["attendees"])
        for name in attendees:
            if name not in existing:
                context["attendees"].append(name)
                existing.add(name)
        # Also add attendees to known_persons
        for name in attendees:
            context["known_persons"].add(name)
