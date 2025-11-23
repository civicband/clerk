import logfire

from .cli import cli
from .hookspecs import ClerkSpec, hookimpl, hookspec
from .utils import pm

# Initialize Logfire
logfire.configure()

# Instrument SQLite
logfire.instrument_sqlite3()


def main() -> None:
    cli()
