from .cli import cli
from hookspecs import hookimpl, hookspec, ClerkSpec

import pluggy

pm = pluggy.PluginManager("civicband.clerk")
pm.add_hookspecs(ClerkSpec)


def main() -> None:
    cli()
