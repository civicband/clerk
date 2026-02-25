import datetime
import json
from typing import Any

import click

from clerk.db import civic_db_connection, get_oldest_site, get_site_by_subdomain, upsert_site
from clerk.fetcher import Fetcher, get_fetcher
from clerk.queue import enqueue_job, generate_run_id
from clerk.utils import assert_db_exists, pm
from clerk.workers import ocr_document_job, queue_ocr


@click.group()
@click.option("--subdomain", "-s", help="Subdomain to process")
@click.option(
    "--proceed/--no-proceed",
    default=True,
    help="Whether to move on to the next stage automatically. Defaults to proceed.",
)
@click.option(
    "--ocr-backend",
    type=click.Choice(["tesseract", "vision"], case_sensitive=False),
    default="tesseract",
    help="OCR backend to use (tesseract or vision). Defaults to tesseract.",
)
@click.option(
    "--fetch-local",
    is_flag=True,
    default=False,
    help="Fetch inline instead of sending through worker queues",
)
@click.pass_context
def etl(ctx, subdomain, proceed=True, ocr_backend="tesseract", fetch_local=False):
    """Database migration commands"""
    ctx.ensure_object(dict)
    ctx.obj["SUBDOMAIN"] = subdomain
    ctx.obj["PROCEED"] = proceed
    ctx.obj["OCR_BACKEND"] = ocr_backend
    ctx.obj["FETCH_LOCAL"] = fetch_local


@etl.command()
@click.option("-n", "--next-site", is_flag=True, help="Enqueue oldest site (for auto-scheduler)")
@click.option("-a", "--all-years", is_flag=True)
@click.option("--skip-fetch", is_flag=True)
@click.option("--all-agendas", is_flag=True)
@click.pass_context
def update(ctx, next_site, all_years, skip_fetch, all_agendas):
    """Update a site."""

    fetch_local = ctx.obj.get("FETCH_LOCAL")
    subdomain = ctx.obj.get("SUBDOMAIN")
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
        job_kwargs: dict[str, Any] = {}
        job_kwargs["ocr_backend"] = ctx.obj.get("OCR_BACKEND")
        job_kwargs["proceed"] = ctx.obj.get("PROCEED")
        if all_years:
            job_kwargs["all_years"] = True
        if all_agendas:
            job_kwargs["all_agendas"] = True
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


@etl.command()
@click.pass_context
def new(ctx):
    assert_db_exists()

    subdomain = ctx.obj.get("SUBDOMAIN")
    if not subdomain:
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
    if ctx.obj["FETCH_LOCAL"]:
        from .queue import generate_run_id
        from .workers import fetch_site_job

        fetch_site_job(
            subdomain=subdomain,
            run_id=generate_run_id(subdomain),
            all_years=True,
            all_agendas=all_agendas,
            ocr_backend=ctx.obj.get("OCR_BACKEND"),
            proceed=ctx.obj.get("PROCEED"),
        )
    else:
        enqueue_job(
            "fetch-site",
            subdomain,
            priority="high",
            all_years=True,
            all_agendas=all_agendas,
            ocr_backend=ctx.obj.get("OCR_BACKEND"),
            proceed=ctx.obj.get("PROCEED"),
        )
    pm.hook.post_create(subdomain=subdomain)


@etl.command()
@click.option(
    "--pdf-path",
    default="",
    type=click.Path(exists=True),
    help="Single PDF path to pass to test OCR",
)
@click.pass_context
def ocr(ctx, pdf_path):
    subdomain: str = ctx.obj.get("SUBDOMAIN")
    proceed = ctx.obj.get("PROCEED")
    if not pdf_path:
        from .queue import generate_run_id

        with civic_db_connection() as conn:
            site = get_site_by_subdomain(conn, subdomain)
        fetcher: Fetcher = get_fetcher(site)
        queue_ocr(fetcher, generate_run_id(subdomain), "fetch", ctx.obj.get("OCR_BACKEND"), proceed)
    else:
        ocr_document_job(subdomain, pdf_path, ctx.obj.get("OCR_BACKEND"), proceed)
