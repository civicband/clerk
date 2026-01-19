"""Command-line interface for clerk.

This module provides the main CLI commands for managing civic data pipelines,
including site creation, data fetching, OCR processing, and database operations.
"""

import datetime
import json
import logging
import os
import shutil
import time
from sqlite3 import OperationalError

import click
import sqlite_utils
from dotenv import load_dotenv

# Load .env file BEFORE local imports so extraction.py can read env vars
load_dotenv()

# ruff: noqa: E402
from datetime import UTC

from . import output
from .output import log
from .plugin_loader import load_plugins_from_directory
from .sentry import init_sentry
from .utils import assert_db_exists, build_db_from_text_internal, build_table_from_text, pm

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
    load_plugins_from_directory(plugins_dir)


@cli.command()
@click.option(
    "--ocr-backend",
    type=click.Choice(["tesseract", "vision"], case_sensitive=False),
    default="tesseract",
    help="OCR backend to use (tesseract or vision). Defaults to tesseract.",
)
def new(ocr_backend="tesseract"):
    """Create a new site"""
    from .db import civic_db_connection, get_site_by_subdomain
    from .queue import enqueue_job

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
    from .db import civic_db_connection, upsert_site

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
    "--ocr-backend",
    type=click.Choice(["tesseract", "vision"], case_sensitive=False),
    default="tesseract",
    help="OCR backend to use (tesseract or vision). Defaults to tesseract.",
)
def update(subdomain, next_site, all_years, skip_fetch, all_agendas, backfill, ocr_backend):
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

        enqueue_job("fetch-site", subdomain, priority="high", **job_kwargs)
        return

    # Error: must specify --subdomain or --next-site
    raise click.UsageError("Must specify --subdomain or --next-site")


def update_site_internal(
    subdomain,
    next_site=False,
    all_years=False,
    skip_fetch=False,
    all_agendas=False,
    backfill=False,
    ocr_backend="tesseract",
):
    from sqlalchemy import text

    from .db import civic_db_connection, get_site_by_subdomain, update_site

    engine = assert_db_exists()
    logger.info(
        "Starting site update subdomain=%s all_years=%s all_agendas=%s",
        subdomain,
        all_years,
        all_agendas,
    )

    query_normal = (
        "select subdomain from sites where status = 'deployed' order by last_updated asc limit 1"
    )
    query_backfill = "select subdomain from sites order by last_updated asc limit 1"

    query = query_normal
    if backfill:
        query = query_backfill

    # Get site to operate on
    if next_site:
        with engine.connect() as conn:
            num_sites_in_ocr = conn.execute(
                text("select count(*) from sites where status = 'needs_ocr'")
            ).fetchone()[0]
            num_sites_in_extraction = conn.execute(
                text("select count(*) from sites where status = 'needs_extraction'")
            ).fetchone()[0]
            total_processing = num_sites_in_ocr + num_sites_in_extraction
            if total_processing >= 5:
                log("Too many sites in progress. Going to sleep.")
                return
            subdomain_query = conn.execute(text(query)).fetchone()
            if not subdomain_query:
                log("No more sites to update today")
                return
            subdomain = subdomain_query[0]

    with civic_db_connection() as conn:
        site = get_site_by_subdomain(conn, subdomain)
    if not site:
        log("No site found matching criteria", level="warning")
        return

    # Fetch and OCR
    log(f"Updating site {site['subdomain']}")
    fetcher = get_fetcher(site, all_years=all_years, all_agendas=all_agendas)
    if not skip_fetch:
        fetch_internal(subdomain, fetcher)
    fetcher.ocr(backend=ocr_backend)  # type: ignore

    # Update status after OCR, before extraction
    with civic_db_connection() as conn:
        update_site(
            conn,
            subdomain,
            {
                "status": "needs_extraction",
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )

    fetcher.transform()  # type: ignore

    update_page_count(subdomain)
    with civic_db_connection() as conn:
        update_site(
            conn,
            subdomain,
            {
                "status": "needs_deploy",
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
    with civic_db_connection() as conn:
        site = get_site_by_subdomain(conn, subdomain)
    rebuild_site_fts_internal(subdomain)
    pm.hook.deploy_municipality(subdomain=subdomain)
    with civic_db_connection() as conn:
        update_site(
            conn,
            subdomain,
            {
                "status": "deployed",
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
    pm.hook.post_deploy(site=site)


def get_fetcher(site, all_years=False, all_agendas=False):
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
        return fetcher_class(site, start_year, all_agendas)  # pyright: ignore[reportCallIssue]
    if site["scraper"] == "custom":
        import importlib

        module_path = f"fetchers.custom.{site['subdomain'].replace('.', '_')}"
        fetcher = importlib.import_module(module_path)
        return fetcher.custom_fetcher(site, start_year, all_agendas)


def fetch_internal(subdomain, fetcher):
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


@cli.command()
def build_full_db():
    from .db import civic_db_connection, get_all_sites

    st = time.time()
    assert_db_exists()
    database = database = f"{STORAGE_DIR}/meetings.db"
    db_backup = f"{STORAGE_DIR}/meetings.db.bk"
    try:
        shutil.copy(database, db_backup)
        os.remove(database)
    except FileNotFoundError:
        pass
    db = sqlite_utils.Database(database)
    db["minutes"].create(  # pyright: ignore[reportAttributeAccessIssue]
        {
            "id": str,
            "subdomain": str,
            "municipality": str,
            "meeting": str,
            "date": str,
            "page": int,
            "text": str,
            "page_image": str,
            "entities_json": str,
            "votes_json": str,
        },
        pk=("id"),
    )
    db["agendas"].create(  # pyright: ignore[reportAttributeAccessIssue]
        {
            "id": str,
            "subdomain": str,
            "municipality": str,
            "meeting": str,
            "date": str,
            "page": int,
            "text": str,
            "page_image": str,
            "entities_json": str,
            "votes_json": str,
        },
        pk=("id"),
    )
    with civic_db_connection() as conn:
        sites = get_all_sites(conn)
    for site in sites:
        subdomain = site["subdomain"]
        municipality = site["name"]
        minutes_txt_dir = f"{STORAGE_DIR}/{subdomain}/txt"
        agendas_txt_dir = f"{STORAGE_DIR}/{subdomain}/_agendas/txt"
        if os.path.exists(minutes_txt_dir):
            build_table_from_text(
                subdomain=subdomain,
                txt_dir=minutes_txt_dir,
                db=db,
                table_name="minutes",
                municipality=municipality,
            )
        if os.path.exists(agendas_txt_dir):
            build_table_from_text(
                subdomain=subdomain,
                txt_dir=agendas_txt_dir,
                db=db,
                table_name="agendas",
                municipality=municipality,
            )
    for table_name in db.table_names():
        if table_name.startswith("pages_"):
            db[table_name].drop(ignore=True)
    try:
        db["agendas"].enable_fts(["text"])
    except OperationalError as e:
        log(str(e), subdomain=subdomain, level="error")
    try:
        db["minutes"].enable_fts(["text"])
    except OperationalError as e:
        log(str(e), subdomain=subdomain, level="error")
    et = time.time()
    elapsed_time = et - st
    log(
        f"Full database build completed in {elapsed_time:.2f} seconds",
        elapsed_time=f"{elapsed_time:.2f}",
    )


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
def migrate_extraction_schema():
    """Add extraction tracking columns to sites table (legacy command, use Alembic for new migrations)"""
    from sqlalchemy import inspect, text

    engine = assert_db_exists()

    with engine.connect() as conn:
        # Check existing columns
        inspector = inspect(engine)
        existing_columns = {col["name"] for col in inspector.get_columns("sites")}

        if "extraction_status" not in existing_columns:
            conn.execute(
                text("ALTER TABLE sites ADD COLUMN extraction_status TEXT DEFAULT 'pending'")
            )
            conn.commit()

        if "last_extracted" not in existing_columns:
            conn.execute(text("ALTER TABLE sites ADD COLUMN last_extracted TEXT"))
            conn.commit()

        # Set pending for all sites that don't have a status
        conn.execute(
            text("UPDATE sites SET extraction_status = 'pending' WHERE extraction_status IS NULL")
        )
        conn.commit()

    click.echo("Migration complete: extraction_status and last_extracted columns added")


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
        ).fetchone()[0]

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
@click.option("--webhook-url", help="Webhook URL for health check alerts")
@click.option("--work-dir", help="Working directory path (defaults to current directory)")
def install_launchd(webhook_url=None, work_dir=None):
    """Install launchd jobs for automated updates (macOS only)"""
    import platform
    import subprocess
    from pathlib import Path

    # Check if macOS
    if platform.system() != "Darwin":
        click.secho("Error: launchd is only available on macOS", fg="red")
        return

    # Get paths
    home = Path.home()
    user = os.environ.get("USER")
    work_dir = Path(work_dir) if work_dir else Path.cwd()
    log_dir = work_dir / "logs"
    lock_file = f"/tmp/civicband-update-{user}.lock"

    # Find required binaries
    gtimeout = shutil.which("gtimeout")
    uv = shutil.which("uv")

    if not gtimeout:
        click.secho("Error: gtimeout not found. Install with: brew install coreutils", fg="red")
        return
    if not uv:
        click.secho("Error: uv not found. Install from: https://docs.astral.sh/uv/", fg="red")
        return

    # Build PATH
    path_parts = [
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        str(Path.home() / ".cargo/bin"),
        "/usr/bin",
        "/bin",
    ]
    env_path = ":".join(path_parts)

    # Template substitutions
    substitutions = {
        "{{LOCK_FILE}}": lock_file,
        "{{LOG_DIR}}": str(log_dir),
        "{{WORK_DIR}}": str(work_dir),
        "{{GTIMEOUT_PATH}}": gtimeout,
        "{{UV_PATH}}": uv,
        "{{WRAPPER_SCRIPT}}": str(work_dir / "update-wrapper.sh"),
        "{{HEALTHCHECK_SCRIPT}}": str(work_dir / "healthcheck.sh"),
        "{{PATH}}": env_path,
        "{{WEBHOOK_URL}}": webhook_url or "",
    }

    # Get template directory - try source location first (development), then installation location
    clerk_src_dir = Path(__file__).parent.parent.parent
    template_dir = clerk_src_dir / "deployment" / "launchd"

    if not template_dir.exists():
        # Try system installation location
        import sys

        install_dir = Path(sys.prefix) / "share" / "clerk" / "deployment" / "launchd"
        if install_dir.exists():
            template_dir = install_dir
        else:
            click.secho(
                f"Error: Template directory not found.\n"
                f"Tried:\n"
                f"  - {clerk_src_dir / 'deployment' / 'launchd'}\n"
                f"  - {install_dir}\n"
                f"Make sure clerk is properly installed with: uv sync",
                fg="red",
            )
            return

    click.echo(f"Installing launchd jobs for user: {user}")
    click.echo(f"Working directory: {work_dir}")
    click.echo(f"Log directory: {log_dir}")

    # Create log directory
    log_dir.mkdir(parents=True, exist_ok=True)

    # Process templates and install files
    files_created = []

    # 1. Create wrapper script
    template_file = template_dir / "update-wrapper.sh.template"
    output_file = work_dir / "update-wrapper.sh"
    content = template_file.read_text()
    for key, value in substitutions.items():
        content = content.replace(key, value)
    output_file.write_text(content)
    output_file.chmod(0o755)
    files_created.append(str(output_file))
    click.echo(f"✓ Created: {output_file}")

    # 2. Create healthcheck script
    template_file = template_dir / "healthcheck.sh.template"
    output_file = work_dir / "healthcheck.sh"
    content = template_file.read_text()
    for key, value in substitutions.items():
        content = content.replace(key, value)
    output_file.write_text(content)
    output_file.chmod(0o755)
    files_created.append(str(output_file))
    click.echo(f"✓ Created: {output_file}")

    # 3. Create and install update plist
    template_file = template_dir / "com.civicband.update.plist.template"
    plist_dir = home / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    output_file = plist_dir / "com.civicband.update.plist"
    content = template_file.read_text()
    for key, value in substitutions.items():
        content = content.replace(key, value)
    output_file.write_text(content)
    files_created.append(str(output_file))
    click.echo(f"✓ Created: {output_file}")

    # 4. Create and install healthcheck plist
    template_file = template_dir / "com.civicband.healthcheck.plist.template"
    output_file = plist_dir / "com.civicband.healthcheck.plist"
    content = template_file.read_text()
    for key, value in substitutions.items():
        content = content.replace(key, value)
    output_file.write_text(content)
    files_created.append(str(output_file))
    click.echo(f"✓ Created: {output_file}")

    # Load launchd jobs
    click.echo("\nLoading launchd jobs...")
    try:
        subprocess.run(
            ["launchctl", "load", str(plist_dir / "com.civicband.update.plist")],
            check=True,
            capture_output=True,
        )
        click.echo("✓ Loaded: com.civicband.update")
    except subprocess.CalledProcessError as e:
        click.secho(f"Warning: Failed to load update job: {e.stderr.decode()}", fg="yellow")

    try:
        subprocess.run(
            ["launchctl", "load", str(plist_dir / "com.civicband.healthcheck.plist")],
            check=True,
            capture_output=True,
        )
        click.echo("✓ Loaded: com.civicband.healthcheck")
    except subprocess.CalledProcessError as e:
        click.secho(f"Warning: Failed to load healthcheck job: {e.stderr.decode()}", fg="yellow")

    # Show status
    click.echo("\n" + "=" * 60)
    click.secho("Installation complete!", fg="green", bold=True)
    click.echo("=" * 60)
    click.echo("\nMonitor logs with:")
    click.echo(f"  tail -f {log_dir}/update.log")
    click.echo(f"  tail -f {log_dir}/healthcheck.log")
    click.echo("\nManage jobs with:")
    click.echo("  launchctl list | grep civicband")
    click.echo("  launchctl unload ~/Library/LaunchAgents/com.civicband.update.plist")
    click.echo("  launchctl load ~/Library/LaunchAgents/com.civicband.update.plist")


@cli.command()
def uninstall_launchd():
    """Uninstall launchd jobs for automated updates (macOS only)"""
    import platform
    import subprocess
    from pathlib import Path

    # Check if macOS
    if platform.system() != "Darwin":
        click.secho("Error: launchd is only available on macOS", fg="red")
        return

    home = Path.home()
    plist_dir = home / "Library" / "LaunchAgents"
    update_plist = plist_dir / "com.civicband.update.plist"
    healthcheck_plist = plist_dir / "com.civicband.healthcheck.plist"

    click.echo("Uninstalling launchd jobs...")

    # Unload and remove update job
    if update_plist.exists():
        try:
            subprocess.run(
                ["launchctl", "unload", str(update_plist)],
                check=True,
                capture_output=True,
            )
            click.echo("✓ Unloaded: com.civicband.update")
        except subprocess.CalledProcessError as e:
            click.secho(f"Warning: Failed to unload update job: {e.stderr.decode()}", fg="yellow")

        update_plist.unlink()
        click.echo(f"✓ Removed: {update_plist}")
    else:
        click.echo("- Update job not found")

    # Unload and remove healthcheck job
    if healthcheck_plist.exists():
        try:
            subprocess.run(
                ["launchctl", "unload", str(healthcheck_plist)],
                check=True,
                capture_output=True,
            )
            click.echo("✓ Unloaded: com.civicband.healthcheck")
        except subprocess.CalledProcessError as e:
            click.secho(
                f"Warning: Failed to unload healthcheck job: {e.stderr.decode()}", fg="yellow"
            )

        healthcheck_plist.unlink()
        click.echo(f"✓ Removed: {healthcheck_plist}")
    else:
        click.echo("- Healthcheck job not found")

    # Optionally clean up scripts and logs
    work_dir = Path.cwd()
    wrapper_script = work_dir / "update-wrapper.sh"
    healthcheck_script = work_dir / "healthcheck.sh"

    if wrapper_script.exists() or healthcheck_script.exists():
        click.echo("\nThe following files remain in the current directory:")
        if wrapper_script.exists():
            click.echo(f"  - {wrapper_script}")
        if healthcheck_script.exists():
            click.echo(f"  - {healthcheck_script}")
        click.echo("  - logs/")
        click.echo("\nRemove these manually if no longer needed.")

    # Check for lock file
    user = os.environ.get("USER")
    lock_file = Path(f"/tmp/civicband-update-{user}.lock")
    if lock_file.exists():
        lock_file.unlink()
        click.echo(f"✓ Removed lock file: {lock_file}")

    click.echo("\n" + "=" * 60)
    click.secho("Uninstall complete!", fg="green", bold=True)
    click.echo("=" * 60)


def _find_alembic_ini():
    """Find alembic.ini file in current directory or package location.

    Returns:
        Path to alembic.ini file

    Raises:
        click.Abort: If alembic.ini is not found
    """
    import sys
    from pathlib import Path

    # Try current directory first
    cwd_ini = Path.cwd() / "alembic.ini"
    if cwd_ini.exists():
        return cwd_ini

    # Try package location (for installed package)
    package_ini = Path(sys.prefix) / "share" / "clerk" / "alembic.ini"
    if package_ini.exists():
        return package_ini

    click.secho(
        "Error: alembic.ini not found. Please run this command from the project root directory.",
        fg="red",
    )
    raise click.Abort()


def _run_alembic_command(*args):
    """Run an alembic command and display output.

    Args:
        *args: Arguments to pass to alembic command

    Raises:
        click.Abort: If alembic command fails
    """
    import subprocess

    alembic_ini = _find_alembic_ini()

    result = subprocess.run(
        ["alembic", "-c", str(alembic_ini), *args],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        click.secho(f"Error running alembic {args[0]}: {result.stderr}", fg="red")
        raise click.Abort()

    click.echo(result.stdout)
    if result.stderr:
        click.echo(result.stderr, err=True)


@cli.group()
def db():
    """Database migration commands"""
    pass


@db.command()
def upgrade():
    """Run database migrations to latest version"""
    _run_alembic_command("upgrade", "head")


@db.command()
def current():
    """Show current database migration version"""
    _run_alembic_command("current")


@db.command()
def history():
    """Show database migration history"""
    _run_alembic_command("history")


@cli.command()
@click.argument("subdomains", nargs=-1, required=True)
@click.option(
    "--priority",
    type=click.Choice(["high", "normal", "low"], case_sensitive=False),
    default="normal",
    help="Job priority (default: normal)",
)
def enqueue(subdomains, priority):
    """Enqueue sites for processing"""
    import redis

    from .db import civic_db_connection
    from .queue import enqueue_job, get_redis
    from .queue_db import create_site_progress, track_job

    # Validate Redis connection
    try:
        get_redis()
    except (redis.ConnectionError, redis.TimeoutError, SystemExit) as e:
        click.secho(f"Error: Cannot connect to Redis: {e}", fg="red")
        raise click.Abort() from e

    # Process each site
    for subdomain in subdomains:
        # Enqueue the job
        try:
            job_id = enqueue_job("fetch-site", subdomain, priority=priority)
        except Exception as e:
            click.secho(f"Error enqueueing {subdomain}: {e}", fg="red")
            continue

        # Track in PostgreSQL
        try:
            with civic_db_connection() as conn:
                track_job(conn, job_id, subdomain, "fetch-site", "fetch")
                create_site_progress(conn, subdomain, "fetch")
        except Exception as e:
            click.secho(f"Warning: Failed to track job in database: {e}", fg="yellow")

        # Display confirmation
        click.echo(f"Enqueued {subdomain} (job: {job_id}, priority: {priority})")


@cli.command()
@click.option("--subdomain", help="Show detailed progress for specific site")
def status(subdomain=None):
    """Show queue status and site progress"""
    import redis
    from sqlalchemy import select
    from sqlalchemy.exc import OperationalError

    from .db import civic_db_connection
    from .models import site_progress_table
    from .queue import (
        get_deploy_queue,
        get_extraction_queue,
        get_fetch_queue,
        get_high_queue,
        get_ocr_queue,
    )

    # Handle Redis connection errors
    try:
        # Show queue status if not querying specific site
        if not subdomain:
            click.echo()
            click.echo("=== Queue Status ===")

            queues = {
                "High priority": get_high_queue(),
                "Fetch": get_fetch_queue(),
                "OCR": get_ocr_queue(),
                "Extraction": get_extraction_queue(),
                "Deploy": get_deploy_queue(),
            }

            for name, queue in queues.items():
                job_count = len(queue)
                click.echo(f"{name:15} {job_count} jobs")
    except (redis.ConnectionError, redis.TimeoutError) as e:
        click.secho(f"Error: Cannot connect to Redis: {e}", fg="red")
        raise click.Abort() from e

    # Handle database connection errors
    try:
        with civic_db_connection() as conn:
            if subdomain:
                # Query for specific site
                stmt = select(site_progress_table).where(
                    site_progress_table.c.subdomain == subdomain
                )
                result = conn.execute(stmt).fetchone()

                if result:
                    # Display detailed site progress
                    percentage = (
                        (result.stage_completed / result.stage_total * 100)
                        if result.stage_total > 0
                        else 0
                    )
                    click.echo(f"Site: {result.subdomain}")
                    click.echo(f"Current stage: {result.current_stage}")
                    click.echo(
                        f"Progress: {result.stage_completed}/{result.stage_total} ({percentage:.1f}%)"
                    )
                    click.echo(f"Started: {result.started_at}")
                    click.echo(f"Updated: {result.updated_at}")
                else:
                    click.echo(f"No progress tracking found for site: {subdomain}")
            else:
                # Query all active sites
                click.echo()
                click.echo("=== Active Sites ===")

                stmt = select(site_progress_table).where(
                    site_progress_table.c.current_stage != "completed"
                )
                results = conn.execute(stmt).fetchall()

                if results:
                    for row in results:
                        if row.stage_total > 0:
                            percentage = row.stage_completed / row.stage_total * 100
                            click.echo(
                                f"  {row.subdomain}: {row.current_stage} ({row.stage_completed}/{row.stage_total}, {percentage:.1f}%)"
                            )
                        else:
                            click.echo(f"  {row.subdomain}: {row.current_stage}")
    except OperationalError as e:
        click.secho(f"Error: Cannot connect to database: {e}", fg="red")
        raise click.Abort() from e


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
        # Single worker
        worker_instance = Worker(queues, connection=get_redis(), default_worker_ttl=default_timeout)
        worker_instance.work(with_scheduler=True, burst=burst)
    else:
        # Worker pool for multiple workers
        # WorkerPool passes **kwargs to Worker constructor, so we can pass default_worker_ttl
        with WorkerPool(
            queues,
            num_workers=num_workers,
            connection=get_redis(),
            default_worker_ttl=default_timeout,
        ) as pool:
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
        load_dotenv()
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
            health_status["checks"]["redis"]["version"] = info.get("redis_version")
            health_status["checks"]["redis"]["uptime_seconds"] = info.get("uptime_in_seconds")
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
            WHERE status IN ('fetching', 'needs_ocr', 'needs_extraction', 'needs_deploy', 'extracting')
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
@click.option(
    "--dry-run", is_flag=True, default=False, help="Show what would be done without making changes"
)
def migrate_stuck_sites(dry_run):
    """Migrate stuck sites to atomic counter system.

    This command:
    1. Finds sites stuck in OCR stage (from site_progress table)
    2. Infers actual state from filesystem (count txt/PDF files)
    3. Updates sites table with inferred counters
    4. Clears deferred coordinators and failed OCR jobs from RQ

    Examples:
        # Preview what would be migrated
        clerk migrate-stuck-sites --dry-run

        # Execute migration
        clerk migrate-stuck-sites
    """
    from . import migrations

    click.echo("=" * 80)
    click.echo("MIGRATION: Stuck Sites to Atomic Counter System")
    click.echo("=" * 80)
    click.echo()

    if dry_run:
        click.secho("DRY RUN MODE - no changes will be made", fg="yellow")
        click.echo()

    migrations.migrate_stuck_sites(dry_run=dry_run)

    if not dry_run:
        migrations.clear_rq_state()

        click.secho("Migration complete!", fg="green")
        click.echo("Next step: Run reconciliation job to unstick sites")
        click.echo("  clerk reconcile-pipeline")
    else:
        click.echo()
        click.secho("Dry run complete - run without --dry-run to apply changes", fg="yellow")


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
@click.option("--limit", default=10, help="Number of sites to investigate in detail")
def investigate_failed_ocr(limit):
    """Investigate sites with no completed OCR documents.

    This command helps diagnose why sites show "No completed OCR documents found".
    It checks filesystem structure, database state, and identifies common failure patterns.

    Examples:
        # Investigate first 10 failed sites
        clerk investigate-failed-ocr

        # Investigate first 20 failed sites
        clerk investigate-failed-ocr --limit 20
    """
    from . import migrations

    click.echo("=" * 80)
    click.echo("INVESTIGATION: Sites with No Completed OCR Documents")
    click.echo("=" * 80)
    click.echo()

    patterns = migrations.investigate_failed_ocr_sites(limit)

    if patterns["total_count"] == 0:
        click.echo("No sites found with ocr_completed = 0")
        return

    click.echo(f"Found {patterns['total_count']} sites with ocr_completed = 0")
    click.echo(f"Investigating first {patterns['investigated_count']} sites in detail...")
    click.echo()

    # Show details for each site
    for i, info in enumerate(patterns["sites"]):
        subdomain = info["subdomain"]
        click.echo(f"Site {i + 1}/{patterns['investigated_count']}: {subdomain}")
        click.echo("-" * 80)

        # Database state
        click.echo("Database:")
        db = info["db_state"]
        click.echo(f"  current_stage: {db.get('current_stage')}")
        click.echo(f"  ocr_total: {db.get('ocr_total')}")
        click.echo(f"  ocr_completed: {db.get('ocr_completed')}")
        click.echo(f"  ocr_failed: {db.get('ocr_failed')}")
        if db.get("last_error_message"):
            error_msg = db.get("last_error_message", "")[:100]
            click.echo(f"  last_error: {error_msg}")

        # Filesystem state
        click.echo("Filesystem:")
        click.echo(f"  site_dir exists: {info['site_dir_exists']}")
        click.echo(f"  minutes_pdf_count: {info.get('minutes_pdf_count', 0)}")
        click.echo(f"  agendas_pdf_count: {info.get('agendas_pdf_count', 0)}")
        click.echo(f"  total_pdf_count: {info['pdf_count']}")
        if info["pdf_files"]:
            click.echo(f"  sample PDFs: {info['pdf_files'][:3]}")
        click.echo(f"  txt_base exists: {info['txt_base_exists']}")
        click.echo(f"  has_any_txt_files: {info['has_any_txt_files']}")

        # Txt structure analysis
        if info["txt_structure"]:
            click.echo("  txt structure:")
            for meeting, docs in info["txt_structure"].items():
                docs_with_files = sum(1 for d in docs if d["has_files"])
                total_docs = len(docs)
                click.echo(f"    {meeting}: {docs_with_files}/{total_docs} docs with txt files")
                if docs_with_files == 0 and total_docs > 0:
                    click.secho(
                        f"      ⚠️ {total_docs} document dirs but no txt files!", fg="yellow"
                    )

        # Diagnosis
        click.echo("Diagnosis:")
        if not info["site_dir_exists"]:
            click.secho("  ❌ Site directory doesn't exist - storage issue", fg="red")
        elif info["pdf_count"] == 0:
            click.secho("  ⚠️ No PDFs found - fetch stage may have failed", fg="yellow")
        elif not info["txt_base_exists"]:
            click.secho("  ⚠️ No txt directory - OCR never ran or output lost", fg="yellow")
        elif info["has_any_txt_files"]:
            click.secho("  ⚠️ Has txt files but wrong structure - investigate above", fg="yellow")
        else:
            click.secho("  ❌ OCR truly failed for all documents", fg="red")

        click.echo()

    # Summary statistics
    click.echo("=" * 80)
    click.echo("SUMMARY")
    click.echo("=" * 80)
    click.echo(f"Patterns found (from {patterns['investigated_count']} sites):")
    click.echo(f"  No site directory: {patterns['no_site_dir']}")
    click.echo(f"  No PDFs found: {patterns['no_pdfs']}")
    click.echo(f"  No txt directory: {patterns['no_txt_base']}")
    click.echo(f"  Has txt files but wrong structure: {patterns['has_txt_wrong_structure']}")
    click.echo(f"  True OCR failure (all docs failed): {patterns['true_ocr_failure']}")
    click.echo()

    if patterns["true_ocr_failure"] > 0:
        click.echo("Recommendations:")
        click.echo("  - Check last_error_message for common error patterns")
        click.echo("  - Investigate sample PDFs to see if they're corrupted")
        click.echo("  - Consider if OCR backend (tesseract/vision) needs tuning")
        click.echo("  - Sites may need manual intervention or different OCR approach")


@cli.command()
@click.option("--limit", default=10, help="Number of failed jobs to show")
def debug_failed_ocr(limit):
    """Show errors from failed OCR jobs in RQ queue.

    This command inspects the RQ failed job registry to show actual error
    messages from OCR jobs that failed. Useful for diagnosing why OCR is
    failing (missing files, permissions, tesseract errors, etc.).

    Examples:
        # Show first 10 failed OCR jobs
        clerk debug-failed-ocr

        # Show first 20 failed OCR jobs
        clerk debug-failed-ocr --limit 20
    """
    from .queue import get_ocr_queue

    click.echo("=" * 80)
    click.echo("DEBUG: Failed OCR Jobs")
    click.echo("=" * 80)
    click.echo()

    ocr_q = get_ocr_queue()
    failed = ocr_q.failed_job_registry

    total_failed = len(failed)
    click.echo(f"Total failed OCR jobs: {total_failed}")
    click.echo()

    if total_failed == 0:
        click.echo("No failed OCR jobs found")
        return

    # Get first N failed jobs
    job_ids = list(failed.get_job_ids())[:limit]

    for i, job_id in enumerate(job_ids):
        job = ocr_q.fetch_job(job_id)
        if job:
            subdomain = job.kwargs.get("subdomain", "unknown")
            pdf_path = job.kwargs.get("pdf_path", "unknown")

            click.echo(f"Failed Job {i + 1}/{len(job_ids)}: {job_id}")
            click.echo(f"  Subdomain: {subdomain}")
            click.echo(f"  PDF path: {pdf_path}")

            if job.exc_info:
                # Extract error type from traceback
                lines = job.exc_info.split("\n")
                error_line = None
                for line in lines:
                    if line.strip().startswith(
                        ("FileNotFoundError:", "PermissionError:", "ValueError:", "Exception:")
                    ):
                        error_line = line.strip()
                        break

                if error_line:
                    click.secho(f"  Error: {error_line[:150]}", fg="red")
                else:
                    # Show last non-empty line
                    for line in reversed(lines):
                        if line.strip():
                            click.secho(f"  Error: {line.strip()[:150]}", fg="red")
                            break
            else:
                click.echo("  Error: (no error info available)")

            click.echo()

    if total_failed > limit:
        click.echo(f"... and {total_failed - limit} more failed jobs")
        click.echo(f"Run with --limit {total_failed} to see all")


cli.add_command(new)
cli.add_command(update)
cli.add_command(build_full_db)
cli.add_command(remove_all_image_dirs)
cli.add_command(migrate_extraction_schema)
cli.add_command(extract_entities)
cli.add_command(install_launchd)
cli.add_command(uninstall_launchd)
cli.add_command(db)
