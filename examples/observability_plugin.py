"""Example observability plugin for Clerk.

This plugin demonstrates how to use update_site and create_site hooks
to add logging, webhooks, and cache invalidation.
"""

import os

import logfire
import requests

from clerk import hookimpl


class ObservabilityPlugin:
    """Plugin that adds observability to database operations."""

    @hookimpl
    def update_site(self, subdomain: str, updates: dict):
        """Log updates and send webhooks for status changes."""
        # Log all updates
        logfire.info(
            "Site updated",
            subdomain=subdomain,
            fields_changed=list(updates.keys()),
            new_values=updates,
        )

        # Send webhook on status changes
        if "status" in updates:
            webhook_url = os.environ.get("CLERK_WEBHOOK_URL")
            if webhook_url:
                try:
                    requests.post(
                        webhook_url,
                        json={
                            "event": "status_change",
                            "subdomain": subdomain,
                            "new_status": updates["status"],
                            "timestamp": updates.get("last_updated"),
                        },
                        timeout=5,
                    )
                except requests.RequestException as e:
                    logfire.error("Webhook failed", error=str(e), subdomain=subdomain)

    @hookimpl
    def create_site(self, subdomain: str, site_data: dict):
        """Log new site creation and notify admins."""
        # Log creation
        logfire.info(
            "Site created",
            subdomain=subdomain,
            municipality=site_data.get("name"),
            state=site_data.get("state"),
        )

        # Send notification
        webhook_url = os.environ.get("CLERK_WEBHOOK_URL")
        if webhook_url:
            try:
                requests.post(
                    webhook_url,
                    json={
                        "event": "site_created",
                        "subdomain": subdomain,
                        "site_data": site_data,
                    },
                    timeout=5,
                )
            except requests.RequestException as e:
                logfire.error("Webhook failed", error=str(e), subdomain=subdomain)


# Auto-register if used as a standalone plugin
if __name__ != "__main__":
    from clerk.utils import pm

    pm.register(ObservabilityPlugin())
