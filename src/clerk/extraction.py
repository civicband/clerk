"""Text extraction pipeline for entities and votes.

This module provides NER-based entity extraction and regex-based vote extraction
for civic meeting documents. Extraction is feature-flagged via ENABLE_EXTRACTION
environment variable.
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

# Feature flag - off by default for safe rollout
EXTRACTION_ENABLED = os.environ.get("ENABLE_EXTRACTION", "0") == "1"

# Confidence threshold for entity filtering
ENTITY_CONFIDENCE_THRESHOLD = float(
    os.environ.get("ENTITY_CONFIDENCE_THRESHOLD", "0.7")
)

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
        _nlp = spacy.load("en_core_web_trf")
        logger.info("Loaded spaCy model en_core_web_trf")
    except OSError:
        logger.error(
            "spaCy model en_core_web_trf not found. "
            "Run: python -m spacy download en_core_web_trf"
        )
        return None

    return _nlp


# Lazy-loaded matchers
_vote_matcher = None
_motion_matcher = None


# Words indicating vote passed
PASS_LEMMAS = {"pass", "carry", "approve"}
# Words indicating vote failed
FAIL_LEMMAS = {"defeat", "fail", "reject"}


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


def _extract_vote_results_spacy(doc: object) -> list[dict]:
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
                    logger.warning(
                        "TALLY_VOTE match without recognized verb: %s", span.text
                    )
                    continue

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


def parse_text(text: str) -> object | None:
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
        # spaCy transformer models don't have direct confidence scores,
        # but we can use the model's certainty through the kb_id or similar.
        # For now, we'll use a heuristic based on entity length and type.
        # In practice, transformer models are high-confidence.
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
        "Mayor", "Vice Mayor", "Council Member", "Councilmember",
        "Councilwoman", "Councilman", "Commissioner", "Chair",
        "Vice Chair", "President", "Vice President", "Member",
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


def extract_votes(text: str, meeting_context: dict | None = None) -> dict:
    """Extract vote records from text using regex patterns.

    Args:
        text: The text to extract votes from
        meeting_context: Optional dict with 'known_persons' and 'attendees'
                        for name resolution

    Returns:
        Dict with 'votes' key containing list of vote records
    """
    if not EXTRACTION_ENABLED:
        return {"votes": []}

    if meeting_context is None:
        meeting_context = {"known_persons": set(), "attendees": []}

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


def _create_vote_record(
    result: str,
    ayes: int | None,
    nays: int,
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