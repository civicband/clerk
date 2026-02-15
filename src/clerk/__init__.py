from .fetcher import Fetcher
from .hookspecs import hookimpl


def main():
    # Lazy import to avoid circular dependency with plugins
    from .cli import cli

    cli()


def __getattr__(name):
    """Lazy import cli to avoid circular dependencies."""
    if name == "cli":
        from .cli import cli

        return cli
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["Fetcher", "hookimpl", "cli", "main"]
