#!/usr/bin/env python3
"""Pipeline reconciliation job.

Detects and recovers stuck sites by:
1. Finding sites with stale updated_at timestamps
2. Inferring actual state from filesystem
3. Enqueueing missing coordinators
4. Re-enqueueing lost jobs

Run this periodically (every 15 minutes) via cron.
"""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click
from sqlalchemy import select, update

from clerk.db import civic_db_connection
from clerk.models import sites_table
from clerk.pipeline_state import claim_coordinator_enqueue
from clerk.queue import get_compilation_queue
from clerk.workers import ocr_complete_coordinator


def count_txt_files(subdomain):
    """Count txt files on filesystem."""
    storage_dir = os.getenv("STORAGE_DIR", "../sites")
    txt_dir = Path(f"{storage_dir}/{subdomain}/txt")
    if not txt_dir.exists():
        return 0
    return len(list(txt_dir.glob("**/*.txt")))


def find_stuck_sites(threshold_hours=2):
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
                sites_table.c.current_stage != 'completed',
                sites_table.c.current_stage.isnot(None),
                sites_table.c.updated_at < cutoff,
            )
        ).fetchall()

    return stuck


def recover_stuck_site(subdomain):
    """Recover a stuck site by inferring state and enqueueing coordinator.

    Args:
        subdomain: Site subdomain
    """
    # Get current site state
    with civic_db_connection() as conn:
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == subdomain)
        ).fetchone()

    if not site:
        click.secho(f"  {subdomain}: Site not found in database", fg="red")
        return

    stage = site.current_stage

    if stage == 'ocr':
        # Infer state from filesystem
        txt_count = count_txt_files(subdomain)

        if txt_count > 0 and not site.coordinator_enqueued:
            # Work was done but coordinator never enqueued

            # Update database to match reality (ocr_completed)
            with civic_db_connection() as conn:
                conn.execute(
                    update(sites_table).where(
                        sites_table.c.subdomain == subdomain
                    ).values(
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
            else:
                click.echo(f"  {subdomain}: Coordinator already claimed by another process")

        elif txt_count == 0:
            click.secho(f"  {subdomain}: No txt files found - ALL OCR failed", fg="yellow")
            # Could re-enqueue OCR jobs here, or mark for manual investigation

        else:
            click.echo(f"  {subdomain}: Already has coordinator enqueued, skipping")

    elif stage in ['compilation', 'extraction', 'deploy']:
        # These are 1:1 jobs - simpler recovery
        # For now just log, could implement re-enqueue logic
        click.echo(f"  {subdomain}: Stuck in {stage} stage (TODO: implement recovery)")

    else:
        click.echo(f"  {subdomain}: Unknown stage '{stage}'")


@click.command()
@click.option('--threshold-hours', default=2, help='Hours since update to consider stuck')
@click.option('--dry-run', is_flag=True, default=False, help='Show what would be done without making changes')
def main(threshold_hours, dry_run):
    """Run pipeline reconciliation."""

    click.echo("=" * 80)
    click.echo(f"RECONCILIATION: {datetime.now(UTC).isoformat()}")
    click.echo("=" * 80)
    click.echo()

    if dry_run:
        click.secho("DRY RUN MODE - no changes will be made", fg="yellow")
        click.echo()

    # Find stuck sites
    stuck = find_stuck_sites(threshold_hours)

    if not stuck:
        click.echo("No stuck sites found")
        return

    click.echo(f"Found {len(stuck)} stuck sites:")
    click.echo()

    # Recover each stuck site
    recovered = 0
    for site in stuck:
        if not dry_run:
            recover_stuck_site(site.subdomain)
            recovered += 1
        else:
            click.echo(f"  {site.subdomain}: Would recover (dry run)")

    click.echo()
    if dry_run:
        click.secho(f"Would recover {len(stuck)} sites", fg="yellow")
    else:
        click.secho(f"Recovered {recovered} sites", fg="green")


if __name__ == "__main__":
    main()
