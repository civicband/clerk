from .cli import cli
from .hookspecs import hookimpl, hookspec, ClerkSpec
from .utils import pm


def main() -> None:
    cli()
