import logfire

from .cli import cli as cli
from .hookspecs import ClerkSpec as ClerkSpec
from .hookspecs import hookimpl as hookimpl
from .hookspecs import hookspec as hookspec
from .plugin_loader import load_plugins_from_directory as load_plugins_from_directory
from .utils import pm as pm

# Initialize Logfire
logfire.configure()

# Instrument SQLite
logfire.instrument_sqlite3()


def main() -> None:
    cli()
