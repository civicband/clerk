"""OCR processing utilities for logging, progress tracking, and error handling."""

import click
import functools
import httpx
import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from xml.etree.ElementTree import ParseError

from clerk.output import log

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
    BlockingIOError,      # Resource temporarily unavailable
    ChildProcessError,    # Child process issues
    InterruptedError,     # System call interrupted
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


class FailureManifest:
    """Writes failure records to JSONL file with atomic appends."""

    def __init__(self, manifest_path: str):
        """Initialize manifest file in append mode.

        Args:
            manifest_path: Path to JSONL file
        """
        self.path = manifest_path
        self.file = open(manifest_path, 'a')

    def record_failure(
        self,
        job_id: str,
        document_path: str,
        meeting: str,
        date: str,
        error_type: str,
        error_class: str,
        error_message: str,
        retry_count: int
    ) -> None:
        """Record a document failure to the manifest.

        Args:
            job_id: Unique job identifier
            document_path: Path to failed document
            meeting: Meeting name
            date: Document date
            error_type: "transient", "permanent", or "critical"
            error_class: Exception class name
            error_message: Exception message
            retry_count: Number of retries attempted
        """
        entry = {
            "job_id": job_id,
            "document_path": document_path,
            "meeting": meeting,
            "date": date,
            "error_type": error_type,
            "error_class": error_class,
            "error_message": error_message,
            "failed_at": datetime.now().isoformat(),
            "retry_count": retry_count
        }
        self.file.write(json.dumps(entry) + '\n')
        self.file.flush()  # Ensure immediate write

    def close(self) -> None:
        """Close the manifest file."""
        self.file.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures file is closed."""
        self.close()
        return False


def retry_on_transient(max_attempts: int = 3, delay_seconds: float = 2):
    """Decorator to retry transient errors with fixed delay.

    Retries functions that raise transient errors (network timeouts, temporary
    file issues). Critical errors fail fast without retry.

    Args:
        max_attempts: Maximum number of attempts (default 3)
        delay_seconds: Delay between retries in seconds (default 2)

    Returns:
        Decorated function that retries on transient errors

    Example:
        @retry_on_transient(max_attempts=3, delay_seconds=2)
        def fetch_pdf(url):
            return httpx.get(url)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except TRANSIENT_ERRORS as e:
                    if attempt == max_attempts:
                        raise  # Exhausted retries

                    # Extract subdomain from kwargs if available for logging
                    subdomain = kwargs.get('subdomain', 'unknown')

                    log(
                        f"Transient error, retrying in {delay_seconds}s",
                        subdomain=subdomain,
                        level="warning",
                        error_class=e.__class__.__name__,
                        error_message=str(e),
                        retry_attempt=attempt,
                        max_retries=max_attempts,
                    )
                    time.sleep(delay_seconds)
                except CRITICAL_ERRORS:
                    raise  # Fail fast on critical errors
                # All other errors pass through (permanent errors)
        return wrapper
    return decorator


def print_progress(state: JobState) -> None:
    """Print human-readable progress to stderr.

    Args:
        state: JobState with current progress
    """
    pct = state.progress_pct()
    processed = state.completed + state.failed + state.skipped
    eta = state.eta_seconds()
    eta_str = f"ETA: {int(eta)}s" if eta else "calculating..."

    click.echo(
        f"OCR Progress: [{processed}/{state.total_documents}] "
        f"{pct:.1f}% complete, {state.failed} failed | {eta_str}",
        err=True
    )
