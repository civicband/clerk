"""Command-line interface for clerk.

This module provides the main CLI commands for managing civic data pipelines,
including site creation, data fetching, OCR processing, and database operations.
"""

import os

import click
from dotenv import find_dotenv, load_dotenv

# Load .env file BEFORE local imports so extraction.py can read env vars
# Use find_dotenv() to search parent directories for .env file
load_dotenv(find_dotenv())
# ruff: noqa: E402

from . import output
from .db import db
from .etl import etl
from .output import configure_logging, logger
from .plugin_loader import load_plugins_from_directory, load_plugins_from_entry_points
from .sheets import sheets
from .utils import pm


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
def cli(_, plugins_dir: str, quiet: bool):
    """Managing civic.band sites"""
    configure_logging()
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
            # Call parent implementation (this will fork and execute job)
            result = super().perform_job(job, queue)
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
        logger.log(message=f"Not starting workers for {worker_type}")
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


cli.add_command(db)
cli.add_command(etl)
cli.add_command(sheets)
