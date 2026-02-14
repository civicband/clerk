import click


@click.group()
def debug():
    """Database migration commands"""
    pass


@debug.command()
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


@debug.command()
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


@debug.command()
@click.option("--limit", default=10, help="Number of sites to show")
def debug_ocr_errors(limit):
    """Show error messages from sites with failed OCR.

    This command queries the database for sites with OCR failures and shows
    the error messages that were recorded when OCR jobs failed.

    Examples:
        # Show first 10 sites with OCR errors
        clerk debug-ocr-errors

        # Show first 20 sites with OCR errors
        clerk debug-ocr-errors --limit 20
    """
    from sqlalchemy import select

    from .db import civic_db_connection
    from .models import sites_table

    click.echo("=" * 80)
    click.echo("DEBUG: OCR Error Messages from Database")
    click.echo("=" * 80)
    click.echo()

    with civic_db_connection() as conn:
        # Get sites with OCR failures
        sites = conn.execute(
            select(sites_table)
            .where(
                sites_table.c.current_stage == "ocr",
                sites_table.c.ocr_failed > 0,
            )
            .limit(limit)
        ).fetchall()

    if not sites:
        click.echo("No sites with OCR failures found")
        return

    click.echo(f"Found {len(sites)} sites with OCR failures:")
    click.echo()

    for i, site in enumerate(sites):
        click.echo(f"Site {i + 1}/{len(sites)}: {site.subdomain}")
        click.echo(
            f"  OCR stats: {site.ocr_completed}/{site.ocr_total} completed, {site.ocr_failed} failed"
        )

        if site.last_error_stage:
            click.echo(f"  Last error stage: {site.last_error_stage}")

        if site.last_error_message:
            # Truncate long error messages
            error_msg = site.last_error_message
            if len(error_msg) > 200:
                error_msg = error_msg[:200] + "..."
            click.secho(f"  Error: {error_msg}", fg="red")
        else:
            click.echo("  Error: (no error message recorded)")

        if site.last_error_at:
            click.echo(f"  Error time: {site.last_error_at}")

        click.echo()


@debug.command()
@click.option("--scraper", default=None, help="Filter by scraper type (e.g., agendacenter)")
@click.option("--days", default=7, help="Sites created in last N days")
@click.option("--limit", default=20, help="Number of sites to show")
def debug_recent_sites(scraper, days, limit):
    """Show recently created sites and their pipeline status.

    Useful for debugging issues with new sites, like "why are new agendacenter
    sites fetching nothing?"

    Examples:
        # Show all sites created in last 7 days
        clerk debug-recent-sites

        # Show agendacenter sites created in last 3 days
        clerk debug-recent-sites --scraper agendacenter --days 3

        # Show last 50 sites
        clerk debug-recent-sites --limit 50
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from .db import civic_db_connection
    from .models import sites_table

    click.echo("=" * 80)
    click.echo("DEBUG: Recent Sites")
    click.echo("=" * 80)
    click.echo()

    cutoff = datetime.now(UTC) - timedelta(days=days)

    with civic_db_connection() as conn:
        # Use started_at as proxy for creation time (when pipeline first ran)
        query = select(sites_table).where(
            sites_table.c.started_at >= cutoff, sites_table.c.started_at.isnot(None)
        )

        if scraper:
            query = query.where(sites_table.c.scraper.like(f"%{scraper}%"))

        query = query.order_by(sites_table.c.started_at.desc()).limit(limit)

        sites = conn.execute(query).fetchall()

    if not sites:
        click.echo(f"No sites found started in last {days} days")
        if scraper:
            click.echo(f"(filtered by scraper: {scraper})")
        return

    click.echo(f"Found {len(sites)} sites started in last {days} days:")
    if scraper:
        click.echo(f"(filtered by scraper: {scraper})")
    click.echo()

    for site in sites:
        click.echo(f"Site: {site.subdomain}")
        click.echo(f"  Started: {site.started_at}")
        click.echo(f"  Scraper: {site.scraper}")
        click.echo(f"  Current stage: {site.current_stage or 'none'}")
        click.echo(f"  Status: {site.status}")

        if site.current_stage == "ocr":
            click.echo(
                f"  OCR: {site.ocr_completed}/{site.ocr_total} completed, {site.ocr_failed} failed"
            )

        if site.last_error_message:
            error_preview = site.last_error_message[:100]
            click.secho(f"  Last error: {error_preview}", fg="yellow")

        click.echo()
