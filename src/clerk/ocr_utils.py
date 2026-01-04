"""OCR processing utilities for logging, progress tracking, and error handling."""

import httpx
import subprocess
import time
from dataclasses import dataclass, field
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


@dataclass
class JobState:
    """Tracks OCR job progress and timing."""

    job_id: str
    total_documents: int
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    start_time: float = field(default_factory=time.time)
    current_document: str | None = None

    def progress_pct(self) -> float:
        """Calculate progress percentage."""
        processed = self.completed + self.failed + self.skipped
        return (processed / self.total_documents * 100) if self.total_documents > 0 else 0.0

    def eta_seconds(self) -> float | None:
        """Estimate time remaining in seconds.

        Returns:
            Estimated seconds until completion, or None if no progress yet
            or if total_documents is zero.
        """
        if self.total_documents == 0:
            return None

        processed = self.completed + self.failed + self.skipped
        if processed == 0:
            return None

        elapsed = time.time() - self.start_time
        rate = elapsed / processed
        remaining = self.total_documents - processed

        # Ensure we don't return negative ETA if somehow overprocessed
        return max(0.0, rate * remaining)
