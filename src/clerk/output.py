"""Unified logging and console output."""

from __future__ import annotations

import logging
import sys

import click

logger = logging.getLogger(__name__)

# Global state set by CLI
_quiet = False
_default_subdomain = None


def configure(quiet: bool | None = None, subdomain: str | None = None):
    """Configure global output options.

    Args:
        quiet: If True, suppress click.echo output (logs still go to Loki)
        subdomain: Default subdomain prefix for log messages
    """
    global _quiet, _default_subdomain
    if quiet is not None:
        _quiet = quiet
    if subdomain is not None:
        _default_subdomain = subdomain


def log(
    message: str,
    subdomain: str | None = None,
    level: str = "info",
    run_id: str | None = None,
    stage: str | None = None,
    job_id: str | None = None,
    parent_job_id: str | None = None,
    **kwargs,
):
    """Unified logging + click output.

    - Always logs to Python logging (-> Loki if configured)
    - click.echo with colored output unless --quiet flag is set

    Args:
        message: The message to log/display
        subdomain: Optional subdomain prefix (uses default if not provided)
        level: Log level - "debug", "info", "warning", "error"
        run_id: Pipeline execution identifier
        stage: Current pipeline stage (fetch/ocr/compilation/extraction/deploy)
        job_id: Current RQ job ID
        parent_job_id: Parent RQ job ID for spawned jobs
        **kwargs: Additional structured fields for logging
    """
    sub = subdomain or _default_subdomain

    # Build extra dict for structured logging fields
    extra: dict = {}
    if sub:
        extra["subdomain"] = sub

    # Add structured logging fields (only if not None)
    if run_id is not None:
        extra["run_id"] = run_id
    if stage is not None:
        extra["stage"] = stage
    if job_id is not None:
        extra["job_id"] = job_id
    if parent_job_id is not None:
        extra["parent_job_id"] = parent_job_id

    if kwargs:
        extra.update(kwargs)

    # Log to Python logging with extra fields
    log_func = getattr(logger, level, logger.info)
    log_func(message, extra=extra)
    # Force flush to ensure logs reach disk before potential crash
    sys.stderr.flush()
    sys.stdout.flush()

    # Click output (unless quiet)
    if not _quiet:
        prefix = click.style(f"{sub}: ", fg="cyan") if sub else ""
        click.echo(prefix + message)
