"""Mock plugin implementations for testing."""

from typing import Any

from clerk import hookimpl


class TestPlugin:
    """Test plugin that implements all clerk hooks for testing."""

    @hookimpl
    def fetcher_extra(self, label: str) -> dict[str, Any] | None:
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
    def post_deploy(self, site: dict[str, Any]):
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
    def post_deploy(self, site: dict[str, Any]):
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
