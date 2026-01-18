"""Sentry integration for error tracking and monitoring.

Initializes Sentry SDK if SENTRY_DSN environment variable is set.
"""

import os
import re

import sentry_sdk


def before_send(event, hint):
    """Normalize error fingerprints for better grouping in Sentry.

    Groups similar errors together even when they contain site-specific data
    (paths, committee names, URLs) to reduce noise in error tracking.

    Args:
        event: Sentry event dict
        hint: Additional context about the event

    Returns:
        Modified event with custom fingerprint, or None to drop the event
    """
    message = None
    exc_type = None

    # Extract message from either exception or log message
    if "exception" in event and event["exception"]["values"]:
        exc_value = event["exception"]["values"][0]
        message = exc_value.get("value", "")
        exc_type = exc_value.get("type", "")
    elif "logentry" in event:
        message = event["logentry"].get("message", "")
    elif "message" in event:
        message = event["message"]

    if not message:
        return event

    # Apply fingerprinting patterns
    # Pattern 1: "/path/to/file.pdf failed to read:" - PDF read errors
    if ".pdf failed to read:" in message:
        event["fingerprint"] = ["pdf-failed-to-read"]

    # Pattern 2: "/path/to/file.pdf failed to process:" - PDF processing errors
    elif ".pdf failed to process:" in message:
        event["fingerprint"] = ["pdf-failed-to-process"]

    # Pattern 3: "PDF file not found: /path/to/file.pdf" - Log messages
    elif "PDF file not found:" in message:
        event["fingerprint"] = ["pdf-file-not-found"]

    # Pattern 4: "No text files found in /path/to/site/txt" - OCR verification failures
    elif "No text files found in" in message:
        event["fingerprint"] = ["no-text-files-found"]

    # Pattern 5: "Error fetching year 2026 for [CommitteeName]" - Fetch failures
    elif "Error fetching year" in message:
        event["fingerprint"] = ["error-fetching-year"]

    # Pattern 6: "Error fetching https://..." - Network/HTTP errors
    elif "Error fetching https://" in message:
        # Group by domain, not full URL
        match = re.search(r"https://([^/]+)", message)
        if match:
            domain = match.group(1)
            event["fingerprint"] = ["fetch-error", domain]
        else:
            event["fingerprint"] = ["fetch-error", "unknown-domain"]

    # Pattern 7: "ocr_coordinator_failed: No text files found" - OCR coordinator
    elif "ocr_coordinator_failed" in message:
        event["fingerprint"] = ["ocr-coordinator-failed"]

    # Pattern 8: "Skipping empty PDF file" - Empty PDF handling
    elif "Skipping empty PDF file" in message:
        event["fingerprint"] = ["empty-pdf-file"]

    # Pattern 9: FileNotFoundError with paths - Missing PDFs or files
    elif exc_type == "FileNotFoundError":
        if "/pdfs/" in message:
            event["fingerprint"] = ["file-not-found", "pdf"]
        elif "/txt/" in message:
            event["fingerprint"] = ["file-not-found", "txt"]
        else:
            event["fingerprint"] = ["file-not-found", "other"]

    return event


def init_sentry():
    """Initialize Sentry SDK if SENTRY_DSN is configured.

    Environment variables:
        SENTRY_DSN: Sentry Data Source Name (DSN) URL
        SENTRY_ENVIRONMENT: Environment name (default: production)
        SENTRY_TRACES_SAMPLE_RATE: Traces sample rate (default: 0.0)

    Examples:
        export SENTRY_DSN="https://key@host/project"
        export SENTRY_ENVIRONMENT="production"
        export SENTRY_TRACES_SAMPLE_RATE="0.1"
    """
    sentry_dsn = os.getenv("SENTRY_DSN")

    if not sentry_dsn:
        # Sentry not configured, skip initialization
        return

    environment = os.getenv("SENTRY_ENVIRONMENT", "production")
    traces_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0"))

    # Import RQ integration to capture worker job exceptions
    from sentry_sdk.integrations.rq import RqIntegration

    sentry_sdk.init(
        dsn=sentry_dsn,
        environment=environment,
        send_default_pii=True,
        max_request_body_size="always",
        traces_sample_rate=traces_sample_rate,
        # Enable RQ integration to capture worker job exceptions
        integrations=[RqIntegration()],
        # Use custom fingerprinting to group similar errors
        before_send=before_send,
    )
