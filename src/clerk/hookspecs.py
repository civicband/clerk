"""Plugin hook specifications for clerk.

This module defines the ClerkSpec interface that plugins can implement to extend
clerk's functionality using the pluggy framework.
"""

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
    def register_cli_commands(self):
        """Return Click command or group to add to CLI.

        Returns:
            click.Command or click.Group: Commands to register
        """

    @hookspec
    def register_job_types(self):
        """Return dictionary of job type to function mappings.

        Returns:
            dict: Mapping of job_type string to job function
                Example: {"finance-etl": finance_etl_job}
        """

    @hookspec
    def register_worker_functions(self):
        """Return dictionary of worker functions for RQ queue.

        Returns:
            dict: Worker function configurations
        """

    @hookspec
    def get_data_processors(self, data_type):
        """Return data processor class for given type.

        Args:
            data_type: String identifying the data type (e.g., 'finance')

        Returns:
            class: Processor class or None if not handled
        """

    @hookspec
    def pre_compilation(self, subdomain, run_id):
        """Hook called before database compilation starts.

        Args:
            subdomain: Municipality subdomain
            run_id: Current run identifier
        """

    @hookspec
    def post_compilation(self, subdomain, database_path, run_id):
        """Hook called after database compilation completes.

        Args:
            subdomain: Municipality subdomain
            database_path: Path to compiled database
            run_id: Current run identifier
        """
