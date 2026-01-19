#!/usr/bin/env python3
"""Migrate stuck sites from site_progress to new atomic counter system.

This script:
1. Finds sites stuck in OCR stage (from site_progress table)
2. Infers actual state from filesystem (count txt/PDF files)
3. Updates sites table with inferred counters
4. Clears deferred coordinators and failed OCR jobs from RQ
"""

from pathlib import Path

import click
from sqlalchemy import select, update

from clerk.db import civic_db_connection
from clerk.models import site_progress_table, sites_table
from clerk.queue import get_compilation_queue, get_ocr_queue


def count_txt_files(subdomain):
    """Count txt files on filesystem."""
    import os
    storage_dir = os.getenv("STORAGE_DIR", "../sites")
    txt_dir = Path(f"{storage_dir}/{subdomain}/txt")
    if not txt_dir.exists():
        return 0
    return len(list(txt_dir.glob("**/*.txt")))


def count_pdf_files(subdomain):
    """Count PDF files on filesystem."""
    import os
    storage_dir = os.getenv("STORAGE_DIR", "../sites")
    pdf_dir = Path(f"{storage_dir}/{subdomain}/pdfs")
    if not pdf_dir.exists():
        return 0
    return len(list(pdf_dir.glob("**/*.pdf")))


def migrate_stuck_sites(dry_run=False):
    """Migrate stuck sites to new system."""

    with civic_db_connection() as conn:
        # Get all stuck sites from site_progress
        stuck = conn.execute(
            select(site_progress_table).where(
                site_progress_table.c.current_stage == 'ocr'
            )
        ).fetchall()

        click.echo(f"Found {len(stuck)} stuck sites in OCR stage")
        click.echo()

        migrated = 0
        for site_prog in stuck:
            subdomain = site_prog.subdomain

            # Infer actual state from filesystem
            txt_count = count_txt_files(subdomain)
            pdf_count = count_pdf_files(subdomain)

            # Conservative estimate of totals
            ocr_total = pdf_count if pdf_count > 0 else site_prog.stage_total
            if ocr_total == 0:
                ocr_total = 1  # avoid division by zero

            ocr_completed = txt_count
            ocr_failed = max(0, ocr_total - ocr_completed)

            # Update sites table (skip in dry-run mode)
            if not dry_run:
                conn.execute(
                    update(sites_table).where(
                        sites_table.c.subdomain == subdomain
                    ).values(
                        current_stage='ocr',
                        ocr_total=ocr_total,
                        ocr_completed=ocr_completed,
                        ocr_failed=ocr_failed,
                        coordinator_enqueued=False,  # Allows reconciliation to trigger
                        started_at=site_prog.started_at,
                        updated_at=site_prog.updated_at,
                    )
                )

            migrated += 1
            click.echo(f"  {subdomain}: {ocr_completed}/{ocr_total} completed, {ocr_failed} failed")

        click.echo()
        click.echo(f"Migrated {migrated} sites")


def clear_rq_state():
    """Clear deferred coordinators and failed OCR jobs."""

    # Clear deferred coordinators
    comp_queue = get_compilation_queue()
    deferred = comp_queue.deferred_job_registry

    click.echo()
    click.echo(f"Clearing {len(deferred)} deferred coordinators...")
    cancelled = 0
    for job_id in deferred.get_job_ids():
        job = comp_queue.fetch_job(job_id)
        if job:
            job.cancel()
            job.delete()
            cancelled += 1

    click.echo(f"  Cancelled {cancelled} deferred coordinators")

    # Clear failed OCR jobs
    ocr_queue = get_ocr_queue()
    failed = ocr_queue.failed_job_registry

    click.echo()
    click.echo(f"Clearing {len(failed)} failed OCR jobs...")
    deleted = 0
    for job_id in failed.get_job_ids():
        job = ocr_queue.fetch_job(job_id)
        if job:
            job.delete()
            deleted += 1

    click.echo(f"  Deleted {deleted} failed OCR jobs")
    click.echo()
    click.echo("RQ cleanup complete")


@click.command()
@click.option('--dry-run', is_flag=True, default=False, help='Show what would be done without making changes')
def main(dry_run):
    """Migrate stuck sites to new atomic counter system."""

    click.echo("=" * 80)
    click.echo("MIGRATION: Stuck Sites to Atomic Counter System")
    click.echo("=" * 80)
    click.echo()

    if dry_run:
        click.secho("DRY RUN MODE - no changes will be made", fg="yellow")
        click.echo()

    migrate_stuck_sites(dry_run=dry_run)

    if not dry_run:
        clear_rq_state()

        click.echo()
        click.secho("Migration complete!", fg="green")
        click.echo("Next step: Run reconciliation job to unstick sites")
        click.echo("  python scripts/reconcile_pipeline.py")
    else:
        click.echo()
        click.secho("Dry run complete - run without --dry-run to apply changes", fg="yellow")


if __name__ == "__main__":
    main()
