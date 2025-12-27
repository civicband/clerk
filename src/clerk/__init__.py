from .cli import cli
from .fetcher import Fetcher
from .hookspecs import hookimpl


def main():
    cli()


__all__ = ["Fetcher", "hookimpl", "cli", "main"]
