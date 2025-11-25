"""Basic Clerk plugin example.

This demonstrates the minimal structure for a Clerk plugin.
"""

from clerk import hookimpl


class BasicPlugin:
    """A minimal Clerk plugin."""

    @hookimpl
    def fetcher_class(self, label: str):
        """Provide a fetcher class for the given scraper type."""
        if label == "basic_scraper":
            from examples.custom_fetcher import BasicFetcher

            return BasicFetcher
        return None

    @hookimpl
    def deploy_municipality(self, subdomain: str):
        """Deploy municipality files.

        This example just prints the subdomain.
        In production, you would deploy to your hosting platform.
        """
        print(f"[BasicPlugin] Deploying {subdomain}")

        # Example: Copy files to web server
        # import shutil
        # from pathlib import Path
        #
        # source = Path(f"../sites/{subdomain}")
        # dest = Path(f"/var/www/{subdomain}")
        # shutil.copytree(source, dest, dirs_exist_ok=True)

    @hookimpl
    def post_deploy(self, site: dict):
        """Actions to run after deployment."""
        print(f"[BasicPlugin] Post-deploy for {site['subdomain']}")

        # Example: Send notification
        # notify_admin(f"Deployed {site['name']}")

        # Example: Update analytics
        # track_deployment(site)

    @hookimpl
    def post_create(self, subdomain: str):
        """Actions to run after site creation."""
        print(f"[BasicPlugin] Created new site: {subdomain}")

        # Example: Initialize infrastructure
        # create_dns_record(subdomain)
        # setup_hosting(subdomain)


# Register the plugin
if __name__ == "__main__":
    from clerk.utils import pm

    plugin = BasicPlugin()
    pm.register(plugin)

    print(f"Registered {plugin.__class__.__name__}")
    print(f"Plugin manager has {len(pm.get_plugins())} plugins")
