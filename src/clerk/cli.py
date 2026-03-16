"""Command-line interface for clerk.

This module provides the main CLI commands for managing civic data pipelines,
including site creation, data fetching, OCR processing, and database operations.
"""

import atexit
import datetime
import logging
import os
import sys
import time
from sqlite3 import OperationalError

import click
import sqlite_utils
from dotenv import find_dotenv, load_dotenv

# Load .env file BEFORE local imports so extraction.py can read env vars
# Use find_dotenv() to search parent directories for .env file
load_dotenv(find_dotenv())

# ruff: noqa: E402

from . import output
from .db import db
from .debug import debug
from .etl import etl
from .extract_cli import extract
from .fetcher import Fetcher
from .output import log
from .plugin_loader import load_plugins_from_directory, load_plugins_from_entry_points
from .sentry import init_sentry
from .utils import assert_db_exists, pm

# Initialize Sentry for error tracking (if SENTRY_DSN is configured)
init_sentry()

logger = logging.getLogger(__name__)


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


def configure_logging(command_name: str = "unknown"):
    """Configure logging to push to Loki (if configured) and console."""
    handlers = []

    # Always add console handler for local visibility
    console = logging.StreamHandler()
    console.setFormatter(JsonFormatter())
    handlers.append(console)

    # Add Loki handler if URL is configured
    loki_url = os.environ.get("LOKI_URL")
    if loki_url:
        import logging_loki

        # Use synchronous LokiHandler instead of LokiQueueHandler
        # LokiQueueHandler uses a background thread that doesn't survive RQ worker forks
        loki_handler = logging_loki.LokiHandler(
            url=f"{loki_url}/loki/api/v1/push",
            tags={"job": "clerk", "host": os.uname().nodename, "command": command_name},
            version="1",
        )
        loki_handler.setFormatter(JsonFormatter())
        handlers.append(loki_handler)

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


STORAGE_DIR = os.environ.get("STORAGE_DIR", "../sites")


@click.group()
@click.version_option()
@click.option(
    "--plugins-dir",
    default="./plugins",
    type=click.Path(),
    help="Directory to load plugins from",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress console output (logs still go to Loki)",
)
@click.pass_context
def cli(ctx, plugins_dir, quiet):
    """Managing civic.band sites"""
    configure_logging(ctx.invoked_subcommand or "cli")
    output.configure(quiet=quiet)
    # Load directory-based plugins if specified
    load_plugins_from_directory(plugins_dir)


def _load_entry_point_plugins():
    """Load plugins from entry points and register their commands.

    This is called after module initialization to avoid circular imports.
    """
    load_plugins_from_entry_points()

    # Register plugin CLI commands from entry points
    for plugin_commands in pm.hook.register_cli_commands():
        if plugin_commands:
            # Add the command or group directly to preserve structure
            cli.add_command(plugin_commands)


# Load entry point plugins after the module is fully initialized
# We do this at the end of the module to avoid circular import issues
_load_entry_point_plugins()


def fetch_internal(subdomain: str, fetcher: Fetcher):
    from .db import civic_db_connection, update_site

    logger.info("Starting fetch subdomain=%s", subdomain)
    with civic_db_connection() as conn:
        update_site(
            conn,
            subdomain,
            {
                "status": "fetching",
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
    st = time.time()
    fetcher.fetch_events()
    et = time.time()
    elapsed_time = et - st
    log(
        f"Fetch time: {elapsed_time:.2f} seconds",
        subdomain=subdomain,
        elapsed_time=f"{elapsed_time:.2f}",
    )
    status = "needs_ocr"
    with civic_db_connection() as conn:
        update_site(
            conn,
            subdomain,
            {
                "status": status,
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )


def rebuild_site_fts_internal(subdomain):
    log("Rebuilding FTS indexes", subdomain=subdomain)
    site_db = sqlite_utils.Database(f"{STORAGE_DIR}/{subdomain}/meetings.db")
    for table_name in site_db.table_names():
        if table_name.startswith("pages_"):
            site_db[table_name].drop(ignore=True)
    try:
        site_db["agendas"].enable_fts(["text"])
    except OperationalError as e:
        log(str(e), subdomain=subdomain, level="error")
    try:
        site_db["minutes"].enable_fts(["text"])
    except OperationalError as e:
        log(str(e), subdomain=subdomain, level="error")


def update_page_count(subdomain):
    from .db import civic_db_connection, update_site

    assert_db_exists()
    site_db = sqlite_utils.Database(f"{STORAGE_DIR}/{subdomain}/meetings.db")
    agendas_count = site_db["agendas"].count
    minutes_count = site_db["minutes"].count
    page_count = agendas_count + minutes_count
    logger.info(
        "Page count updated subdomain=%s agendas=%d minutes=%d total=%d",
        subdomain,
        agendas_count,
        minutes_count,
        page_count,
    )
    with civic_db_connection() as conn:
        update_site(
            conn,
            subdomain,
            {
                "pages": page_count,
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )


@cli.command()
@click.argument(
    "worker_type", type=click.Choice(["fetch", "ocr", "compilation", "extraction", "deploy"])
)
@click.option("--num-workers", "-n", type=int, default=1, help="Number of workers to start")
@click.option("--burst", is_flag=True, help="Exit when queue empty (for testing)")
def worker(worker_type, num_workers, burst):
    """Start RQ workers."""
    import redis
    from rq import Worker
    from rq.worker_pool import WorkerPool

    class DiagnosticWorker(Worker):
        """Custom RQ Worker with pre-fork diagnostic logging."""

        def perform_job(self, job, queue):
            """Override to add logging before and after fork happens."""
            import sys

            # Log BEFORE forking work-horse (this is in parent process)
            try:
                # Safely convert args to string (handles MagicMock in tests)
                args_str = str(job.args) if job.args else "none"
                args_preview = args_str[:50] if len(args_str) > 50 else args_str
                # Use structured logging for Loki/Grafana visibility
                logger.info(
                    "worker_pre_fork",
                    extra={
                        "stage": "pre_fork",
                        "job_id": job.id,
                        "func_name": job.func_name,
                        "args_preview": args_preview,
                    },
                )
                sys.stderr.flush()
            except Exception:
                pass

            # Call parent implementation (this will fork and execute job)
            result = super().perform_job(job, queue)

            # Log AFTER fork completes (back in parent process)
            try:
                logger.info(
                    "worker_post_fork",
                    extra={
                        "stage": "post_fork",
                        "job_id": job.id,
                    },
                )
                sys.stderr.flush()
            except Exception:
                pass

            return result

    from .queue import (
        get_compilation_queue,
        get_deploy_queue,
        get_extraction_queue,
        get_fetch_queue,
        get_high_queue,
        get_ocr_queue,
        get_redis,
    )

    # Validate Redis connection before starting workers
    try:
        get_redis()
    except (redis.ConnectionError, redis.TimeoutError) as e:
        click.secho(f"Error: Cannot connect to Redis: {e}", fg="red")
        raise click.Abort() from e

    # Map worker types to queue lists (each worker checks high priority first)
    queue_map = {
        "fetch": [get_high_queue(), get_fetch_queue()],
        "ocr": [get_high_queue(), get_ocr_queue()],
        "compilation": [get_high_queue(), get_compilation_queue()],
        "extraction": [get_high_queue(), get_extraction_queue()],
        "deploy": [get_high_queue(), get_deploy_queue()],
    }

    # Default job timeouts per worker type (for jobs without explicit timeout)
    # Note: Individual jobs can override with job_timeout parameter when enqueuing
    timeout_map: dict[str, int] = {
        "fetch": 3600,  # 1 hour - fetching PDFs from city websites
        "ocr": 3600,  # 1 hour - OCR can be slow, especially with Vision
        "compilation": 3600,  # 1 hour - database compilation with large datasets
        "extraction": 7200,  # 2 hours - LLM-based entity extraction
        "deploy": 600,  # 10 minutes - S3 upload and CDN deployment
    }

    queues = queue_map[worker_type]
    default_timeout = timeout_map[worker_type]

    if num_workers == 0:
        click.secho(f"Not starting workers for {worker_type}")
        return

    if num_workers == 1:
        # Single worker with diagnostic logging
        worker_instance = DiagnosticWorker(
            queues, connection=get_redis(), default_worker_ttl=default_timeout
        )
        worker_instance.work(with_scheduler=True, burst=burst)
    else:
        # Worker pool for multiple workers
        # WorkerPool passes worker_class parameter to use our DiagnosticWorker
        pool = WorkerPool(
            queues,
            num_workers=num_workers,
            connection=get_redis(),
            default_worker_ttl=default_timeout,
            worker_class=DiagnosticWorker,
        )
        pool.start(burst=burst)


cli.add_command(extract)
cli.add_command(db)
cli.add_command(debug)
cli.add_command(etl)
