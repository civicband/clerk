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

    # ETL Pipeline Hooks

    @hookspec
    def extractor_class(self, label):
        """Returns an extractor class for the given label.

        Extractor interface:
            __init__(self, site: dict, config: dict)
            extract(self) -> None  # writes files to STORAGE_DIR/{subdomain}/extracted/
        """

    @hookspec
    def transformer_class(self, label):
        """Returns a transformer class for the given label.

        Transformer interface:
            __init__(self, site: dict, config: dict)
            transform(self) -> None  # reads extracted files, writes transformed files
        """

    @hookspec
    def loader_class(self, label):
        """Returns a loader class for the given label.

        Loader interface:
            __init__(self, site: dict, config: dict)
            load(self) -> None  # reads transformed files, creates tables, writes to DB
        """
