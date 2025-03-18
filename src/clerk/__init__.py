from .cli import cli
from .hookspecs import ClerkSpec, hookimpl, hookspec
from .utils import pm


def main() -> None:
    cli()
