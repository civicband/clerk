import datetime
import json
import os
import shutil
import time
from hashlib import sha256
from sqlite3 import OperationalError

import click
import sqlite_utils

from .utils import assert_db_exists, pm

STORAGE_DIR = "sites"


@click.group()
@click.version_option()
def cli():
    """Managing civic.band sites"""


@cli.command()
def new():
    """Create a new site"""
    db = assert_db_exists()

    subdomain = click.prompt("Subdomain")
    exists = db.execute(
        "select * from sites where subdomain =?", (subdomain,)
    ).fetchone()
    if exists:
        click.echo(f"Site {subdomain} already exists")
        return

    name = click.prompt("Name")
    state = click.prompt("State")
    country = click.prompt("Country", default="US")
    kind = click.prompt("Kind")
    start_year = click.prompt("Start year")
    all_agendas = click.prompt("Fetch all agendas", type=bool, default=False)
    lat_lng = click.prompt("Lat, Lng")
    scraper = click.prompt("Scraper")

    extra = pm.hook.fetcher_extra(label=scraper)
    extra = list(filter(None, extra))
    if len(extra):
        extra = extra[0]

    db["sites"].insert(
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
            "site_db": "meetings.db",
            "lat": lat_lng.split(",")[0].strip(),
            "lng": lat_lng.split(",")[1].strip(),
        }
    )

    click.echo(f"Site {subdomain} created")
    update_site_internal(subdomain, all_years=True, all_agendas=all_agendas)


@cli.command()
@click.option(
    "-s",
    "--subdomain",
)
@click.option("-n", "--next-site", is_flag=True)
@click.option("-a", "--all-years", is_flag=True)
@click.option("--skip-fetch", is_flag=True)
@click.option("--all-agendas", is_flag=True)
def update_site(
    subdomain, next_site=False, all_years=False, skip_fetch=False, all_agendas=False
):
    update_site_internal(
        subdomain,
        next_site,
        all_years=all_years,
        skip_fetch=skip_fetch,
        all_agendas=all_agendas,
    )


def update_site_internal(
    subdomain, next_site=False, all_years=False, skip_fetch=False, all_agendas=False
):
    db = assert_db_exists()
    yesterday = datetime.datetime.now() - datetime.timedelta(days=1)

    # Get site to operate on
    if next_site:
        subdomain_query = db.execute(
            f"select subdomain from sites where last_updated < '{yesterday}' and status = 'deployed' order by last_updated asc limit 1"
        ).fetchone()
        if not subdomain_query:
            click.echo("No more sites to update today")
            return
        subdomain = subdomain_query[0]
    site = db["sites"].get(subdomain)
    if not site:
        click.echo("No site found matching criteria")
        return

    # Fetch and OCR
    click.echo(f"Updating site {site['subdomain']}")
    fetcher = get_fetcher(site, all_years=all_years, all_agendas=all_agendas)
    if not skip_fetch:
        fetch_internal(subdomain, fetcher)
    fetcher.ocr()

    update_page_count(subdomain)
    remove_image_dir(subdomain)
    db["sites"].update(
        subdomain,
        {
            "status": "needs_deploy",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    site = db["sites"].get(subdomain)
    rebuild_site_fts_internal(subdomain)

    pm.hook.deploy_municipality(subdomain=subdomain)
    db["sites"].update(
        subdomain,
        {
            "status": "deployed",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    pm.hook.post_deploy(subdomain=subdomain)


def get_fetcher(site, all_years=False, all_agendas=False):
    start_year = site["start_year"]
    fetcher_class = None
    try:
        start_year = datetime.datetime.strptime(
            site["last_updated"], "%Y-%m-%dT%H:%M:%S"
        ).year
    except TypeError:
        start_year = site["start_year"]
    if all_years:
        start_year = site["start_year"]
    fetcher_class = pm.hook.fetcher_class(label=site["scraper"])

    fetcher_class = list(filter(None, fetcher_class))
    if len(fetcher_class):
        fetcher_class = fetcher_class[0]

    if fetcher_class:
        return fetcher_class(site, start_year, all_agendas)
    if site["scraper"] == "custom":
        import importlib

        module_path = f"fetchers.custom.{site['subdomain'].replace('.', '_')}"
        fetcher = importlib.import_module(module_path)
        return fetcher.custom_fetcher(site, start_year, all_agendas)


def fetch_internal(subdomain, fetcher):
    db = assert_db_exists()
    db["sites"].update(
        subdomain,
        {
            "status": "fetching",
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )
    fetcher.fetch_events()
    status = "needs_ocr"
    db["sites"].update(
        subdomain,
        {
            "status": status,
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )


def delete_old_triggers(subdomain):
    db = assert_db_exists()
    site = db["sites"].get(subdomain)
    if site["site_db"] == "meetings.db":
        site_db = sqlite_utils.Database(f"{STORAGE_DIR}/{subdomain}/{site['site_db']}")
        site_db.execute("drop trigger if exists pages_ai").fetchall()
        site_db.execute("drop trigger if exists pages_ad").fetchall()
        site_db.execute("drop trigger if exists pages_au").fetchall()


@cli.command()
@click.option(
    "-s",
    "--subdomain",
)
def build_db_from_text(subdomain):
    build_db_from_text_internal(subdomain)


def build_db_from_text_internal(subdomain):
    st = time.time()
    sites_db = assert_db_exists()
    site = sites_db["sites"].get(subdomain)
    minutes_txt_dir = f"{STORAGE_DIR}/{subdomain}/txt"
    agendas_txt_dir = f"{STORAGE_DIR}/{subdomain}/_agendas/txt"
    database = f"{STORAGE_DIR}/{subdomain}/{site['site_db']}"
    db_backup = f"{STORAGE_DIR}/{subdomain}/{site['site_db']}.bk"
    shutil.copy(database, db_backup)
    os.remove(database)
    # TODO: copy and delete old db first
    db = sqlite_utils.Database(database)
    db["minutes"].create(
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
    db["agendas"].create(
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
    print("Execution time:", elapsed_time, "seconds")


def build_table_from_text(subdomain, txt_dir, db, table_name):
    directories = [
        directory
        for directory in sorted(os.listdir(txt_dir))
        if directory != ".DS_Store"
    ]
    sentence_id = 1
    for meeting in directories:
        print(f"Processing {meeting}")
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
                with open(page_file_path, "r") as page_file:
                    page_image_path = (
                        f"/{meeting}/{meeting_date}/{page.split('.')[0]}.png"
                    )
                    if table_name == "agendas":
                        key_hash["kind"] = "agenda"
                        page_image_path = f"/_agendas/{meeting}/{meeting_date}/{page.split('.')[0]}.png"
                    text = page_file.read()
                    key_hash.update(
                        {
                            "meeting": meeting,
                            "date": meeting_date,
                            "page": int(page.split(".")[0]),
                            "text": text,
                        }
                    )
                    key = sha256(
                        json.dumps(key_hash, sort_keys=True).encode("utf-8")
                    ).hexdigest()
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


def remove_image_dir(subdomain):
    image_dir = f"{STORAGE_DIR}/{subdomain}/images"
    if os.path.exists(image_dir):
        shutil.rmtree(image_dir)
    agendas_image_dir = f"{STORAGE_DIR}/{subdomain}/_agendas/images"
    if os.path.exists(agendas_image_dir):
        shutil.rmtree(agendas_image_dir)


def rebuild_site_fts_internal(subdomain):
    site = assert_db_exists()["sites"].get(subdomain)
    site_db = sqlite_utils.Database(f"{STORAGE_DIR}/{subdomain}/{site['site_db']}")
    for table_name in site_db.table_names():
        if table_name.startswith("pages_"):
            site_db[table_name].drop(ignore=True)
    try:
        site_db["agendas"].enable_fts(["text"])
    except OperationalError as e:
        print(e)
    try:
        site_db["minutes"].enable_fts(["text"])
    except OperationalError as e:
        print(e)


def update_page_count(subdomain):
    db = assert_db_exists()
    site = db["sites"].get(subdomain)
    site_db = sqlite_utils.Database(f"{STORAGE_DIR}/{subdomain}/{site['site_db']}")
    agendas_count = site_db["agendas"].count
    minutes_count = site_db["minutes"].count
    page_count = agendas_count + minutes_count
    db["sites"].update(
        subdomain,
        {
            "pages": page_count,
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
    )


cli.add_command(new)
cli.add_command(update_site)
