"""Command-line interface for clerk.

This module provides the main CLI commands for managing civic data pipelines,
including site creation, data fetching, OCR processing, and database operations.
"""

import atexit
import datetime
import json
import logging
import os
import shutil
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
from datetime import UTC

from . import output
from .db import civic_db_connection, db, get_site_by_subdomain, upsert_site
from .debug import debug
from .fetcher import Fetcher
from .output import log
from .plugin_loader import load_plugins_from_directory, load_plugins_from_entry_points
from .queue import enqueue_job, generate_run_id
from .sentry import init_sentry
from .utils import assert_db_exists, build_db_from_text_internal, pm

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


@cli.command()
@click.option(
    "--ocr-backend",
    type=click.Choice(["tesseract", "vision"], case_sensitive=False),
    default="tesseract",
    help="OCR backend to use (tesseract or vision). Defaults to tesseract.",
)
@click.option(
    "--fetch-local", is_flag=True, default=False, help="Fetch inline instead of sending through RQ"
)
def new(ocr_backend="tesseract", fetch_local=False):
    """Create a new site"""
    assert_db_exists()

    subdomain = click.prompt("Subdomain")
    with civic_db_connection() as conn:
        exists = get_site_by_subdomain(conn, subdomain)
    if exists:
        click.secho(f"Site {subdomain} already exists", fg="red")
        return

    name = click.prompt("Name", type=str)
    state = click.prompt("State", type=str)
    country = click.prompt("Country", default="US", type=str)
    kind = click.prompt("Kind", type=str)
    start_year = click.prompt("Start year", type=int)
    all_agendas = click.prompt("Fetch all agendas", type=bool, default=False)
    lat_lng = click.prompt("Lat, Lng")
    scraper = click.prompt("Scraper", type=str)

    extra = pm.hook.fetcher_extra(label=scraper)
    extra = list(filter(None, extra))
    if len(extra):
        extra = extra[0]

    # Create site in database

    with civic_db_connection() as conn:
        upsert_site(
            conn,
            {
                "subdomain": subdomain,
                "name": name,
                "state": state,
                "country": country,
                "kind": kind,
                "scraper": scraper,
                "pages": 0,
                "start_year": start_year,
                "status": "new",
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "lat": lat_lng.split(",")[0].strip(),
                "lng": lat_lng.split(",")[1].strip(),
                "extra": json.dumps(extra) if extra else "{}",
                "extraction_status": "pending",
                "last_extracted": None,
            },
        )

    click.echo(f"Site {subdomain} created")
    click.echo(f"Enqueueing new site {subdomain} with high priority")
    if fetch_local:
        from .queue import generate_run_id
        from .workers import fetch_site_job

        fetch_site_job(
            subdomain=subdomain,
            run_id=generate_run_id(subdomain),
            all_years=True,
            all_agendas=all_agendas,
            ocr_backend=ocr_backend,
        )
    else:
        enqueue_job(
            "fetch-site",
            subdomain,
            priority="high",
            all_years=True,
            all_agendas=all_agendas,
            ocr_backend=ocr_backend,
        )
    pm.hook.post_create(subdomain=subdomain)


@cli.command()
@click.option("-s", "--subdomain", help="Specific site subdomain")
@click.option("-n", "--next-site", is_flag=True, help="Enqueue oldest site (for auto-scheduler)")
@click.option("-a", "--all-years", is_flag=True)
@click.option("--skip-fetch", is_flag=True)
@click.option("--all-agendas", is_flag=True)
@click.option("--backfill", is_flag=True)
@click.option(
    "--fetch-local", is_flag=True, default=False, help="Fetch inline instead of sending through RQ"
)
@click.option(
    "--ocr-backend",
    type=click.Choice(["tesseract", "vision"], case_sensitive=False),
    default="tesseract",
    help="OCR backend to use (tesseract or vision). Defaults to tesseract.",
)
def update(
    subdomain, next_site, all_years, skip_fetch, all_agendas, backfill, fetch_local, ocr_backend
):
    """Update a site."""
    import datetime

    from .db import civic_db_connection, get_oldest_site, get_site_by_subdomain, upsert_site
    from .queue import enqueue_job

    if next_site:
        # Auto-scheduler mode: enqueue oldest site with normal priority
        oldest_subdomain = get_oldest_site(lookback_hours=23)
        if not oldest_subdomain:
            click.echo("No sites eligible for auto-enqueue")
            return

        click.echo(f"Auto-enqueueing {oldest_subdomain}")

        # Update last_updated BEFORE enqueueing to prevent race condition
        # (multiple cron runs picking the same site)
        with civic_db_connection() as conn:
            upsert_site(
                conn,
                {
                    "subdomain": oldest_subdomain,
                    "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                },
            )

        if fetch_local:
            from .workers import fetch_site_job

            fetch_site_job(oldest_subdomain, generate_run_id(oldest_subdomain))
        else:
            enqueue_job("fetch-site", oldest_subdomain, priority="normal")
        return

    if subdomain:
        # Manual update mode: enqueue specific site with high priority
        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, subdomain)
            if not site:
                click.secho(f"Error: Site '{subdomain}' not found", fg="red")
                raise click.Abort()

        click.echo(f"Enqueueing {subdomain} with high priority")

        # Build kwargs for job
        job_kwargs = {}
        if all_years:
            job_kwargs["all_years"] = True
        if all_agendas:
            job_kwargs["all_agendas"] = True
        if backfill:
            job_kwargs["backfill"] = True
        if ocr_backend:
            job_kwargs["ocr_backend"] = ocr_backend
        if skip_fetch:
            job_kwargs["skip_fetch"] = True

        if fetch_local:
            from .workers import fetch_site_job

            fetch_site_job(subdomain, run_id=generate_run_id(subdomain), **job_kwargs)
        else:
            enqueue_job("fetch-site", subdomain, priority="high", **job_kwargs)
        return

    # Error: must specify --subdomain or --next-site
    raise click.UsageError("Must specify --subdomain or --next-site")


def get_fetcher(site, all_years=False, all_agendas=False) -> Fetcher:  # type: ignore
    start_year = site["start_year"]
    fetcher_class = None
    try:
        start_year = datetime.datetime.strptime(site["last_updated"], "%Y-%m-%dT%H:%M:%S").year
    except TypeError:
        start_year = site["start_year"]
    if all_years:
        start_year = site["start_year"]
    fetcher_class = pm.hook.fetcher_class(label=site["scraper"])

    fetcher_class = list(filter(None, fetcher_class))
    if len(fetcher_class):
        fetcher_class = fetcher_class[0]

    if fetcher_class:
        return fetcher_class(site, start_year, all_agendas)  # type: ignore[no-any-return, operator]  # pyright: ignore[reportCallIssue]
    if site["scraper"] == "custom":
        import importlib

        module_path = f"fetchers.custom.{site['subdomain'].replace('.', '_')}"
        fetcher = importlib.import_module(module_path)
        return fetcher.custom_fetcher(site, start_year, all_agendas)  # type: ignore[no-any-return]


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


@cli.command()
@click.option(
    "-s",
    "--subdomain",
)
@click.option(
    "--extract-entities",
    is_flag=True,
    default=False,
    help="Extract entities for uncached pages (slower, ~20 min per site)",
)
@click.option(
    "--ignore-cache",
    is_flag=True,
    help="Ignore cache and extract all pages (requires --extract-entities)",
)
def build_db_from_text(subdomain, extract_entities, ignore_cache=False):
    """Build database from text files

    By default, rebuilds database from text files using cached entity extractions.
    Use --extract-entities to extract entities for uncached pages.
    Use --ignore-cache with --extract-entities to re-extract all pages.
    """
    build_db_from_text_internal(
        subdomain, extract_entities=extract_entities, ignore_cache=ignore_cache
    )
    rebuild_site_fts_internal(subdomain)


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
def remove_all_image_dirs():
    """Remove image directories for all sites"""
    sites_db = assert_db_exists()
    for site in sites_db.query("select subdomain from sites order by subdomain"):  # type: ignore
        subdomain = site["subdomain"]
        log("Removing image dir", subdomain=subdomain)
        image_dir = f"{STORAGE_DIR}/{subdomain}/images"
        if os.path.exists(image_dir):
            shutil.rmtree(image_dir)
        agendas_image_dir = f"{STORAGE_DIR}/{subdomain}/_agendas/images"
        if os.path.exists(agendas_image_dir):
            shutil.rmtree(agendas_image_dir)


@cli.command()
@click.option("-s", "--subdomain")
@click.option("-n", "--next-site", is_flag=True)
def extract_entities(subdomain, next_site=False):
    """Extract entities from site minutes using spaCy"""
    extract_entities_internal(subdomain, next_site)


def extract_entities_internal(subdomain, next_site=False):
    """Internal implementation of extract-entities command"""
    from sqlalchemy import text

    from .db import civic_db_connection, get_site_by_subdomain, update_site

    engine = assert_db_exists()

    if next_site:
        # Query for next site needing extraction
        with engine.connect() as conn:
            next_site_row = conn.execute(
                text("""
                SELECT subdomain FROM sites
                WHERE extraction_status IN ('pending', 'failed')
                ORDER BY last_extracted ASC NULLS FIRST
                LIMIT 1
            """)
            ).fetchone()

            if not next_site_row:
                log("No sites need extraction")
                return

            subdomain = next_site_row[0]
            log(f"Selected next site: {subdomain}")

    if not subdomain:
        log("Must specify --subdomain or --next-site", level="error")
        return

    # CRITICAL: Validate site exists (prevents path traversal)
    try:
        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, subdomain)
    except Exception:
        log(f"Site not found: {subdomain}", level="error")
        return

    if not site:
        log(f"Site not found: {subdomain}", level="error")
        return

    # Check if extraction already in progress
    with engine.connect() as conn:
        num_in_progress = conn.execute(
            text("SELECT COUNT(*) FROM sites WHERE extraction_status = 'in_progress'")
        ).fetchone()[0]  # type: ignore

    if num_in_progress > 0:
        log("Extraction already in progress, exiting")
        return

    # Mark as in_progress
    with civic_db_connection() as conn:
        update_site(conn, subdomain, {"extraction_status": "in_progress"})

    try:
        # Run extraction - rebuild DB from text with entity extraction enabled
        build_db_from_text_internal(subdomain, extract_entities=True, ignore_cache=False)
        rebuild_site_fts_internal(subdomain)

        # Mark extraction as completed BEFORE deployment
        with civic_db_connection() as conn:
            update_site(
                conn,
                subdomain,
                {
                    "extraction_status": "completed",
                    "last_extracted": datetime.datetime.now().isoformat(),
                },
            )

        log("Extraction completed successfully", subdomain=subdomain)

        # Deploy unless in dev mode (separate error handling)
        if not os.environ.get("CIVIC_DEV_MODE"):
            try:
                site_db = sqlite_utils.Database(f"{STORAGE_DIR}/{subdomain}/meetings.db")
                pm.hook.deploy_municipality(
                    subdomain=subdomain, municipality=site["name"], db=site_db
                )
                pm.hook.post_deploy(site=site)
                log("Deployed updated database", subdomain=subdomain)
            except Exception as deploy_error:
                log(
                    f"Deployment failed but extraction completed: {deploy_error}",
                    subdomain=subdomain,
                    level="error",
                )
                # Don't raise - extraction succeeded
        else:
            log("DEV MODE: Skipping deployment", subdomain=subdomain)

    except Exception as e:
        with civic_db_connection() as conn:
            update_site(conn, subdomain, {"extraction_status": "failed"})
        log(f"Extraction failed: {e}", subdomain=subdomain, level="error")
        raise


@cli.command()
@click.argument("subdomain")
def purge(subdomain):
    """Remove all jobs for a specific site"""
    import redis

    from .db import civic_db_connection
    from .queue import (
        get_deploy_queue,
        get_extraction_queue,
        get_fetch_queue,
        get_high_queue,
        get_ocr_queue,
    )
    from .queue_db import delete_jobs_for_site, delete_site_progress, get_jobs_for_site

    # Handle Redis connection errors
    try:
        # Use single database transaction to prevent race conditions
        with civic_db_connection() as conn:
            # Get all jobs for the site from database
            jobs = get_jobs_for_site(conn, subdomain)
            click.echo(f"Found {len(jobs)} job(s) for site {subdomain}")

            deleted_count = 0

            # Only connect to Redis if there are jobs to purge
            if jobs:
                # Cancel and delete each job from RQ (outside transaction is OK)
                queues = [
                    get_high_queue(),
                    get_fetch_queue(),
                    get_ocr_queue(),
                    get_extraction_queue(),
                    get_deploy_queue(),
                ]

                for job_data in jobs:
                    job_id = job_data["rq_job_id"]

                    # Try all queues
                    for queue in queues:
                        try:
                            job = queue.fetch_job(job_id)
                            if job:
                                job.cancel()
                                job.delete()
                                deleted_count += 1
                                break  # Found and deleted, no need to check other queues
                        except Exception:
                            # Job might not be in this queue, or other transient error
                            # Continue trying other queues
                            continue

            # Delete database records in same transaction
            delete_site_progress(conn, subdomain)
            delete_jobs_for_site(conn, subdomain)

            click.echo(f"Purged {deleted_count} job(s) from queues for site {subdomain}")
            click.echo(f"Deleted database records for site {subdomain}")

    except (redis.ConnectionError, redis.TimeoutError) as e:
        click.secho(f"Error: Cannot connect to Redis: {e}", fg="red")
        raise click.Abort() from e
    except Exception as e:
        click.secho(f"Error purging site: {e}", fg="red")
        raise click.Abort() from e


@cli.command()
@click.argument("queue_name")
def purge_queue(queue_name):
    """Clear an entire queue (emergency operation)"""
    import redis

    from .queue import (
        get_deploy_queue,
        get_extraction_queue,
        get_fetch_queue,
        get_high_queue,
        get_ocr_queue,
    )

    queues = {
        "high": get_high_queue,
        "fetch": get_fetch_queue,
        "ocr": get_ocr_queue,
        "extraction": get_extraction_queue,
        "deploy": get_deploy_queue,
    }

    if queue_name not in queues:
        click.secho(
            f"Error: Invalid queue name '{queue_name}'. Valid queues: {', '.join(queues.keys())}",
            fg="red",
        )
        raise click.Abort()

    # Handle Redis connection errors
    try:
        queue = queues[queue_name]()
        count = queue.empty()

        click.echo(f"Cleared {count} job(s) from '{queue_name}' queue")

    except (redis.ConnectionError, redis.TimeoutError) as e:
        click.secho(f"Error: Cannot connect to Redis: {e}", fg="red")
        raise click.Abort() from e
    except Exception as e:
        click.secho(f"Error clearing queue: {e}", fg="red")
        raise click.Abort() from e


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
    timeout_map = {
        "fetch": 3600,  # 1 hour - fetching PDFs from city websites
        "ocr": 3600,  # 1 hour - OCR can be slow, especially with Vision
        "compilation": 3600,  # 1 hour - database compilation with large datasets
        "extraction": 7200,  # 2 hours - LLM-based entity extraction
        "deploy": 600,  # 10 minutes - S3 upload and CDN deployment
    }

    queues = queue_map[worker_type]
    default_timeout = timeout_map[worker_type]

    if num_workers == 1:
        # Single worker with diagnostic logging
        worker_instance = DiagnosticWorker(
            queues, connection=get_redis(), default_worker_ttl=default_timeout
        )
        worker_instance.work(with_scheduler=True, burst=burst)
    else:
        # Worker pool for multiple workers
        # WorkerPool passes worker_class parameter to use our DiagnosticWorker
        with WorkerPool(
            queues,
            num_workers=num_workers,
            connection=get_redis(),
            default_worker_ttl=default_timeout,
            worker_class=DiagnosticWorker,
        ) as pool:  # type: ignore
            pool.start()


@cli.command()
def install_workers():
    """Install RQ workers as background services (macOS/Linux)."""
    import subprocess
    import sys
    from pathlib import Path

    # Try package location first (installed)
    package_scripts = Path(sys.prefix) / "share" / "clerk" / "scripts"

    # Try relative to this file (development)
    dev_scripts = Path(__file__).parent.parent.parent / "scripts"

    script_path = None
    if (package_scripts / "install-workers.sh").exists():
        script_path = package_scripts / "install-workers.sh"
    elif (dev_scripts / "install-workers.sh").exists():
        script_path = dev_scripts / "install-workers.sh"
    else:
        click.secho("Error: install-workers.sh script not found", fg="red")
        raise click.Abort()

    # Execute the script
    result = subprocess.run(
        [str(script_path)],
        cwd=Path.cwd(),  # Run in current directory (where .env is)
    )
    sys.exit(result.returncode)


@cli.command()
def uninstall_workers():
    """Uninstall RQ worker background services (macOS/Linux)."""
    import subprocess
    import sys
    from pathlib import Path

    # Try package location first (installed)
    package_scripts = Path(sys.prefix) / "share" / "clerk" / "scripts"

    # Try relative to this file (development)
    dev_scripts = Path(__file__).parent.parent.parent / "scripts"

    script_path = None
    if (package_scripts / "uninstall-workers.sh").exists():
        script_path = package_scripts / "uninstall-workers.sh"
    elif (dev_scripts / "uninstall-workers.sh").exists():
        script_path = dev_scripts / "uninstall-workers.sh"
    else:
        click.secho("Error: uninstall-workers.sh script not found", fg="red")
        raise click.Abort()

    # Execute the script
    result = subprocess.run(
        [str(script_path)],
        cwd=Path.cwd(),  # Run in current directory (where .env is)
    )
    sys.exit(result.returncode)


@cli.command()
def reload_workers():
    """Reload RQ worker background services after code changes (macOS/Linux)."""
    import subprocess
    import sys
    from pathlib import Path

    # Try package location first (installed)
    package_scripts = Path(sys.prefix) / "share" / "clerk" / "scripts"

    # Try relative to this file (development)
    dev_scripts = Path(__file__).parent.parent.parent / "scripts"

    script_path = None
    if (package_scripts / "reload-workers.sh").exists():
        script_path = package_scripts / "reload-workers.sh"
    elif (dev_scripts / "reload-workers.sh").exists():
        script_path = dev_scripts / "reload-workers.sh"
    else:
        click.secho("Error: reload-workers.sh script not found", fg="red")
        raise click.Abort()

    # Execute the script
    result = subprocess.run(
        [str(script_path)],
        cwd=Path.cwd(),  # Run in current directory (where .env is)
    )
    sys.exit(result.returncode)


@cli.command()
def diagnose_workers():
    """Diagnose worker installation and connection issues."""
    import subprocess
    from pathlib import Path

    def print_section(title):
        click.secho(f"\n=== {title} ===", fg="blue", bold=True)

    def print_success(msg):
        click.secho(f"✓ {msg}", fg="green")

    def print_error(msg):
        click.secho(f"✗ {msg}", fg="red")

    def print_warning(msg):
        click.secho(f"⚠ {msg}", fg="yellow")

    # 1. Check .env file
    print_section("1. Checking .env file")
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        print_success(f".env file exists at {env_path}")
    else:
        print_error(f".env file not found at {env_path}")
        click.echo("   Workers need .env file in the working directory")

    # 2. Check clerk executable
    print_section("2. Checking clerk executable")
    clerk_path = shutil.which("clerk")
    if not clerk_path:
        if (Path.cwd() / ".venv" / "bin" / "clerk").exists():
            clerk_path = str(Path.cwd() / ".venv" / "bin" / "clerk")
        elif (Path.cwd() / "venv" / "bin" / "clerk").exists():
            clerk_path = str(Path.cwd() / "venv" / "bin" / "clerk")

    if clerk_path and Path(clerk_path).exists():
        print_success(f"Clerk found at {clerk_path}")

        # Check execute permissions
        clerk_file = Path(clerk_path)
        is_executable = os.access(clerk_path, os.X_OK)
        perms = oct(clerk_file.stat().st_mode)[-3:]

        if is_executable:
            print_success(f"Clerk is executable (permissions: {perms})")
        else:
            print_error(f"Clerk is NOT executable (permissions: {perms})")
            click.echo(f"   Fix: chmod +x {clerk_path}")

        try:
            result = subprocess.run([clerk_path, "--version"], capture_output=True, text=True)
            click.echo(f"   Version: {result.stdout.strip()}")
        except Exception as e:
            print_error(f"Could not run clerk: {e}")
    else:
        print_error("Clerk executable not found")

    # 3. Check Redis connection
    print_section("3. Checking Redis connection")
    if env_path.exists():
        load_dotenv(find_dotenv())
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        click.echo(f"   Redis URL: {redis_url}")

        try:
            import redis as redis_module

            r = redis_module.from_url(redis_url)
            r.ping()
            print_success("Redis is running and accessible")
        except ImportError:
            print_warning("redis package not installed, cannot test connection")
        except Exception as e:
            print_error(f"Cannot connect to Redis: {e}")
            click.echo("   This is likely why workers are failing!")
            click.echo("   Fix: brew services start redis")
    else:
        print_warning("Skipping (no .env file)")

    # 4. Check log directory
    print_section("4. Checking log directory")
    log_dir = Path.home() / ".clerk" / "logs"
    if log_dir.exists():
        print_success(f"Log directory exists at {log_dir}")

        # Check write permissions
        if os.access(log_dir, os.W_OK):
            print_success("Log directory is writable")
        else:
            print_error("Log directory is NOT writable")
            click.echo(f"   Permissions: {oct(log_dir.stat().st_mode)[-3:]}")
            click.echo(f"   Fix: chmod u+w {log_dir}")

        # Show recent errors
        error_logs = sorted(
            log_dir.glob("clerk-worker-*.error.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if error_logs:
            click.echo("\n   Recent worker error logs:")
            has_errors = False
            for log_file in error_logs[:5]:  # Show first 5
                size = log_file.stat().st_size
                if size > 0:
                    has_errors = True
                    print_warning(f"→ {log_file.name} ({size} bytes)")
                    click.echo("      Last 5 lines:")
                    try:
                        lines = log_file.read_text().strip().split("\n")
                        for line in lines[-5:]:
                            click.echo(f"        {line}")
                    except Exception:
                        pass
                    click.echo("")

            if not has_errors:
                print_success("No errors in recent logs (all 0 bytes)")
        else:
            click.echo("   No error logs found")
    else:
        print_warning(f"Log directory doesn't exist: {log_dir}")

    # 5. Check plist files
    print_section("5. Checking LaunchAgent plists")
    launchagents_dir = Path.home() / "Library" / "LaunchAgents"
    plist_files = list(launchagents_dir.glob("com.civicband.clerk.worker.*.plist"))

    if plist_files:
        print_success(f"Found {len(plist_files)} worker plist files")

        # Validate one plist
        sample_plist = plist_files[0]
        click.echo(f"\n   Sample plist: {sample_plist.name}")

        # Check plist permissions
        plist_perms = oct(sample_plist.stat().st_mode)[-3:]
        if os.access(sample_plist, os.R_OK):
            print_success(f"Plist is readable (permissions: {plist_perms})")
        else:
            print_error(f"Plist is NOT readable (permissions: {plist_perms})")
            click.echo(f"   Fix: chmod 644 {sample_plist}")

        try:
            subprocess.run(
                ["plutil", "-lint", str(sample_plist)],
                capture_output=True,
                check=True,
            )
            print_success("Plist XML is valid")
        except subprocess.CalledProcessError as e:
            print_error("Plist XML is invalid!")
            if e.stderr:
                click.echo(f"   Error: {e.stderr.decode()}")

        # Show plist content (key parts)
        click.echo("\n   Sample plist configuration:")
        try:
            import plistlib

            with open(sample_plist, "rb") as f:
                plist_data = plistlib.load(f)
                prog_args = plist_data.get("ProgramArguments", [])
                click.echo(f"      Program: {' '.join(prog_args)}")

                # Check if the program executable exists and is executable
                if prog_args:
                    plist_clerk_path = Path(prog_args[0])
                    if plist_clerk_path.exists():
                        if os.access(plist_clerk_path, os.X_OK):
                            print_success("      Program executable is valid")
                        else:
                            print_error("      Program exists but is NOT executable")
                            click.echo(
                                f"        Permissions: {oct(plist_clerk_path.stat().st_mode)[-3:]}"
                            )
                            click.echo(f"        Fix: chmod +x {plist_clerk_path}")
                    else:
                        print_error(f"      Program does NOT exist: {plist_clerk_path}")

                working_dir = plist_data.get("WorkingDirectory", "NOT SET")
                click.echo(f"      WorkingDirectory: {working_dir}")

                # Check if working directory exists and is accessible
                if working_dir != "NOT SET":
                    working_path = Path(working_dir)
                    if working_path.exists():
                        if os.access(working_path, os.R_OK | os.X_OK):
                            print_success("      WorkingDirectory is accessible")

                            # Check if .env exists in working directory
                            env_file = working_path / ".env"
                            if env_file.exists():
                                print_success("      .env exists in WorkingDirectory")
                            else:
                                print_error("      .env NOT found in WorkingDirectory")
                        else:
                            print_error("      WorkingDirectory is NOT accessible")
                            click.echo(
                                f"        Permissions: {oct(working_path.stat().st_mode)[-3:]}"
                            )
                    else:
                        print_error("      WorkingDirectory does NOT exist")

                env_vars = plist_data.get("EnvironmentVariables", {})
                if env_vars:
                    click.echo(f"      Environment variables: {len(env_vars)} set")
                    for key in ["REDIS_URL", "DATABASE_URL"]:
                        if key in env_vars:
                            click.echo(f"        {key}: {env_vars[key]}")
        except Exception as e:
            print_warning(f"Could not parse plist: {e}")

        # Check worker status
        click.echo("\n   Worker status:")
        failed_workers = []
        try:
            result = subprocess.run(
                ["launchctl", "list"],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.split("\n"):
                if "com.civicband.clerk.worker" in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        pid, status, label = parts[0], parts[1], parts[2]
                        if pid == "-":
                            print_error(f"{label} (not running, exit code: {status})")
                            failed_workers.append(label)
                        else:
                            print_success(f"{label} (PID: {pid})")

            # If workers failed, try to get error details
            if failed_workers:
                click.echo("\n   Attempting to get error details for failed workers:")
                for label in failed_workers[:3]:  # Show first 3 failures
                    click.echo(f"\n   Checking {label}:")

                    # Try to get print info from launchctl
                    result = subprocess.run(
                        ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0:
                        # Look for error info in output
                        for line in result.stdout.split("\n"):
                            if "last exit code" in line.lower() or "error" in line.lower():
                                click.echo(f"      {line.strip()}")
                    else:
                        # Try to load manually to see error
                        plist_file = launchagents_dir / f"{label}.plist"
                        if plist_file.exists():
                            load_result = subprocess.run(
                                ["launchctl", "load", "-w", str(plist_file)],
                                capture_output=True,
                                text=True,
                            )
                            if load_result.returncode != 0:
                                click.echo(f"      Load error: {load_result.stderr.strip()}")

        except Exception as e:
            print_warning(f"Could not check worker status: {e}")
    else:
        print_error("No worker plist files found")

    # 6. Try manual worker execution
    print_section("6. Testing manual worker execution")
    if clerk_path:
        click.echo(f"   Running: {clerk_path} worker fetch --burst")
        click.echo("   (This will exit immediately if queue is empty)\n")

        result = subprocess.run(
            [clerk_path, "worker", "fetch", "--burst"],
            cwd=Path.cwd(),
        )

        if result.returncode == 0:
            click.echo("")
            print_success("Worker can run manually")
        else:
            click.echo("")
            print_error("Worker failed when run manually")
            click.echo("   This is likely the same error preventing LaunchAgents from loading")
    else:
        print_warning("Cannot test (clerk not found)")

    # 7. Summary
    print_section("Summary and Recommendations")
    click.echo("")

    if not env_path.exists():
        print_error(f"Create a .env file in {Path.cwd()}")

    # Check for Redis errors in logs
    if log_dir.exists():
        for log_file in log_dir.glob("*.error.log"):
            try:
                if "Cannot connect to Redis" in log_file.read_text():
                    print_error("Start Redis server: brew services start redis")
                    break
            except Exception:
                pass

    click.echo(f"\nFor more details, check logs in: {log_dir}")


@cli.command()
@click.option("--json", "output_json", is_flag=True, help="Output as JSON for monitoring systems")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed information")
def health(output_json, verbose):
    """Check system health and queue status.

    Checks:
    - Redis connectivity
    - PostgreSQL connectivity
    - Queue depths and backlogs
    - Worker status
    - Failed job counts
    - Recent completion rates
    - Site progress issues

    Exit codes:
    - 0: System healthy
    - 1: System degraded (warnings present)
    - 2: System unhealthy (critical errors)
    """
    import sys
    from datetime import datetime

    import redis
    from rq import Queue
    from rq.registry import FailedJobRegistry, FinishedJobRegistry, StartedJobRegistry
    from rq.worker import Worker

    from .db import civic_db_connection
    from .queue import get_redis

    health_status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "checks": {},
        "issues": [],
        "warnings": [],
    }

    # Thresholds
    QUEUE_DEPTH_THRESHOLDS = {
        "high": 100,
        "fetch": 50,
        "ocr": 500,
        "extraction": 100,
        "deploy": 50,
    }

    # Check 1: Redis connectivity
    try:
        redis_client = get_redis()
        redis_client.ping()
        health_status["checks"]["redis"] = {
            "status": "ok",
            "message": "Redis is accessible",
        }
        if verbose:
            info = redis_client.info()
            health_status["checks"]["redis"]["version"] = info.get("redis_version")  # type: ignore
            health_status["checks"]["redis"]["uptime_seconds"] = info.get("uptime_in_seconds")  # type: ignore
    except (redis.ConnectionError, redis.TimeoutError) as e:
        health_status["status"] = "unhealthy"
        health_status["checks"]["redis"] = {
            "status": "error",
            "message": f"Cannot connect to Redis: {e}",
        }
        health_status["issues"].append("Redis unreachable - workers cannot process jobs")

    # Check 2: PostgreSQL connectivity
    try:
        from sqlalchemy import text

        with civic_db_connection() as conn:
            # Simple query to verify connection
            result = conn.execute(text("SELECT 1")).fetchone()
            if result:
                health_status["checks"]["database"] = {
                    "status": "ok",
                    "message": "PostgreSQL is accessible",
                }
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["checks"]["database"] = {
            "status": "error",
            "message": f"Cannot connect to PostgreSQL: {e}",
        }
        health_status["issues"].append("Database unreachable - cannot track jobs or sites")

    # Only continue with queue checks if Redis is up
    if health_status["checks"].get("redis", {}).get("status") == "ok":
        # Check 3: Queue depths
        queue_depths = {}
        for queue_name in ["high", "fetch", "ocr", "extraction", "deploy"]:
            try:
                queue = Queue(queue_name, connection=redis_client)
                depth = len(queue)
                queue_depths[queue_name] = depth

                threshold = QUEUE_DEPTH_THRESHOLDS.get(queue_name, 100)
                if depth > threshold:
                    health_status["status"] = (
                        "degraded"
                        if health_status["status"] == "healthy"
                        else health_status["status"]
                    )
                    health_status["warnings"].append(
                        f"{queue_name} queue backed up: {depth} jobs (threshold: {threshold})"
                    )
            except Exception as e:
                health_status["warnings"].append(f"Cannot check {queue_name} queue: {e}")

        health_status["checks"]["queues"] = {
            "status": "ok"
            if not any(d > QUEUE_DEPTH_THRESHOLDS.get(q, 100) for q, d in queue_depths.items())
            else "warning",
            "depths": queue_depths,
            "total_queued": sum(queue_depths.values()),
        }

        # Check 4: Worker status
        try:
            workers = Worker.all(connection=redis_client)
            active_workers = [w for w in workers if w.state in ("busy", "idle")]
            busy_workers = [w for w in workers if w.state == "busy"]

            health_status["checks"]["workers"] = {
                "status": "ok" if len(active_workers) > 0 else "error",
                "total": len(workers),
                "active": len(active_workers),
                "busy": len(busy_workers),
                "idle": len(active_workers) - len(busy_workers),
            }

            if len(active_workers) == 0:
                health_status["status"] = "unhealthy"
                health_status["issues"].append("No workers running - jobs will not be processed")

            if verbose and active_workers:
                health_status["checks"]["workers"]["details"] = [
                    {
                        "name": w.name,
                        "state": w.state,
                        "queues": [q.name for q in w.queues],
                        "current_job": w.get_current_job_id(),
                    }
                    for w in active_workers[:5]  # Limit to first 5
                ]
        except Exception as e:
            health_status["warnings"].append(f"Cannot check worker status: {e}")

        # Check 5: Failed jobs
        try:
            failed_registry = FailedJobRegistry(connection=redis_client)
            failed_count = len(failed_registry)

            health_status["checks"]["failed_jobs"] = {
                "status": "ok" if failed_count < 10 else "warning",
                "count": failed_count,
            }

            if failed_count > 10:
                health_status["status"] = (
                    "degraded" if health_status["status"] == "healthy" else health_status["status"]
                )
                health_status["warnings"].append(f"{failed_count} failed jobs in queue")

            if verbose and failed_count > 0:
                # Get most recent failures
                recent_failed = list(failed_registry.get_job_ids(0, 5))
                health_status["checks"]["failed_jobs"]["recent"] = recent_failed[:5]
        except Exception as e:
            health_status["warnings"].append(f"Cannot check failed jobs: {e}")

        # Check 6: Job completion rate (last hour)
        try:
            finished_registry = FinishedJobRegistry(connection=redis_client)
            finished_count = len(finished_registry)

            health_status["checks"]["completion"] = {
                "status": "ok",
                "finished_last_hour": finished_count,
            }

            if verbose:
                started_registry = StartedJobRegistry(connection=redis_client)
                started_count = len(started_registry)
                health_status["checks"]["completion"]["currently_running"] = started_count
        except Exception as e:
            health_status["warnings"].append(f"Cannot check job completion: {e}")

    # Check 7: Site progress issues (database check)
    if health_status["checks"].get("database", {}).get("status") == "ok":
        try:
            with civic_db_connection() as conn:
                # Find sites stuck in progress for too long
                from sqlalchemy import text

                query = text("""
                    SELECT sp.subdomain, sp.current_stage, sp.stage_completed, sp.stage_total, sp.updated_at, s.status
                    FROM site_progress sp
                    LEFT JOIN sites s ON sp.subdomain = s.subdomain
                    WHERE sp.current_stage != 'completed'
                      AND sp.updated_at < NOW() - INTERVAL '2 hours'
                      AND NOT (
                        -- Exclude sites that are deployed and just waiting on optional extraction
                        s.status = 'deployed' AND sp.current_stage = 'extraction'
                      )
                    ORDER BY sp.updated_at ASC
                    LIMIT 10
                """)

                stuck_sites = []
                for row in conn.execute(query):
                    stuck_sites.append(
                        {
                            "subdomain": row[0],
                            "stage": row[1],
                            "progress": f"{row[2]}/{row[3]}" if row[3] else "unknown",
                            "stalled_for": str(datetime.now(UTC) - row[4]) if row[4] else "unknown",
                            "status": row[5] if row[5] else "unknown",
                        }
                    )

                health_status["checks"]["site_progress"] = {
                    "status": "ok" if len(stuck_sites) == 0 else "warning",
                    "stuck_sites": len(stuck_sites),
                }

                if stuck_sites:
                    health_status["status"] = (
                        "degraded"
                        if health_status["status"] == "healthy"
                        else health_status["status"]
                    )
                    health_status["warnings"].append(
                        f"{len(stuck_sites)} sites stuck in critical pipeline stages for >2 hours"
                    )

                    if verbose:
                        health_status["checks"]["site_progress"]["details"] = stuck_sites

        except Exception as e:
            health_status["warnings"].append(f"Cannot check site progress: {e}")

    # Output results
    if output_json:
        click.echo(json.dumps(health_status, indent=2))
    else:
        # Human-readable output
        status_colors = {
            "healthy": "green",
            "degraded": "yellow",
            "unhealthy": "red",
        }
        status_emoji = {
            "healthy": "✅",
            "degraded": "⚠️",
            "unhealthy": "❌",
        }

        click.echo(f"\n{status_emoji[health_status['status']]} System Status: ", nl=False)
        click.secho(
            health_status["status"].upper(), fg=status_colors[health_status["status"]], bold=True
        )
        click.echo(f"Checked at: {health_status['timestamp']}\n")

        # Show check results
        for check_name, check_data in health_status["checks"].items():
            status_icon = (
                "✓"
                if check_data["status"] == "ok"
                else ("!" if check_data["status"] == "warning" else "✗")
            )
            click.echo(
                f"{status_icon} {check_name.replace('_', ' ').title()}: {check_data.get('message', check_data['status'])}"
            )

            # Show key metrics
            if check_name == "queues" and "depths" in check_data:
                for queue, depth in check_data["depths"].items():
                    color = "red" if depth > QUEUE_DEPTH_THRESHOLDS.get(queue, 100) else None
                    click.echo(f"    {queue}: ", nl=False)
                    click.secho(f"{depth} jobs", fg=color)

            elif check_name == "workers":
                click.echo(
                    f"    Active: {check_data.get('active', 0)}/{check_data.get('total', 0)} ({check_data.get('busy', 0)} busy)"
                )

            elif check_name == "failed_jobs":
                color = "red" if check_data.get("count", 0) > 10 else None
                click.echo("    Failed: ", nl=False)
                click.secho(f"{check_data.get('count', 0)}", fg=color)

            elif check_name == "site_progress" and check_data.get("stuck_sites", 0) > 0:
                click.echo(f"    Stuck sites: {check_data['stuck_sites']}")
                if verbose and "details" in check_data:
                    for site in check_data["details"]:
                        click.echo(
                            f"      • {site['subdomain']}: {site['stage']} ({site['progress']}) "
                            f"- stalled {site['stalled_for']} [status: {site['status']}]"
                        )

        # Show issues
        if health_status["issues"]:
            click.echo("\n❌ CRITICAL ISSUES:")
            for issue in health_status["issues"]:
                click.secho(f"  • {issue}", fg="red")

        # Show warnings
        if health_status["warnings"]:
            click.echo("\n⚠️  WARNINGS:")
            for warning in health_status["warnings"]:
                click.secho(f"  • {warning}", fg="yellow")

        if not health_status["issues"] and not health_status["warnings"]:
            click.echo("\n✅ All systems operational\n")

    # Exit with appropriate code
    exit_code = 0
    if health_status["status"] == "degraded":
        exit_code = 1
    elif health_status["status"] == "unhealthy":
        exit_code = 2

    sys.exit(exit_code)


@cli.command()
@click.option("--reset", is_flag=True, help="Reset orphaned sites to initial state")
@click.option("--reenqueue", is_flag=True, help="Re-enqueue orphaned sites for processing")
@click.option("--max-age", default=2, help="Consider sites orphaned after N hours (default: 2)")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def cleanup_orphaned(reset, reenqueue, max_age, output_json):
    """Find and clean up orphaned jobs.

    Orphaned jobs are sites where the status indicates work in progress
    (fetching, needs_ocr, etc.) but no job is actually running in the queue.

    This can happen when:
    - Workers crash mid-job
    - Jobs fail silently without updating status
    - Redis is cleared but database isn't

    Examples:
        # List orphaned sites
        clerk cleanup-orphaned

        # Reset orphaned sites to initial state
        clerk cleanup-orphaned --reset

        # Reset and re-enqueue for processing
        clerk cleanup-orphaned --reset --reenqueue

        # Only consider sites orphaned after 4 hours
        clerk cleanup-orphaned --max-age 4
    """
    from datetime import datetime, timedelta

    import redis
    from sqlalchemy import text

    from .db import civic_db_connection, update_site
    from .queue import get_redis
    from .queue_db import get_jobs_for_site

    try:
        redis_client = get_redis()
        redis_client.ping()
    except (redis.ConnectionError, redis.TimeoutError) as e:
        click.secho(f"✗ Cannot connect to Redis: {e}", fg="red")
        return

    orphaned_sites = []

    with civic_db_connection() as conn:
        # Find sites with in-progress status that are old enough
        cutoff_time = datetime.now(UTC) - timedelta(hours=max_age)
        query = text("""
            SELECT subdomain, status, last_updated
            FROM sites
            WHERE status IN ('fetching', 'needs_ocr', 'needs_compilation', 'needs_deploy', 'extracting')
              AND last_updated::timestamp < :cutoff_time
            ORDER BY last_updated ASC
        """)

        for row in conn.execute(query, {"cutoff_time": cutoff_time}):
            subdomain = row[0]
            status = row[1]
            last_updated_str = row[2]

            # Parse last_updated string to datetime for stale calculation
            last_updated = None
            if last_updated_str:
                try:
                    last_updated = datetime.fromisoformat(last_updated_str).replace(tzinfo=UTC)
                except Exception:
                    pass

            # Check if there are any jobs for this site in any queue
            jobs = get_jobs_for_site(conn, subdomain)

            # Check if any job is actually running
            has_active_job = False
            for job_data in jobs:
                job_id = job_data.get("job_id")
                if job_id:
                    # Check if job exists in Redis
                    try:
                        from rq.job import Job

                        job = Job.fetch(job_id, connection=redis_client)
                        if job.get_status() in ["queued", "started"]:
                            has_active_job = True
                            break
                    except Exception:
                        # Job doesn't exist in Redis
                        pass

            if not has_active_job:
                orphaned_sites.append(
                    {
                        "subdomain": subdomain,
                        "status": status,
                        "last_updated": last_updated_str if last_updated_str else "unknown",
                        "stale_for": str(datetime.now(UTC) - last_updated)
                        if last_updated
                        else "unknown",
                    }
                )

    if output_json:
        import json

        result = {
            "orphaned_count": len(orphaned_sites),
            "sites": orphaned_sites,
            "actions": {
                "reset": reset,
                "reenqueue": reenqueue,
            },
        }
        click.echo(json.dumps(result, indent=2))
    else:
        if not orphaned_sites:
            click.secho("✓ No orphaned sites found", fg="green")
            return

        click.secho(f"\n⚠️  Found {len(orphaned_sites)} orphaned sites:\n", fg="yellow", bold=True)

        for site in orphaned_sites:
            click.echo(f"  • {site['subdomain']}: {site['status']} - stale for {site['stale_for']}")

    if orphaned_sites and (reset or reenqueue):
        click.echo()

        if reset:
            click.secho(f"🔄 Resetting {len(orphaned_sites)} orphaned sites...", fg="cyan")
            with civic_db_connection() as conn:
                for site in orphaned_sites:
                    update_site(
                        conn,
                        site["subdomain"],
                        {
                            "status": None,
                            "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                        },
                    )
                    click.echo(f"  ✓ Reset {site['subdomain']}")

        if reenqueue:
            from .queue import get_high_queue

            click.secho(f"📥 Re-enqueueing {len(orphaned_sites)} sites...", fg="cyan")
            high_queue = get_high_queue()

            for site in orphaned_sites:
                from .workers import fetch_site_job

                job = high_queue.enqueue(
                    fetch_site_job,
                    subdomain=site["subdomain"],
                    run_id=f"retry_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    job_timeout="30m",
                    description=f"Retry orphaned: {site['subdomain']}",
                )
                click.echo(f"  ✓ Enqueued {site['subdomain']} (job: {job.id})")

        click.echo()
        click.secho("✅ Cleanup complete", fg="green", bold=True)


@cli.command()
@click.option("--queue", default="ocr", help="Queue to check (default: ocr)")
@click.option("--limit", default=5, help="Number of failed jobs to show (default: 5)")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def check_failed(queue, limit, output_json):
    """Check failed jobs in a queue and show error details.

    Examples:
        # Check OCR failures
        clerk check-failed

        # Check first 10 fetch failures
        clerk check-failed --queue fetch --limit 10

        # Get JSON output
        clerk check-failed --json
    """
    import redis
    from rq.job import Job
    from rq.registry import FailedJobRegistry

    from .queue import get_redis

    try:
        redis_client = get_redis()
        redis_client.ping()
    except (redis.ConnectionError, redis.TimeoutError) as e:
        click.secho(f"✗ Cannot connect to Redis: {e}", fg="red")
        return

    failed_reg = FailedJobRegistry(queue, connection=redis_client)
    total_failures = len(failed_reg)

    failed_jobs = []
    for job_id in list(failed_reg.get_job_ids())[:limit]:
        try:
            job = Job.fetch(job_id, connection=redis_client)
            exc_info = None
            if job.exc_info:
                # Get full traceback for debugging
                exc_info = job.exc_info.strip()

            failed_jobs.append(
                {
                    "job_id": job_id,
                    "description": job.description,
                    "exc_info": exc_info,
                    "status": job.get_status(),
                    "created_at": str(job.created_at) if job.created_at else None,
                    "ended_at": str(job.ended_at) if job.ended_at else None,
                    "args": job.args,
                    "kwargs": job.kwargs,
                    "meta": job.meta,
                }
            )
        except Exception as e:
            failed_jobs.append(
                {
                    "job_id": job_id,
                    "description": "Could not fetch job details",
                    "exc_info": str(e),
                    "status": "unknown",
                    "created_at": None,
                    "ended_at": None,
                    "meta": {},
                }
            )

    if output_json:
        result = {
            "queue": queue,
            "total_failures": total_failures,
            "showing": len(failed_jobs),
            "failed_jobs": failed_jobs,
        }
        click.echo(json.dumps(result, indent=2))
    else:
        click.secho(f"\n{'=' * 60}", fg="cyan")
        click.secho(f"Failed Jobs in '{queue}' Queue", fg="cyan", bold=True)
        click.secho(f"{'=' * 60}\n", fg="cyan")

        click.echo(f"Total failures: {total_failures}")
        click.echo(f"Showing first {len(failed_jobs)} jobs:\n")

        for i, job_info in enumerate(failed_jobs, 1):
            click.secho(f"{i}. {job_info['description']}", fg="yellow", bold=True)
            click.echo(f"   Job ID: {job_info['job_id']}")
            click.echo(f"   Status: {job_info.get('status', 'unknown')}")

            # Show job arguments (subdomain, pdf_path, etc.)
            if job_info.get("kwargs"):
                kwargs = job_info["kwargs"]
                if "subdomain" in kwargs:
                    click.echo(f"   Subdomain: {kwargs['subdomain']}")
                if "pdf_path" in kwargs:
                    click.echo(f"   PDF Path: {kwargs['pdf_path']}")

            if job_info.get("created_at"):
                click.echo(f"   Created: {job_info['created_at']}")
            if job_info.get("ended_at"):
                click.echo(f"   Ended: {job_info['ended_at']}")
            if job_info["exc_info"]:
                click.secho("   Error:", fg="red")
                for line in job_info["exc_info"].split("\n"):
                    click.echo(f"     {line}")
            else:
                click.secho("   (No exception info available)", dim=True)
            click.echo()


@cli.command()
@click.option("--threshold-hours", default=2, help="Hours since update to consider stuck")
@click.option(
    "--dry-run", is_flag=True, default=False, help="Show what would be done without making changes"
)
def reconcile_pipeline(threshold_hours, dry_run):
    """Detect and recover stuck sites in pipeline.

    This command:
    1. Finds sites with stale updated_at timestamps
    2. Infers actual state from filesystem
    3. Enqueues missing coordinators
    4. Re-enqueues lost jobs

    Run this periodically (every 15 minutes) via cron.

    Examples:
        # Check for sites stuck >2 hours
        clerk reconcile-pipeline

        # Check for sites stuck >6 hours (dry run)
        clerk reconcile-pipeline --threshold-hours 6 --dry-run

        # Preview what would be recovered
        clerk reconcile-pipeline --dry-run
    """
    from datetime import UTC, datetime

    from . import migrations

    click.echo("=" * 80)
    click.echo(f"RECONCILIATION: {datetime.now(UTC).isoformat()}")
    click.echo("=" * 80)
    click.echo()

    if dry_run:
        click.secho("DRY RUN MODE - no changes will be made", fg="yellow")
        click.echo()

    # Find stuck sites
    stuck = migrations.find_stuck_sites(threshold_hours)

    if not stuck:
        click.echo("No stuck sites found")
        return

    click.echo(f"Found {len(stuck)} stuck sites:")
    click.echo()

    # Recover each stuck site
    recovered = 0
    for site in stuck:
        if not dry_run:
            if migrations.recover_stuck_site(site.subdomain):
                recovered += 1
        else:
            click.echo(f"  {site.subdomain}: Would recover (dry run)")

    click.echo()
    if dry_run:
        click.secho(f"Would recover {len(stuck)} sites", fg="yellow")
    else:
        click.secho(f"Recovered {recovered} sites", fg="green")


@cli.command()
def pipeline_status():
    """Show comprehensive pipeline health and status.

    Shows:
    - Pipeline stage distribution
    - Sites marked as no_documents
    - Stuck sites (not updated in 2+ hours)
    - Success metrics and completion rates

    Examples:
        # Show current pipeline status
        clerk pipeline-status
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from .models import sites_table

    click.echo("=" * 80)
    click.echo("PIPELINE STATUS")
    click.echo("=" * 80)
    click.echo()

    with civic_db_connection() as conn:
        # 1. Stage distribution
        click.echo("Pipeline Stage Distribution:")
        click.echo("-" * 40)

        stage_counts = conn.execute(
            select(sites_table.c.current_stage, func.count().label("count"))
            .where(sites_table.c.current_stage.isnot(None))
            .group_by(sites_table.c.current_stage)
        ).fetchall()

        total_in_pipeline = sum(row.count for row in stage_counts)  # type: ignore

        for row in sorted(stage_counts, key=lambda x: x.count, reverse=True):  # type: ignore
            stage = row.current_stage or "none"
            count = row.count
            pct = (count / total_in_pipeline * 100) if total_in_pipeline > 0 else 0
            click.echo(f"  {stage:20s}: {count:4d} ({pct:5.1f}%)")

        click.echo()

        # 2. No documents sites
        no_docs_count = conn.execute(
            select(func.count())
            .select_from(sites_table)
            .where(sites_table.c.status == "no_documents")
        ).scalar()

        if no_docs_count and no_docs_count > 0:
            click.secho(f"Sites with No Documents: {no_docs_count}", fg="yellow")
            click.echo()

        # 3. Stuck sites (not updated in 2+ hours, not completed)
        cutoff = datetime.now(UTC) - timedelta(hours=2)
        stuck = conn.execute(
            select(func.count())
            .select_from(sites_table)
            .where(
                sites_table.c.current_stage != "completed",
                sites_table.c.current_stage.isnot(None),
                sites_table.c.updated_at < cutoff,
            )
        ).scalar()

        if stuck and stuck > 0:
            click.secho(f"⚠️  Stuck Sites (>2h no update): {stuck}", fg="yellow")
            click.echo("  Run: clerk reconcile-pipeline")
            click.echo()
        else:
            click.secho("✓ No stuck sites found", fg="green")
            click.echo()

        # 4. Success metrics
        click.echo("OCR Success Metrics:")
        click.echo("-" * 40)

        ocr_stats = conn.execute(
            select(
                func.sum(sites_table.c.ocr_total).label("total_jobs"),
                func.sum(sites_table.c.ocr_completed).label("completed"),
                func.sum(sites_table.c.ocr_failed).label("failed"),
            ).where(sites_table.c.ocr_total > 0)
        ).fetchone()

        if ocr_stats and ocr_stats.total_jobs:
            total = ocr_stats.total_jobs or 0
            completed = ocr_stats.completed or 0
            failed = ocr_stats.failed or 0

            success_rate = (completed / total * 100) if total > 0 else 0
            failure_rate = (failed / total * 100) if total > 0 else 0

            click.echo(f"  Total OCR jobs:    {total:6d}")
            click.echo(f"  Completed:         {completed:6d} ({success_rate:5.1f}%)")
            click.echo(f"  Failed:            {failed:6d} ({failure_rate:5.1f}%)")
        else:
            click.echo("  No OCR jobs found")

        click.echo()

        # 5. Recent completions
        click.echo("Recent Activity (last 24h):")
        click.echo("-" * 40)

        day_ago = datetime.now(UTC) - timedelta(hours=24)
        recently_completed = conn.execute(
            select(func.count())
            .select_from(sites_table)
            .where(sites_table.c.current_stage == "completed", sites_table.c.updated_at >= day_ago)
        ).scalar()

        click.echo(f"  Sites completed: {recently_completed or 0}")
        click.echo()

        # 6. Sites in active stages
        click.echo("Active Processing:")
        click.echo("-" * 40)

        active_stages = ["ocr", "compilation", "extraction", "deploy"]
        for stage in active_stages:
            count = conn.execute(
                select(func.count())
                .select_from(sites_table)
                .where(sites_table.c.current_stage == stage)
            ).scalar()

            if count and count > 0:
                click.echo(f"  {stage.capitalize():15s}: {count:4d} sites processing")

    click.echo()
    click.echo("=" * 80)


@cli.command()
@click.option(
    "--dry-run", is_flag=True, default=False, help="Show what would be done without making changes"
)
def fix_extraction_stage(dry_run):
    """Fix sites stuck at 'extraction' stage but already deployed.

    This fixes a bug where ocr_complete_coordinator set stage to 'extraction'
    but deploy_job didn't update sites.current_stage to 'completed'.

    Finds sites with current_stage='extraction' but status='deployed'
    and updates their current_stage to 'completed'.

    Examples:
        # Preview what would be fixed
        clerk fix-extraction-stage --dry-run

        # Apply the fix
        clerk fix-extraction-stage
    """
    from sqlalchemy import select, update

    from .db import civic_db_connection
    from .models import sites_table

    click.echo("=" * 80)
    click.echo("FIX: Sites stuck at 'extraction' stage but deployed")
    click.echo("=" * 80)
    click.echo()

    if dry_run:
        click.secho("DRY RUN MODE - no changes will be made", fg="yellow")
        click.echo()

    with civic_db_connection() as conn:
        # Find sites stuck at extraction but actually deployed
        stuck = conn.execute(
            select(sites_table).where(
                sites_table.c.current_stage == "extraction",
                sites_table.c.status == "deployed",
            )
        ).fetchall()

        click.echo(f"Found {len(stuck)} sites stuck at 'extraction' stage but deployed")
        click.echo()

        fixed = 0
        for site in stuck:
            subdomain = site.subdomain
            status = site.status

            click.echo(f"  {subdomain}: status={status}, current_stage=extraction → completed")

            # Update current_stage to completed (skip in dry-run mode)
            if not dry_run:
                conn.execute(
                    update(sites_table)
                    .where(sites_table.c.subdomain == subdomain)
                    .values(current_stage="completed")
                )

            fixed += 1

        click.echo()
        click.echo(f"{'Would fix' if dry_run else 'Fixed'} {fixed} sites")

    if not dry_run:
        click.echo()
        click.secho("Migration complete!", fg="green")
    else:
        click.echo()
        click.secho("Dry run complete - run without --dry-run to apply changes", fg="yellow")


cli.add_command(new)
cli.add_command(update)
cli.add_command(remove_all_image_dirs)
cli.add_command(extract_entities)
cli.add_command(db)
cli.add_command(debug)
