from .hookspecs import hookimpl


class DummyPlugins:

    @hookimpl
    def deploy_municipality(self, subdomain):
        print(f"Dummy deploy_municipality for {subdomain}")

    @hookimpl
    def upload_static_file(self, file_path, storage_path):
        print(f"Dummy upload_static_file for {file_path}, {storage_path}")

    @hookimpl
    def post_deploy(self, subdomain):
        print(f"Dummy post_deploy for {subdomain}")
