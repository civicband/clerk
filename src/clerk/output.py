"""Unified logging and console output."""

from __future__ import annotations

import logging
import sys

import click

pylogger = logging.getLogger(__name__)

# Global state set by CLI
_quiet = False
_default_subdomain = None


class ClerkLogger:
    quiet = False
    subdomain: str | None = None
    meeting: str | None = None
    job_id: str | None = None
    run_id: str | None = None
    backend: str | None = None
    date: str | None = None
    stage: str | None = None

    def __init__(
        self,
        subdomain: str | None = None,
        job_id: str | None = None,
        stage: str | None = None,
        run_id: str | None = None,
        backend: str | None = None,
    ) -> None:
        self.subdomain = subdomain
        self.job_id = job_id
        self.stage = stage
        self.run_id = run_id
        self.backend = backend

    def log(
        self,
        message: str,
        level: str = "info",
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
        sub = self.subdomain or _default_subdomain

        # Build extra dict for structured logging fields
        extra: dict = {}
        if sub:
            extra["subdomain"] = sub

        # Add structured logging fields (only if not None)
        if self.run_id is not None:
            extra["run_id"] = self.run_id
        if self.stage is not None:
            extra["stage"] = self.stage
        if self.job_id is not None:
            extra["job_id"] = self.job_id
        if parent_job_id is not None:
            extra["parent_job_id"] = parent_job_id
        if self.meeting is not None:
            extra["meeting"] = self.meeting
        if self.backend is not None:
            extra["backend"] = self.backend
        if self.date is not None:
            extra["meeting_date"] = self.date

        if kwargs:
            extra.update(kwargs)

        # Log to Python logging with extra fields
        log_func = getattr(pylogger, level, pylogger.info)
        log_func(message, extra=extra)
        # Force flush to ensure logs reach disk before potential crash
        sys.stderr.flush()
        sys.stdout.flush()

        # Click output (unless quiet)
        if not _quiet:
            prefix = click.style(f"{sub}: ", fg="cyan") if sub else ""
            click.echo(prefix + message)


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


logger = ClerkLogger()
