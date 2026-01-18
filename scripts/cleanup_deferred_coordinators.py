#!/usr/bin/env python3
"""Clean up deferred OCR coordinator jobs and reset site progress.

This script handles sites that got stuck in OCR state due to failed OCR jobs.
When individual OCR jobs fail with exceptions, the ocr_complete_coordinator
job that depends on them stays in "deferred" state forever, and the site never
progresses to compilation/deployment.

Usage:
    # Dry run (see what would be done)
    uv run python scripts/cleanup_deferred_coordinators.py

    # Actually clean up
    uv run python scripts/cleanup_deferred_coordinators.py --no-dry-run

    # Clean up and re-enqueue sites
    uv run python scripts/cleanup_deferred_coordinators.py --no-dry-run --re-enqueue

This script:
1. Finds all deferred jobs in the compilation queue
2. Identifies which ones are ocr_complete_coordinator jobs
3. Cancels and deletes those deferred jobs
4. Resets site_progress for affected sites
5. Optionally re-enqueues the sites for fresh processing
"""

import click

from clerk.db import civic_db_connection
from clerk.queue import get_compilation_queue
from clerk.queue_db import delete_site_progress


def cleanup_deferred_coordinators(dry_run=True, re_enqueue=False):
    """Clean up deferred coordinator jobs and reset affected sites."""
    queue = get_compilation_queue()
    deferred_registry = queue.deferred_job_registry

    job_ids = deferred_registry.get_job_ids()
    total_deferred = len(job_ids)

    click.echo(f"Found {total_deferred} deferred jobs in compilation queue")

    if total_deferred == 0:
        click.echo("Nothing to clean up!")
        return

    # Find coordinator jobs and extract subdomains
    coordinator_jobs = []
    affected_sites = set()

    for job_id in job_ids:
        job = queue.fetch_job(job_id)
        if not job:
            continue

        # Check if it's an ocr_complete_coordinator job
        if job.func_name and "ocr_complete_coordinator" in job.func_name:
            # Extract subdomain from args (first argument)
            if job.args and len(job.args) > 0:
                subdomain = job.args[0]
                coordinator_jobs.append((job_id, subdomain, job))
                affected_sites.add(subdomain)

    click.echo(f"Found {len(coordinator_jobs)} ocr_complete_coordinator jobs")
    click.echo(f"Affecting {len(affected_sites)} sites:")
    for site in sorted(affected_sites):
        click.echo(f"  - {site}")

    if dry_run:
        click.echo()
        click.secho("DRY RUN - no changes made", fg="yellow")
        click.echo("Run with --no-dry-run to actually clean up")
        return

    # Cancel and delete the deferred coordinator jobs
    click.echo()
    click.echo("Cancelling deferred coordinator jobs...")
    cancelled_count = 0
    for job_id, subdomain, job in coordinator_jobs:
        try:
            job.cancel()
            job.delete()
            cancelled_count += 1
        except Exception as e:
            click.secho(f"  Error cancelling job {job_id} for {subdomain}: {e}", fg="red")

    click.echo(f"Cancelled {cancelled_count} deferred jobs")

    # Reset site progress for affected sites
    click.echo()
    click.echo("Resetting site progress...")
    reset_count = 0
    with civic_db_connection() as conn:
        for subdomain in affected_sites:
            try:
                delete_site_progress(conn, subdomain)
                reset_count += 1
            except Exception as e:
                click.secho(f"  Error resetting {subdomain}: {e}", fg="red")

    click.echo(f"Reset progress for {reset_count} sites")

    # Optionally re-enqueue sites
    if re_enqueue:
        click.echo()
        click.echo("Re-enqueuing sites for processing...")
        import time

        from clerk.queue import get_fetch_queue
        from clerk.workers import fetch_site_job

        fetch_queue = get_fetch_queue()
        enqueued_count = 0

        for subdomain in sorted(affected_sites):
            try:
                # Generate a new run_id
                run_id = f"cleanup_{int(time.time())}_{subdomain}"

                # Enqueue fetch job
                fetch_queue.enqueue(
                    fetch_site_job,
                    subdomain=subdomain,
                    run_id=run_id,
                    all_years=False,
                    all_agendas=False,
                    job_timeout="30m",
                )
                enqueued_count += 1
                click.echo(f"  Enqueued {subdomain}")
            except Exception as e:
                click.secho(f"  Error enqueuing {subdomain}: {e}", fg="red")

        click.echo(f"Re-enqueued {enqueued_count} sites")

    click.echo()
    click.secho("Cleanup complete!", fg="green")


@click.command()
@click.option(
    "--dry-run/--no-dry-run", default=True, help="Show what would be done without making changes"
)
@click.option("--re-enqueue", is_flag=True, help="Re-enqueue sites for processing after cleanup")
def main(dry_run, re_enqueue):
    """Clean up deferred OCR coordinator jobs."""
    cleanup_deferred_coordinators(dry_run=dry_run, re_enqueue=re_enqueue)


if __name__ == "__main__":
    main()
