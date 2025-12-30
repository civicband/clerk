import datetime
import logging
import os
import shutil
import time
from sqlite3 import OperationalError

import click
import sqlite_utils
from dotenv import load_dotenv

from . import output
from .output import log
from .plugin_loader import load_plugins_from_directory
from .utils import assert_db_exists, build_db_from_text_internal, build_table_from_text, pm

# Load .env file early
load_dotenv()

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
def new():
    """Create a new site"""
    db = assert_db_exists()

    subdomain = click.prompt("Subdomain")
    exists = db.execute("select * from sites where subdomain =?", (subdomain,)).fetchone()
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

    db["sites"].insert(  # pyright: ignore[reportAttributeAccessIssue]
        {
            "subdomain": subdomain,
            "name": name,
            "state": state,
            "country": country,
            "kind": kind,
            "scraper": scraper,
            "start_year": start_year,
            "extra": extra,
            "status": "new",
            "lat": lat_lng.split(",")[0].strip(),
            "lng": lat_lng.split(",")[1].strip(),
        }
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
def update(
    subdomain,
    next_site=False,
    all_years=False,
    skip_fetch=False,
    all_agendas=False,
    backfill=False,
):
    """Update a site"""
    update_site_internal(
        subdomain,
        next_site,
        all_years=all_years,
        skip_fetch=skip_fetch,
        all_agendas=all_agendas,
        backfill=backfill,
    )


def update_site_internal(
    subdomain,
    next_site=False,
    all_years=False,
    skip_fetch=False,
    all_agendas=False,
    backfill=False,
):
    db = assert_db_exists()
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
        num_sites_in_ocr = db.execute(
            "select count(*) from sites where status = 'needs_ocr'"
        ).fetchone()[0]
        if num_sites_in_ocr >= 5:
            log("Too many sites in progress. Going to sleep.")
            return
        subdomain_query = db.execute(query).fetchone()
        if not subdomain_query:
            log("No more sites to update today")
            return
        subdomain = subdomain_query[0]
    site = db["sites"].get(subdomain)  # type: ignore
    if not site:
        log("No site found matching criteria", level="warning")
        return

    # Fetch and OCR
    log(f"Updating site {site['subdomain']}")
    fetcher = get_fetcher(site, all_years=all_years, all_agendas=all_agendas)
    if not skip_fetch:
        fetch_internal(subdomain, fetcher)
    fetcher.ocr()  # type: ignore
    fetcher.transform()  # type: ignore

    update_page_count(subdomain)
    db["sites"].update(  # type: ignore
        subdomain,
        {
            "status": "needs_deploy",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    site = db["sites"].get(subdomain)  # type: ignore
    rebuild_site_fts_internal(subdomain)
    pm.hook.deploy_municipality(subdomain=subdomain)
    db["sites"].update(  # type: ignore
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
    db = assert_db_exists()
    logger.info("Starting fetch subdomain=%s", subdomain)
    db["sites"].update(  # pyright: ignore[reportAttributeAccessIssue]
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
    db["sites"].update(  # pyright: ignore[reportAttributeAccessIssue]
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
def build_db_from_text(subdomain):
    """Build database from text files"""
    build_db_from_text_internal(subdomain)
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
    st = time.time()
    sites_db = assert_db_exists()
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
    for site in sites_db.query("select subdomain, name from sites order by subdomain"):
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
    db = assert_db_exists()
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
    db["sites"].update(  # type: ignore
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


cli.add_command(new)
cli.add_command(update)
cli.add_command(build_full_db)
cli.add_command(remove_all_image_dirs)
