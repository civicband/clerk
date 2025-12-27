"""Unified logging and console output."""

import logging

import click

logger = logging.getLogger(__name__)

# Global state set by CLI
_quiet = False
_default_subdomain = None

LEVEL_COLORS = {
    "error": "red",
    "warning": "yellow",
    "info": None,  # default terminal color
    "debug": "dim",
}


def configure(quiet: bool = None, subdomain: str = None):
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


def log(message: str, subdomain: str = None, level: str = "info", **kwargs):
    """Unified logging + click output.

    - Always logs to Python logging (-> Loki if configured)
    - click.echo with colored output unless --quiet flag is set

    Args:
        message: The message to log/display
        subdomain: Optional subdomain prefix (uses default if not provided)
        level: Log level - "debug", "info", "warning", "error"
        **kwargs: Additional structured fields for logging
    """
    sub = subdomain or _default_subdomain

    # Build log message with kwargs for structured logging
    log_msg = message
    if kwargs:
        log_msg += " " + " ".join(f"{k}={v}" for k, v in kwargs.items())
    if sub:
        log_msg = f"subdomain={sub} {log_msg}"

    # Log to Python logging
    log_func = getattr(logger, level, logger.info)
    log_func(log_msg)

    # Click output (unless quiet)
    if not _quiet:
        prefix = click.style(f"{sub}: ", fg="cyan") if sub else ""
        color = LEVEL_COLORS.get(level)
        styled_msg = click.style(message, fg=color) if color else message
        click.echo(prefix + styled_msg)
