"""Plugin discovery from directory and entry points."""

import importlib.util
import inspect
import sys
from importlib.metadata import entry_points
from pathlib import Path

import click

from .utils import pm

# The marker attribute that pluggy adds to hookimpl-decorated methods
HOOKIMPL_MARKER = "civicband.clerk_impl"


def has_hookimpl_methods(cls: type) -> bool:
    """Check if a class has any methods decorated with @hookimpl."""
    for name in dir(cls):
        if name.startswith("_"):
            continue
        method = getattr(cls, name, None)
        if callable(method) and hasattr(method, HOOKIMPL_MARKER):
            return True
    return False


def load_plugins_from_directory(plugins_dir: str) -> None:
    """Load all plugins from a directory.

    Scans the directory for .py files, imports them, finds classes
    with @hookimpl decorated methods, and registers them with the
    plugin manager.

    Args:
        plugins_dir: Path to directory containing plugin files.

    Raises:
        ImportError: If a plugin file cannot be imported.
        Exception: If a plugin class cannot be instantiated.
    """
    plugins_path = Path(plugins_dir)

    if not plugins_path.exists():
        return

    if not plugins_path.is_dir():
        raise click.ClickException(f"Plugins path is not a directory: {plugins_dir}")

    # Add parent directory to sys.path so plugins can import local modules
    parent_dir = str(plugins_path.parent.resolve())
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    for py_file in sorted(plugins_path.glob("*.py")):
        # Skip __init__.py and similar
        if py_file.name.startswith("_"):
            continue

        # Import the module
        module_name = f"clerk_plugins.{py_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            raise click.ClickException(f"Cannot load plugin file: {py_file}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            raise click.ClickException(f"Error loading plugin {py_file}: {e}") from e

        # Find and register plugin classes
        for name, obj in inspect.getmembers(module, inspect.isclass):
            # Skip imported classes (only register classes defined in this module)
            if obj.__module__ != module_name:
                continue

            if has_hookimpl_methods(obj):
                try:
                    instance = obj()
                    pm.register(instance)
                except Exception as e:
                    raise click.ClickException(
                        f"Error instantiating plugin {name} from {py_file}: {e}"
                    ) from e


def load_plugins_from_entry_points() -> None:
    """Load all plugins registered via entry points.

    Discovers plugins that have been installed as packages and registered
    their plugin classes via the 'clerk.plugins' entry point group.

    Raises:
        Exception: If a plugin class cannot be loaded or instantiated.
    """
    discovered = entry_points()

    # Handle both old and new importlib.metadata API
    if hasattr(discovered, "select"):
        # New API (Python 3.10+)
        clerk_plugins = discovered.select(group="clerk.plugins")
    else:
        # Old API (Python 3.9 and below) - returns dict-like object
        clerk_plugins = discovered.get("clerk.plugins", [])  # type: ignore[attr-defined]

    for ep in clerk_plugins:
        try:
            plugin_class = ep.load()
            instance = plugin_class()
            pm.register(instance)
        except Exception as e:
            raise click.ClickException(
                f"Error loading plugin '{ep.name}' from entry point: {e}"
            ) from e
