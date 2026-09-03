"""Unified logging and console output."""

from __future__ import annotations

import atexit
import logging
import sys

import click

pylogger = logging.getLogger(__name__)

# Global state set by CLI
_quiet = False
_default_subdomain = None


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    # Standard LogRecord attributes to exclude from extra fields
    RESERVED_ATTRS = {
        "name",
        "msg",
        "args",
        "created",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "exc_info",
        "exc_text",
        "thread",
        "threadName",
        "taskName",
        "message",
    }

    def format(self, record):
        import json

        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include extra fields passed via extra={}
        for key, value in record.__dict__.items():
            if key not in self.RESERVED_ATTRS and not key.startswith("_"):
                log_record[key] = value

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


def configure_logging():
    """Configure logging to push to Loki (if configured) and console."""
    handlers = []

    # Always add console handler for local visibility
    console = logging.StreamHandler()
    console.setFormatter(JsonFormatter())
    handlers.append(console)
    logging.basicConfig(
        level=logging.INFO,
        handlers=handlers,
    )

    # Suppress noisy httpx logs (we log requests ourselves)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Register atexit handler to flush logs on exit
    def flush_logs_on_exit():
        """Flush all log handlers on exit."""
        sys.stderr.flush()
        sys.stdout.flush()
        for handler in logging.getLogger().handlers:
            handler.flush()

    atexit.register(flush_logs_on_exit)


class ClerkLogger:
    quiet: bool = False
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
        **kwargs,  # pyright: ignore[reportMissingParameterType, reportUnknownParameterType]
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
        extra: dict = {}  # pyright: ignore[reportMissingTypeArgument, reportUnknownVariableType]
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
            extra.update(kwargs)  # pyright: ignore[reportUnknownMemberType]

        # Log to Python logging with extra fields
        log_func = getattr(pylogger, level, pylogger.info)
        _ = log_func(message, extra=extra)  # pyright: ignore[reportUnknownArgumentType]
        # Force flush to ensure logs reach disk before potential crash
        _ = sys.stderr.flush()
        _ = sys.stdout.flush()

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
