# Plugin Directory Discovery Design

**Status:** Implemented

## Overview

Enable clerk to automatically discover and load plugins from a `./plugins/` directory, eliminating the need for manual plugin registration in a wrapper script.

## Current State

Users must create a wrapper script that manually registers plugins:

```python
from clerk import cli, pm

if __name__ == "__main__":
    pm.register(GranicusPlugin())
    pm.register(LegistarPlugin())
    # ... more manual registration
    cli()
```

## Desired State

Users run `clerk` directly, and plugins are discovered automatically:

```bash
clerk update -s foo.civic.band
```

## Design

### Plugin Discovery Flow

1. CLI starts via `clerk` command
2. Check if plugins directory exists (default: `./plugins/`, overridable via `--plugins-dir`)
3. For each `.py` file in the directory:
   - Import the module dynamically
   - Inspect all classes defined in that module
   - For each class, check if any methods have the `@hookimpl` marker
   - If yes, instantiate the class and register it with `pm`
4. Proceed with normal CLI command execution

### CLI Interface

```bash
# Uses ./plugins/ by default
clerk update -s foo.civic.band

# Override plugins directory
clerk --plugins-dir ./my-plugins update -s foo.civic.band
```

### Project Structure

```
my-civicband-project/
├── civic.db
├── plugins/
│   ├── granicus.py      # Contains GranicusPlugin class
│   ├── legistar.py      # Contains LegistarPlugin class
│   └── civicband.py     # Project-specific plugins
└── sites/
```

### Example Plugin File

```python
# plugins/granicus.py
from clerk import hookimpl

class GranicusPlugin:
    @hookimpl
    def fetcher_class(self, label):
        if label == "granicus":
            return GranicusFetcher
        return None

    @hookimpl
    def fetcher_extra(self, label):
        if label == "granicus":
            return {"api_key": os.environ.get("GRANICUS_API_KEY")}
        return None
```

### Error Handling

- **Fail fast** on all plugin loading errors
- Syntax errors in plugin files: crash with clear error
- Import failures: crash with clear error
- Class instantiation failures: crash with clear error

Rationale: If someone configured a plugin, they need it. Silent skipping leads to confusing debugging.

### Implementation Location

Plugin loading happens in the `cli()` function, after the plugin manager is created but before any commands run:

```python
@click.group()
@click.version_option()
@click.option('--plugins-dir', default='./plugins', type=click.Path(),
              help='Directory to load plugins from')
def cli(plugins_dir):
    """Managing civic.band sites"""
    load_plugins_from_directory(plugins_dir)
```

### Detection Mechanism

A class is considered a plugin if it has any methods decorated with `@hookimpl`. Detection uses `pluggy`'s internal marker:

```python
def has_hookimpl_methods(cls):
    for name in dir(cls):
        method = getattr(cls, name, None)
        if method and hasattr(method, 'hookimpl'):
            return True
    return False
```

## Future Considerations

Not in scope for this implementation, but could be added later:

- Entry points for pip-installed plugins (`pip install clerk-plugin-granicus`)
- `CLERK_PLUGINS_DIR` environment variable
- `clerk plugins list` command to show loaded plugins
- Plugin ordering/priority
