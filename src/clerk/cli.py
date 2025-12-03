import datetime
import json
import os
import shutil
import time
from hashlib import sha256
from sqlite3 import OperationalError

import click
import logfire
import sqlite_utils

from .plugin_loader import load_plugins_from_directory
from .utils import assert_db_exists, pm

STORAGE_DIR = os.environ.get("STORAGE_DIR", "../sites")


@click.group()
@click.version_option()
@click.option(
    "--plugins-dir",
    default="./plugins",
    type=click.Path(),
    help="Directory to load plugins from",
)
def cli(plugins_dir):
    """Managing civic.band sites"""
    load_plugins_from_directory(plugins_dir)


@cli.command()
@logfire.instrument("create_new_site")
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


@logfire.instrument("update_site", extract_args=True)
def update_site_internal(
    subdomain,
    next_site=False,
    all_years=False,
    skip_fetch=False,
    all_agendas=False,
    backfill=False,
):
    db = assert_db_exists()
    logfire.info(
        "Starting site update", subdomain=subdomain, all_years=all_years, all_agendas=all_agendas
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
            click.echo("Too many sites in progress. Going to sleep.")
            return
        subdomain_query = db.execute(query).fetchone()
        if not subdomain_query:
            click.echo("No more sites to update today")
            return
        subdomain = subdomain_query[0]
    site = db["sites"].get(subdomain)  # type: ignore
    if not site:
        click.echo("No site found matching criteria")
        return

    # Fetch and OCR
    click.echo(f"Updating site {site['subdomain']}")
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


@logfire.instrument("fetch_site_data", extract_args=True)
def fetch_internal(subdomain, fetcher):
    db = assert_db_exists()
    logfire.info("Starting fetch", subdomain=subdomain)
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
    logfire.info("Fetch completed", subdomain=subdomain, elapsed_time=elapsed_time)
    click.echo(click.style(subdomain, fg="cyan") + ": " + f"Fetch time: {elapsed_time} seconds")
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


@logfire.instrument("build_db_from_text", extract_args=True)
def build_db_from_text_internal(subdomain):
    st = time.time()
    logfire.info("Building database from text", subdomain=subdomain)
    minutes_txt_dir = f"{STORAGE_DIR}/{subdomain}/txt"
    agendas_txt_dir = f"{STORAGE_DIR}/{subdomain}/_agendas/txt"
    database = f"{STORAGE_DIR}/{subdomain}/meetings.db"
    db_backup = f"{STORAGE_DIR}/{subdomain}/meetings.db.bk"
    shutil.copy(database, db_backup)
    os.remove(database)
    # TODO: copy and delete old db first
    db = sqlite_utils.Database(database)
    db["minutes"].create(  # pyright: ignore[reportAttributeAccessIssue]
        {
            "id": str,
            "meeting": str,
            "date": str,
            "page": int,
            "text": str,
            "page_image": str,
        },
        pk=("id"),
    )
    db["agendas"].create(  # pyright: ignore[reportAttributeAccessIssue]
        {
            "id": str,
            "meeting": str,
            "date": str,
            "page": int,
            "text": str,
            "page_image": str,
        },
        pk=("id"),
    )
    if os.path.exists(minutes_txt_dir):
        build_table_from_text(subdomain, minutes_txt_dir, db, "minutes")
    if os.path.exists(agendas_txt_dir):
        build_table_from_text(subdomain, agendas_txt_dir, db, "agendas")
    et = time.time()
    elapsed_time = et - st
    logfire.info("Database build completed", subdomain=subdomain, elapsed_time=elapsed_time)
    click.echo(f"Execution time: {elapsed_time} seconds")


@logfire.instrument("build_table_from_text", extract_args=True)
def build_table_from_text(subdomain, txt_dir, db, table_name, municipality=None):
    logfire.info(
        "Building table from text",
        subdomain=subdomain,
        table_name=table_name,
        municipality=municipality,
    )
    directories = [
        directory for directory in sorted(os.listdir(txt_dir)) if directory != ".DS_Store"
    ]
    for meeting in directories:
        click.echo(click.style(subdomain, fg="cyan") + ": " + f"Processing {meeting}")
        meeting_dates = [
            meeting_date
            for meeting_date in sorted(os.listdir(f"{txt_dir}/{meeting}"))
            if meeting_date != ".DS_Store"
        ]
        entries = []
        for meeting_date in meeting_dates:
            for page in os.listdir(f"{txt_dir}/{meeting}/{meeting_date}"):
                if not page.endswith(".txt"):
                    continue
                key_hash = {"kind": "minutes"}
                page_file_path = f"{txt_dir}/{meeting}/{meeting_date}/{page}"
                with open(page_file_path) as page_file:
                    page_image_path = f"/{meeting}/{meeting_date}/{page.split('.')[0]}.png"
                    if table_name == "agendas":
                        key_hash["kind"] = "agenda"
                        page_image_path = (
                            f"/_agendas/{meeting}/{meeting_date}/{page.split('.')[0]}.png"
                        )
                    text = page_file.read()
                    page_number = int(page.split(".")[0])
                    key_hash.update(  # type: ignore
                        {
                            "meeting": meeting,
                            "date": meeting_date,
                            "page": page_number,
                            "text": text,
                        }  # pyright: ignore[reportArgumentType]
                    )
                    if municipality:
                        key_hash.update({"subdomain": subdomain, "municipality": municipality})
                    key = sha256(json.dumps(key_hash, sort_keys=True).encode("utf-8")).hexdigest()
                    key = key[:12]
                    key_hash.update(
                        {
                            "id": key,
                            "text": text,
                            "page_image": page_image_path,
                        }
                    )
                    del key_hash["kind"]
                    entries.append(key_hash)
        db[table_name].insert_all(entries)


@logfire.instrument("rebuild_site_fts", extract_args=True)
def rebuild_site_fts_internal(subdomain):
    logfire.info("Rebuilding FTS indexes", subdomain=subdomain)
    site_db = sqlite_utils.Database(f"{STORAGE_DIR}/{subdomain}/meetings.db")
    for table_name in site_db.table_names():
        if table_name.startswith("pages_"):
            site_db[table_name].drop(ignore=True)
    try:
        site_db["agendas"].enable_fts(["text"])
    except OperationalError as e:
        click.echo(click.style(subdomain, fg="cyan") + ": " + click.style(str(e), fg="red"))
    try:
        site_db["minutes"].enable_fts(["text"])
    except OperationalError as e:
        click.echo(click.style(subdomain, fg="cyan") + ": " + click.style(str(e), fg="red"))


@cli.command()
@logfire.instrument("build_full_db")
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
        click.echo(click.style(subdomain, fg="cyan") + ": " + click.style(str(e), fg="red"))
    try:
        db["minutes"].enable_fts(["text"])
    except OperationalError as e:
        click.echo(click.style(subdomain, fg="cyan") + ": " + click.style(str(e), fg="red"))
    et = time.time()
    elapsed_time = et - st
    logfire.info("Full database build completed", elapsed_time=elapsed_time)
    click.echo(f"Execution time: {elapsed_time} seconds")


@logfire.instrument("update_page_count", extract_args=True)
def update_page_count(subdomain):
    db = assert_db_exists()
    site_db = sqlite_utils.Database(f"{STORAGE_DIR}/{subdomain}/meetings.db")
    agendas_count = site_db["agendas"].count
    minutes_count = site_db["minutes"].count
    page_count = agendas_count + minutes_count
    logfire.info(
        "Page count updated",
        subdomain=subdomain,
        agendas=agendas_count,
        minutes=minutes_count,
        total=page_count,
    )
    db["sites"].update(  # type: ignore
        subdomain,
        {
            "pages": page_count,
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )


cli.add_command(new)
cli.add_command(update)
cli.add_command(build_full_db)
