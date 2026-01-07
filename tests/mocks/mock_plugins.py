"""Mock plugin implementations for testing."""

from typing import Any, Dict, Optional

from clerk import hookimpl


class TestPlugin:
    """Test plugin that implements all clerk hooks for testing."""

    @hookimpl
    def fetcher_extra(self, label: str) -> Optional[Dict[str, Any]]:
        """Return extra configuration for fetchers."""
        if label == "test_scraper":
            return {"test_key": "test_value"}
        return None

    @hookimpl
    def fetcher_class(self, label: str):
        """Return a fetcher class for the given label."""
        if label == "test_scraper":
            from tests.mocks.mock_fetchers import MockFetcher

            return MockFetcher
        return None

    @hookimpl
    def deploy_municipality(self, subdomain: str):
        """Mock deployment of municipality files."""
        # Just record that deploy was called
        self.deployed_subdomains = getattr(self, "deployed_subdomains", [])
        self.deployed_subdomains.append(subdomain)

    @hookimpl
    def post_deploy(self, site: Dict[str, Any]):
        """Mock post-deployment actions."""
        # Record post_deploy calls
        self.post_deploy_calls = getattr(self, "post_deploy_calls", [])
        self.post_deploy_calls.append(site)

    @hookimpl
    def upload_static_file(self, file_path: str, storage_path: str):
        """Mock upload of static files."""
        # Record uploads
        self.uploaded_files = getattr(self, "uploaded_files", [])
        self.uploaded_files.append((file_path, storage_path))

    @hookimpl
    def post_create(self, subdomain: str):
        """Mock post-creation actions."""
        # Record post_create calls
        self.post_create_calls = getattr(self, "post_create_calls", [])
        self.post_create_calls.append(subdomain)

    @hookimpl
    def create_site(self, subdomain: str, site_data: Dict[str, Any]):
        """Mock site creation in datastore."""
        # Record create_site calls
        self.create_site_calls = getattr(self, "create_site_calls", [])
        self.create_site_calls.append(
            {
                "subdomain": subdomain,
                "site_data": site_data,
            }
        )

        # Actually create the database and site record
        import sqlite_utils

        db = sqlite_utils.Database("civic.db")

        # If the table doesn't exist, create it with all columns
        if not db["sites"].exists():
            db["sites"].insert({"subdomain": subdomain, **site_data}, pk="subdomain")
        else:
            # Table exists - only insert columns that exist
            existing_columns = {col.name for col in db["sites"].columns}
            filtered_data = {
                k: v for k, v in site_data.items() if k in existing_columns or k == "subdomain"
            }
            db["sites"].insert(filtered_data, pk="subdomain", replace=True)

    @hookimpl
    def update_site(self, subdomain: str, updates: Dict[str, Any]):
        """Mock site update in datastore."""
        # Record update_site calls
        self.update_site_calls = getattr(self, "update_site_calls", [])
        self.update_site_calls.append(
            {
                "subdomain": subdomain,
                "updates": updates,
            }
        )

        # Actually update the database
        import sqlite_utils

        db = sqlite_utils.Database("civic.db")
        if db["sites"].exists():
            db["sites"].update(subdomain, updates)


class NoOpPlugin:
    """Plugin that does nothing - useful for testing missing hooks."""

    pass


class FailingPlugin:
    """Plugin that raises errors for testing error handling."""

    @hookimpl
    def fetcher_extra(self, label: str):
        """Raise an error."""
        raise RuntimeError("fetcher_extra failed")

    @hookimpl
    def fetcher_class(self, label: str):
        """Raise an error."""
        raise RuntimeError("fetcher_class failed")

    @hookimpl
    def deploy_municipality(self, subdomain: str):
        """Raise an error."""
        raise RuntimeError("deploy_municipality failed")

    @hookimpl
    def post_deploy(self, site: Dict[str, Any]):
        """Raise an error."""
        raise RuntimeError("post_deploy failed")

    @hookimpl
    def upload_static_file(self, file_path: str, storage_path: str):
        """Raise an error."""
        raise RuntimeError("upload_static_file failed")

    @hookimpl
    def post_create(self, subdomain: str):
        """Raise an error."""
        raise RuntimeError("post_create failed")

    @hookimpl
    def create_site(self, subdomain: str, site_data: Dict[str, Any]):
        """Raise an error."""
        raise RuntimeError("create_site failed")

    @hookimpl
    def update_site(self, subdomain: str, updates: Dict[str, Any]):
        """Raise an error."""
        raise RuntimeError("update_site failed")
