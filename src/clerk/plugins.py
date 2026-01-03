import click

from .hookspecs import hookimpl


class DummyPlugins:
    @hookimpl
    def deploy_municipality(self, subdomain):
        click.echo(
            click.style(subdomain, "cyan") + ": " + f"Dummy deploy_municipality for {subdomain}"
        )

    @hookimpl
    def upload_static_file(self, file_path, storage_path):
        click.echo(f"Dummy upload_static_file for {file_path}, {storage_path}")

    @hookimpl
    def post_deploy(self, site):
        click.echo(
            click.style(site["subdomain"], "cyan")
            + ": "
            + f"Dummy post_deploy for {site['subdomain']}"
        )

    @hookimpl
    def post_create(self, subdomain):
        click.echo(click.style(subdomain, "cyan") + ": " + f"Dummy post_create for {subdomain}")


class DefaultDBPlugin:
    """Default plugin that handles actual database writes."""

    @hookimpl
    def update_site(self, subdomain, updates):
        """Default implementation: write to database (SQLite or PostgreSQL)."""
        from .utils import assert_db_exists
        from .db import civic_db_connection, update_site

        assert_db_exists()  # Ensure schema exists
        with civic_db_connection() as conn:
            update_site(conn, subdomain, updates)

    @hookimpl
    def create_site(self, subdomain, site_data):
        """Default implementation: insert into database (SQLite or PostgreSQL)."""
        from .utils import assert_db_exists
        from .db import civic_db_connection, upsert_site

        assert_db_exists()  # Ensure schema exists
        with civic_db_connection() as conn:
            upsert_site(conn, site_data)
