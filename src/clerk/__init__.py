import logfire

from .adapter import FetcherAdapter as FetcherAdapter
from .cli import cli as cli
from .defaults import GenericLoader as GenericLoader
from .defaults import IdentityTransformer as IdentityTransformer
from .hookspecs import ClerkSpec as ClerkSpec
from .hookspecs import hookimpl as hookimpl
from .hookspecs import hookspec as hookspec
from .pipeline import get_pipeline_components as get_pipeline_components
from .pipeline import lookup_extractor as lookup_extractor
from .pipeline import lookup_loader as lookup_loader
from .pipeline import lookup_transformer as lookup_transformer
from .plugin_loader import load_plugins_from_directory as load_plugins_from_directory
from .utils import pm as pm

# Initialize Logfire
logfire.configure()

# Instrument SQLite
logfire.instrument_sqlite3()


def main() -> None:
    cli()
