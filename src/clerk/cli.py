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
from . import output
from .output import log
from .plugin_loader import load_plugins_from_directory
from .utils import assert_db_exists, build_db_from_text_internal, build_table_from_text, pm

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
        from queue import Queue

        # Use LokiQueueHandler for async batched sending (much faster than synchronous LokiHandler)
        loki_queue = Queue()
        loki_handler = logging_loki.LokiQueueHandler(
            loki_queue,
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
def new():
    """Create a new site"""
    from .db import civic_db_connection, get_site_by_subdomain

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
    update_site_internal(subdomain, all_years=True, all_agendas=all_agendas)
    pm.hook.post_create(subdomain=subdomain)


@cli.command()
@click.option(
    "-s",
    "--subdomain",
)
@click.option("-n", "--next-site", is_flag=True)
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
def update(
    subdomain,
    next_site=False,
    all_years=False,
    skip_fetch=False,
    all_agendas=False,
    backfill=False,
    ocr_backend="tesseract",
):
    """Update a site"""
    update_site_internal(
        subdomain,
        next_site,
        all_years=all_years,
        skip_fetch=skip_fetch,
        all_agendas=all_agendas,
        backfill=backfill,
        ocr_backend=ocr_backend,
    )


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
    for site in sites_db.query("select subdomain from sites order by subdomain"):
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


cli.add_command(new)
cli.add_command(update)
cli.add_command(build_full_db)
cli.add_command(remove_all_image_dirs)
cli.add_command(migrate_extraction_schema)
cli.add_command(extract_entities)
