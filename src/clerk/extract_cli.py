"""CLI commands for entity and vote extraction.

Provides the `clerk extract` command group with subcommands:
- entities: Extract persons, orgs, locations
- votes: Extract vote records
- all: Run both entity and vote extraction
"""

import click


@click.group()
def extract():
    """Extract entities and votes from site text files."""
    pass


def _validate_site_args(subdomain, next_site):
    """Validate that either --subdomain or --next-site is provided."""
    if not subdomain and not next_site:
        raise click.UsageError("Must specify --subdomain or --next-site")


@extract.command()
@click.option("-s", "--subdomain", help="Site subdomain to extract from")
@click.option("-n", "--next-site", is_flag=True, help="Auto-select next site needing extraction")
@click.option("--rebuild", is_flag=True, help="Ignore cache and re-extract everything")
def entities(subdomain, next_site, rebuild):
    """Extract entities (persons, orgs, locations) from site text files."""
    _validate_site_args(subdomain, next_site)
    click.echo(f"Entity extraction: subdomain={subdomain}, next_site={next_site}, rebuild={rebuild}")


@extract.command()
@click.option("-s", "--subdomain", help="Site subdomain to extract from")
@click.option("-n", "--next-site", is_flag=True, help="Auto-select next site needing extraction")
@click.option("--rebuild", is_flag=True, help="Ignore cache and re-extract everything")
def votes(subdomain, next_site, rebuild):
    """Extract vote records from site text files."""
    _validate_site_args(subdomain, next_site)
    click.echo(f"Vote extraction: subdomain={subdomain}, next_site={next_site}, rebuild={rebuild}")


@extract.command(name="all")
@click.option("-s", "--subdomain", help="Site subdomain to extract from")
@click.option("-n", "--next-site", is_flag=True, help="Auto-select next site needing extraction")
@click.option("--rebuild", is_flag=True, help="Ignore cache and re-extract everything")
def all_(subdomain, next_site, rebuild):
    """Extract both entities and votes from site text files."""
    _validate_site_args(subdomain, next_site)
    click.echo(f"Full extraction: subdomain={subdomain}, next_site={next_site}, rebuild={rebuild}")
