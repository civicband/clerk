"""OCR processing utilities for logging, progress tracking, and error handling."""

import httpx
import subprocess
from xml.etree.ElementTree import ParseError

# Optional PDF dependencies
try:
    from pypdf.errors import PdfReadError
except ImportError:
    # Create a placeholder exception type that will never match
    class PdfReadError(Exception):
        """Placeholder for when pypdf is not installed."""
        pass


# Transient errors - retry with backoff
TRANSIENT_ERRORS = (
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    OSError,  # Temporary file system issues
)

# Permanent errors - log and skip
PERMANENT_ERRORS = (
    PdfReadError,
    subprocess.CalledProcessError,  # Tesseract failures
    ParseError,
)

# Critical errors - fail fast
CRITICAL_ERRORS = (
    FileNotFoundError,  # Storage dir doesn't exist
    PermissionError,    # Can't write to storage
    ImportError,        # Missing dependencies
)
