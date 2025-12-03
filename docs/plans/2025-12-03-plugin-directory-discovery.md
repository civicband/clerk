# Plugin Directory Discovery Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable clerk to automatically discover and load plugins from a `./plugins/` directory.

**Architecture:** Add a `load_plugins_from_directory()` function in `utils.py` that scans a directory for Python files, imports them, detects classes with `@hookimpl` methods by checking for the `civicband.clerk_impl` attribute, and registers them with the plugin manager. The CLI group gains a `--plugins-dir` option that defaults to `./plugins/`.

**Tech Stack:** Python `importlib`, `inspect`, `pathlib`, Click, pluggy

---

### Task 1: Add `load_plugins_from_directory` function with tests

**Files:**
- Create: `src/clerk/plugin_loader.py`
- Create: `tests/test_plugin_loader.py`

**Step 1: Write the failing test for plugin detection**

Create `tests/test_plugin_loader.py`:

```python
"""Tests for plugin directory discovery."""

import pytest
from pathlib import Path

from clerk.plugin_loader import load_plugins_from_directory
from clerk.utils import pm


@pytest.fixture
def plugins_dir(tmp_path):
    """Create a temporary plugins directory with test plugins."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    return plugins


@pytest.fixture
def sample_plugin_file(plugins_dir):
    """Create a sample plugin file."""
    plugin_code = '''
from clerk import hookimpl

class SamplePlugin:
    @hookimpl
    def fetcher_class(self, label):
        if label == "sample":
            return "SampleFetcher"
        return None
'''
    plugin_file = plugins_dir / "sample_plugin.py"
    plugin_file.write_text(plugin_code)
    return plugin_file


class TestLoadPluginsFromDirectory:
    """Tests for load_plugins_from_directory function."""

    def test_loads_plugin_from_directory(self, plugins_dir, sample_plugin_file, cli_module):
        """Test that plugins are loaded from directory."""
        # Get initial plugin count
        initial_count = len(pm.get_plugins())

        # Load plugins
        load_plugins_from_directory(str(plugins_dir))

        # Should have one more plugin registered
        assert len(pm.get_plugins()) == initial_count + 1

    def test_skips_nonexistent_directory(self):
        """Test that missing directory is handled gracefully."""
        # Should not raise
        load_plugins_from_directory("/nonexistent/path")

    def test_skips_non_plugin_files(self, plugins_dir):
        """Test that files without hookimpl methods are skipped."""
        # Create a file without any plugins
        non_plugin = plugins_dir / "not_a_plugin.py"
        non_plugin.write_text("x = 1\n")

        initial_count = len(pm.get_plugins())
        load_plugins_from_directory(str(plugins_dir))

        # No new plugins should be registered
        assert len(pm.get_plugins()) == initial_count

    def test_skips_dunder_files(self, plugins_dir):
        """Test that __init__.py and similar are skipped."""
        init_file = plugins_dir / "__init__.py"
        init_file.write_text("# init file\n")

        initial_count = len(pm.get_plugins())
        load_plugins_from_directory(str(plugins_dir))

        assert len(pm.get_plugins()) == initial_count
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plugin_loader.py -v`

Expected: FAIL with "ModuleNotFoundError: No module named 'clerk.plugin_loader'"

**Step 3: Write minimal implementation**

Create `src/clerk/plugin_loader.py`:

```python
"""Plugin discovery from directory."""

import importlib.util
import inspect
import sys
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
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_plugin_loader.py -v`

Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/clerk/plugin_loader.py tests/test_plugin_loader.py
git commit -m "feat: add plugin directory discovery

Add load_plugins_from_directory() function that:
- Scans a directory for .py files
- Imports each file and detects classes with @hookimpl methods
- Registers plugin instances with the plugin manager
- Fails fast on any errors"
```

---

### Task 2: Add error handling tests

**Files:**
- Modify: `tests/test_plugin_loader.py`

**Step 1: Write failing tests for error cases**

Add to `tests/test_plugin_loader.py`:

```python
class TestPluginLoaderErrors:
    """Tests for error handling in plugin loader."""

    def test_fails_on_syntax_error(self, plugins_dir):
        """Test that syntax errors in plugins cause failure."""
        bad_plugin = plugins_dir / "bad_syntax.py"
        bad_plugin.write_text("def broken(\n")  # Syntax error

        with pytest.raises(click.ClickException, match="Error loading plugin"):
            load_plugins_from_directory(str(plugins_dir))

    def test_fails_on_import_error(self, plugins_dir):
        """Test that import errors in plugins cause failure."""
        bad_plugin = plugins_dir / "bad_import.py"
        bad_plugin.write_text("import nonexistent_module_12345\n")

        with pytest.raises(click.ClickException, match="Error loading plugin"):
            load_plugins_from_directory(str(plugins_dir))

    def test_fails_on_instantiation_error(self, plugins_dir):
        """Test that plugin instantiation errors cause failure."""
        bad_plugin = plugins_dir / "bad_init.py"
        bad_plugin.write_text('''
from clerk import hookimpl

class BadPlugin:
    def __init__(self):
        raise RuntimeError("Cannot instantiate")

    @hookimpl
    def fetcher_class(self, label):
        return None
''')

        with pytest.raises(click.ClickException, match="Error instantiating plugin"):
            load_plugins_from_directory(str(plugins_dir))

    def test_fails_if_path_is_file(self, tmp_path):
        """Test that passing a file path raises error."""
        file_path = tmp_path / "not_a_dir.py"
        file_path.write_text("x = 1")

        with pytest.raises(click.ClickException, match="not a directory"):
            load_plugins_from_directory(str(file_path))
```

Also add the import at top of file:

```python
import click
```

**Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugin_loader.py::TestPluginLoaderErrors -v`

Expected: All tests PASS (implementation already handles these)

**Step 3: Commit**

```bash
git add tests/test_plugin_loader.py
git commit -m "test: add error handling tests for plugin loader"
```

---

### Task 3: Integrate plugin loading into CLI

**Files:**
- Modify: `src/clerk/cli.py:18-22`
- Create: `tests/test_plugin_loader_cli.py`

**Step 1: Write failing test for CLI integration**

Create `tests/test_plugin_loader_cli.py`:

```python
"""Tests for CLI plugin loading integration."""

import pytest
from click.testing import CliRunner

from clerk.cli import cli


@pytest.fixture
def plugins_dir_with_plugin(tmp_path):
    """Create a plugins directory with a test plugin."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()

    plugin_code = '''
from clerk import hookimpl

class CLITestPlugin:
    @hookimpl
    def fetcher_class(self, label):
        if label == "cli_test":
            return "CLITestFetcher"
        return None
'''
    (plugins / "cli_test_plugin.py").write_text(plugin_code)
    return plugins


class TestCLIPluginLoading:
    """Tests for plugin loading via CLI."""

    def test_plugins_dir_option_exists(self):
        """Test that --plugins-dir option is available."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "--plugins-dir" in result.output

    def test_default_plugins_dir(self, tmp_path, monkeypatch):
        """Test that ./plugins/ is used by default."""
        monkeypatch.chdir(tmp_path)

        # Create default plugins directory
        plugins = tmp_path / "plugins"
        plugins.mkdir()

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        # Should not error even with empty plugins dir
        assert result.exit_code == 0

    def test_custom_plugins_dir(self, tmp_path, plugins_dir_with_plugin, monkeypatch):
        """Test loading plugins from custom directory."""
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--plugins-dir", str(plugins_dir_with_plugin), "--help"]
        )

        assert result.exit_code == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plugin_loader_cli.py::TestCLIPluginLoading::test_plugins_dir_option_exists -v`

Expected: FAIL with assertion error (--plugins-dir not in output)

**Step 3: Modify CLI to add --plugins-dir option**

Modify `src/clerk/cli.py`. Change lines 18-22 from:

```python
@click.group()
@click.version_option()
def cli():
    """Managing civic.band sites"""
```

To:

```python
from .plugin_loader import load_plugins_from_directory


@click.group()
@click.version_option()
@click.option(
    "--plugins-dir",
    default="./plugins",
    type=click.Path(),
    help="Directory to load plugins from",
)
def cli(plugins_dir):
    """Managing civic.band sites"""
    load_plugins_from_directory(plugins_dir)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_plugin_loader_cli.py -v`

Expected: All tests PASS

**Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`

Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/clerk/cli.py tests/test_plugin_loader_cli.py
git commit -m "feat: add --plugins-dir CLI option

Integrate plugin directory loading into CLI:
- Add --plugins-dir option (default: ./plugins/)
- Load plugins on CLI startup before any commands run"
```

---

### Task 4: Export plugin_loader in package

**Files:**
- Modify: `src/clerk/__init__.py`

**Step 1: Add export**

Modify `src/clerk/__init__.py` to add the export:

```python
import logfire

from .cli import cli as cli
from .hookspecs import ClerkSpec as ClerkSpec
from .hookspecs import hookimpl as hookimpl
from .hookspecs import hookspec as hookspec
from .plugin_loader import load_plugins_from_directory as load_plugins_from_directory
from .utils import pm as pm

# Initialize Logfire
logfire.configure()

# Instrument SQLite
logfire.instrument_sqlite3()


def main() -> None:
    cli()
```

**Step 2: Verify tests still pass**

Run: `uv run pytest tests/ -v`

Expected: All tests PASS

**Step 3: Commit**

```bash
git add src/clerk/__init__.py
git commit -m "feat: export load_plugins_from_directory from package"
```

---

### Task 5: Update documentation

**Files:**
- Modify: `docs/plans/2025-12-03-plugin-directory-discovery-design.md`
- Modify: `docs/plugin-development.md`

**Step 1: Update design doc status**

Add to top of `docs/plans/2025-12-03-plugin-directory-discovery-design.md`:

```markdown
**Status:** Implemented
```

**Step 2: Update plugin development guide**

Add new section to `docs/plugin-development.md` after the existing content:

```markdown
## Plugin Discovery

Clerk automatically discovers plugins from a `./plugins/` directory in the current working directory.

### Directory Structure

```
my-project/
├── civic.db
├── plugins/
│   ├── my_fetcher.py
│   └── my_deploy.py
└── sites/
```

### Creating a Plugin

Create a Python file in the `./plugins/` directory with a class that uses the `@hookimpl` decorator:

```python
# plugins/my_fetcher.py
from clerk import hookimpl

class MyFetcherPlugin:
    @hookimpl
    def fetcher_class(self, label):
        if label == "my_fetcher":
            from .my_fetcher_impl import MyFetcher
            return MyFetcher
        return None
```

Clerk will automatically:
1. Scan `./plugins/` for `.py` files
2. Import each file
3. Find classes with `@hookimpl` methods
4. Instantiate and register them

### Custom Plugins Directory

Use `--plugins-dir` to load plugins from a different location:

```bash
clerk --plugins-dir ./my-plugins update -s foo.civic.band
```

### Error Handling

Clerk fails fast on plugin errors. If a plugin file has:
- Syntax errors
- Import errors
- Instantiation errors

Clerk will exit with a clear error message rather than silently skipping the plugin.
```

**Step 3: Commit**

```bash
git add docs/plans/2025-12-03-plugin-directory-discovery-design.md docs/plugin-development.md
git commit -m "docs: update plugin documentation with directory discovery"
```

---

### Task 6: Lint and final verification

**Step 1: Run linter**

Run: `uv run ruff check src/clerk/plugin_loader.py tests/test_plugin_loader.py tests/test_plugin_loader_cli.py`

Fix any issues.

**Step 2: Run formatter**

Run: `uv run ruff format src/ tests/`

**Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`

Expected: All tests PASS

**Step 4: Final commit if needed**

```bash
git add -A
git commit -m "style: format and lint plugin loader code"
```

---

## Summary

After completing all tasks:

1. `clerk` command automatically loads plugins from `./plugins/`
2. `--plugins-dir` option allows custom plugin directory
3. Plugins are any class with `@hookimpl` methods in `.py` files
4. Errors fail fast with clear messages
5. Full test coverage for plugin loading
