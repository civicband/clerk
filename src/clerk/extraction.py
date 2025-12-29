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
