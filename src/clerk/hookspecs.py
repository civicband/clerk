from pluggy import HookimplMarker, HookspecMarker

hookspec = HookspecMarker("civicband.clerk")
hookimpl = HookimplMarker("civicband.clerk")


class ClerkSpec:
    @hookspec
    def fetcher_extra(self, label):
        """Gets the necessary extra bits for setting up a fetcher"""

    @hookspec
    def fetcher_class(self, label):
        """Gets the fetcher class for label"""

    @hookspec
    def deploy_municipality(self, subdomain):
        """Deploys the necessary files for serving a municipality"""

    @hookspec
    def post_deploy(self, site):
        """Runs actions after the deploy of a municipality"""

    @hookspec
    def upload_static_file(self, file_path, storage_path):
        """Uploads a file to static storage, like S3 or a CDN"""

    @hookspec
    def post_create(self, subdomain):
        """Runs actions actions after the creation of a site"""

    @hookspec
    def update_site(self, subdomain, updates):
        """Update a site record in civic.db

        Args:
            subdomain: The site subdomain (e.g., 'berkeleyca.civic.band')
            updates: Dictionary of fields to update (e.g., {'status': 'deployed'})
        """

    @hookspec
    def create_site(self, subdomain, site_data):
        """Create a new site record in civic.db

        Args:
            subdomain: The site subdomain
            site_data: Dictionary of all site fields
        """
