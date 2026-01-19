"""Migration utilities for pipeline state consolidation.

This module provides reusable migration functions that can be called from both
CLI commands and standalone scripts.
"""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click
from sqlalchemy import select, update

from .db import civic_db_connection
from .models import site_progress_table, sites_table
from .pipeline_state import claim_coordinator_enqueue
from .queue import get_compilation_queue, get_ocr_queue
from .workers import ocr_complete_coordinator


def count_txt_files(subdomain: str) -> int:
    """Count txt files on filesystem.

    Args:
        subdomain: Site subdomain

    Returns:
        Number of txt files found
    """
    storage_dir = os.getenv("STORAGE_DIR", "../sites")
    txt_dir = Path(f"{storage_dir}/{subdomain}/txt")
    if not txt_dir.exists():
        return 0
    return len(list(txt_dir.glob("**/*.txt")))


def count_pdf_files(subdomain: str) -> int:
    """Count PDF files on filesystem.

    Args:
        subdomain: Site subdomain

    Returns:
        Number of PDF files found
    """
    storage_dir = os.getenv("STORAGE_DIR", "../sites")
    pdf_dir = Path(f"{storage_dir}/{subdomain}/pdfs")
    if not pdf_dir.exists():
        return 0
    return len(list(pdf_dir.glob("**/*.pdf")))


def migrate_stuck_sites(dry_run: bool = False) -> int:
    """Migrate stuck sites from site_progress to new atomic counter system.

    Args:
        dry_run: If True, don't make any changes

    Returns:
        Number of sites migrated
    """
    with civic_db_connection() as conn:
        # Get all stuck sites from site_progress
        stuck = conn.execute(
            select(site_progress_table).where(site_progress_table.c.current_stage == "ocr")
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
                    update(sites_table)
                    .where(sites_table.c.subdomain == subdomain)
                    .values(
                        current_stage="ocr",
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

        return migrated


def clear_rq_state() -> tuple[int, int]:
    """Clear deferred coordinators and failed OCR jobs.

    Returns:
        Tuple of (deferred_cancelled, failed_deleted)
    """
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

    return (cancelled, deleted)


def find_stuck_sites(threshold_hours: int = 2) -> list:
    """Find sites stuck in pipeline for >threshold_hours.

    Args:
        threshold_hours: Hours since last update to consider stuck

    Returns:
        List of stuck site records
    """
    cutoff = datetime.now(UTC) - timedelta(hours=threshold_hours)

    with civic_db_connection() as conn:
        stuck = conn.execute(
            select(sites_table).where(
                sites_table.c.current_stage != "completed",
                sites_table.c.current_stage.isnot(None),
                sites_table.c.updated_at < cutoff,
            )
        ).fetchall()

    return stuck


def recover_stuck_site(subdomain: str) -> bool:
    """Recover a stuck site by inferring state and enqueueing coordinator.

    Args:
        subdomain: Site subdomain

    Returns:
        True if recovery was successful, False otherwise
    """
    # Get current site state
    with civic_db_connection() as conn:
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == subdomain)
        ).fetchone()

    if not site:
        click.secho(f"  {subdomain}: Site not found in database", fg="red")
        return False

    stage = site.current_stage

    if stage == "ocr":
        # Infer state from filesystem
        txt_count = count_txt_files(subdomain)

        if txt_count > 0 and not site.coordinator_enqueued:
            # Work was done but coordinator never enqueued

            # Update database to match reality (ocr_completed)
            with civic_db_connection() as conn:
                conn.execute(
                    update(sites_table)
                    .where(sites_table.c.subdomain == subdomain)
                    .values(
                        ocr_completed=txt_count,
                        updated_at=datetime.now(UTC),
                    )
                )

            # Atomic claim to prevent duplicate coordinators
            if claim_coordinator_enqueue(subdomain):
                click.echo(f"  {subdomain}: Found {txt_count} txt files, enqueueing coordinator")

                # Enqueue coordinator
                get_compilation_queue().enqueue(
                    ocr_complete_coordinator,
                    subdomain=subdomain,
                    run_id=f"{subdomain}_recovered",
                    job_timeout="5m",
                    description=f"OCR coordinator (recovered): {subdomain}",
                )
                return True
            else:
                click.echo(f"  {subdomain}: Coordinator already claimed by another process")
                return False

        elif txt_count == 0:
            click.secho(f"  {subdomain}: No txt files found - ALL OCR failed", fg="yellow")
            return False

        else:
            click.echo(f"  {subdomain}: Already has coordinator enqueued, skipping")
            return False

    elif stage in ["compilation", "extraction", "deploy"]:
        # These are 1:1 jobs - simpler recovery
        # For now just log, could implement re-enqueue logic
        click.echo(f"  {subdomain}: Stuck in {stage} stage (TODO: implement recovery)")
        return False

    else:
        click.echo(f"  {subdomain}: Unknown stage '{stage}'")
        return False
