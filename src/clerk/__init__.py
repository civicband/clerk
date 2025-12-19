import logfire

from .fetcher import Fetcher

logfire.configure()
logfire.instrument_sqlite3()

__all__ = ["Fetcher"]
