#!/usr/bin/env python3
"""Fix sites stuck at 'extraction' stage but already deployed.

This script:
1. Finds sites with current_stage='extraction' but status='deployed'
2. Updates their current_stage to 'completed'
3. This fixes a bug where ocr_complete_coordinator set stage to 'extraction'
   but deploy_job didn't update sites.current_stage to 'completed'
"""

import click
from sqlalchemy import select, update

from clerk.db import civic_db_connection
from clerk.models import sites_table


def fix_extraction_stage(dry_run=False):
    """Fix sites stuck at extraction stage."""

    with civic_db_connection() as conn:
        # Find sites stuck at extraction but actually deployed
        stuck = conn.execute(
            select(sites_table).where(
                sites_table.c.current_stage == "extraction",
                sites_table.c.status == "deployed",
            )
        ).fetchall()

        click.echo(f"Found {len(stuck)} sites stuck at 'extraction' stage but deployed")
        click.echo()

        fixed = 0
        for site in stuck:
            subdomain = site.subdomain
            status = site.status

            click.echo(f"  {subdomain}: status={status}, current_stage=extraction → completed")

            # Update current_stage to completed (skip in dry-run mode)
            if not dry_run:
                conn.execute(
                    update(sites_table)
                    .where(sites_table.c.subdomain == subdomain)
                    .values(current_stage="completed")
                )

            fixed += 1

        click.echo()
        click.echo(f"Fixed {fixed} sites")


@click.command()
@click.option(
    "--dry-run", is_flag=True, default=False, help="Show what would be done without making changes"
)
def main(dry_run):
    """Fix sites stuck at extraction stage but already deployed."""

    click.echo("=" * 80)
    click.echo("FIX: Sites stuck at 'extraction' stage but deployed")
    click.echo("=" * 80)
    click.echo()

    if dry_run:
        click.secho("DRY RUN MODE - no changes will be made", fg="yellow")
        click.echo()

    fix_extraction_stage(dry_run=dry_run)

    if not dry_run:
        click.echo()
        click.secho("Migration complete!", fg="green")
    else:
        click.echo()
        click.secho("Dry run complete - run without --dry-run to apply changes", fg="yellow")


if __name__ == "__main__":
    main()
