"""Text extraction pipeline for entities and votes.

This module provides NER-based entity extraction and regex-based vote extraction
for civic meeting documents. Extraction is feature-flagged via ENABLE_EXTRACTION
environment variable.
"""

import logging
import os

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
