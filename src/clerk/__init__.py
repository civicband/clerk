import logfire

from .cli import cli
from .fetcher import Fetcher
from .hookspecs import hookimpl

logfire.configure()
logfire.instrument_sqlite3()


def main():
    cli()


__all__ = ["Fetcher", "hookimpl", "cli", "main"]
