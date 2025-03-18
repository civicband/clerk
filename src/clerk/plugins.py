import click

from .hookspecs import hookimpl


class DummyPlugins:

    @hookimpl
    def deploy_municipality(self, subdomain):
        click.echo(
            click.style(subdomain, "cyan")
            + ": "
            + f"Dummy deploy_municipality for {subdomain}"
        )

    @hookimpl
    def upload_static_file(self, file_path, storage_path):
        click.echo(f"Dummy upload_static_file for {file_path}, {storage_path}")

    @hookimpl
    def post_deploy(self, site):
        click.echo(
            click.style(site["subdomain"], "cyan")
            + ": "
            + f"Dummy post_deploy for {site["subdomain"]}"
        )

    @hookimpl
    def post_create(self, subdomain):
        click.echo(
            click.style(subdomain, "cyan") + ": " + f"Dummy post_create for {subdomain}"
        )
