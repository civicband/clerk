import logfire

from .fetcher import Fetcher
from .hookspecs import hookimpl

logfire.configure()
logfire.instrument_sqlite3()

__all__ = ["Fetcher", "hookimpl"]
