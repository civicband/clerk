# Clerk Plugin System Enhancements

## Overview
This document details the enhancements needed in the clerk repository to support the election finance integration via plugins. This is part of the larger integration plan documented in `ELECTION_FINANCE_INTEGRATION.md`.

## Current Plugin System
- Framework: pluggy
- Hookspecs: 6 existing hooks (fetcher_extra, fetcher_class, deploy_municipality, post_deploy, upload_static_file, post_create)
- Plugin discovery: Dynamic loading from plugins directory
- Plugin examples: Legistar fetcher, CivicText fetcher

## Required Enhancements

### 1. New Hook Specifications

#### File: src/clerk/hookspecs.py (UPDATE)
Add the following new hookspecs:

```python
@hookspec
def register_cli_commands(self):
    """Return Click command or group to add to CLI.

    Returns:
        click.Command or click.Group: Commands to register
    """

@hookspec
def register_job_types(self):
    """Return dictionary of job type to function mappings.

    Returns:
        dict: Mapping of job_type string to job function
            Example: {"finance-etl": finance_etl_job}
    """

@hookspec
def register_worker_functions(self):
    """Return dictionary of worker functions for RQ queue.

    Returns:
        dict: Worker function configurations
    """

@hookspec
def get_data_processors(self, data_type):
    """Return data processor class for given type.

    Args:
        data_type: String identifying the data type (e.g., 'finance')

    Returns:
        class: Processor class or None if not handled
    """

@hookspec
def pre_compilation(self, subdomain, run_id):
    """Hook called before database compilation starts.

    Args:
        subdomain: Municipality subdomain
        run_id: Current run identifier
    """

@hookspec
def post_compilation(self, subdomain, database_path, run_id):
    """Hook called after database compilation completes.

    Args:
        subdomain: Municipality subdomain
        database_path: Path to compiled database
        run_id: Current run identifier
    """
```

### 2. CLI Enhancement for Plugin Commands

#### File: src/clerk/cli.py (UPDATE)

```python
@click.group(invoke_without_command=True)
@click.option("--plugins-dir", default="./plugins", help="Directory containing plugins")
@click.option("-q", "--quiet", is_flag=True, help="Suppress output")
@click.pass_context
def cli(ctx, plugins_dir, quiet):
    """Managing civic.band sites"""
    # ... existing setup ...

    # Load plugins
    load_plugins_from_directory(plugins_dir)

    # NEW: Register plugin CLI commands
    pm = get_plugin_manager()
    for plugin_commands in pm.hook.register_cli_commands():
        if plugin_commands:
            if isinstance(plugin_commands, click.Group):
                for name, cmd in plugin_commands.commands.items():
                    cli.add_command(cmd, name=name)
            elif isinstance(plugin_commands, click.Command):
                cli.add_command(plugin_commands)

    # ... rest of existing code ...
```

### 3. Queue System Enhancement for Plugin Jobs

#### File: src/clerk/queue.py (UPDATE)

```python
def get_job_function_map():
    """Get complete job function mapping including plugin jobs.

    Returns:
        dict: Complete job_type to function mapping
    """
    # Base job function map
    job_function_map = {
        "fetch-site": workers.fetch_site_job,
        "ocr-page": workers.ocr_page_job,
        "extract-site": workers.extraction_job,
        "deploy-site": workers.deploy_job,
        "db-compilation": workers.db_compilation_job,
        "coordinator": workers.coordinator_job,
    }

    # Add plugin job types
    pm = get_plugin_manager()
    for plugin_jobs in pm.hook.register_job_types():
        if plugin_jobs:
            job_function_map.update(plugin_jobs)

    return job_function_map


def enqueue_job(job_type, site_id, priority="normal", run_id=None, **kwargs):
    """Enqueue a job to the appropriate queue.

    Enhanced to support plugin-registered job types.
    """
    # ... existing validation ...

    # Get complete job function map
    job_function_map = get_job_function_map()

    job_function = job_function_map.get(job_type)
    if not job_function:
        raise ValueError(f"Unknown job type: {job_type}. Available: {list(job_function_map.keys())}")

    # ... rest of existing enqueue logic ...
```

### 4. Database Schema Changes

#### File: alembic/versions/xxx_add_has_finance_data.py (NEW)
```python
"""Add has_finance_data column to sites table

Revision ID: xxx
Revises: 9daf09ff2554
Create Date: 2024-xx-xx

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'xxx'
down_revision = '9daf09ff2554'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add has_finance_data column and index."""
    op.add_column('sites',
        sa.Column('has_finance_data', sa.Boolean(),
                  server_default='false', nullable=False))

    op.create_index('idx_sites_has_finance_data', 'sites', ['has_finance_data'])


def downgrade() -> None:
    """Remove has_finance_data column and index."""
    op.drop_index('idx_sites_has_finance_data', table_name='sites')
    op.drop_column('sites', 'has_finance_data')
```

#### File: src/clerk/models.py (UPDATE)
Add to sites_table definition:
```python
Column("has_finance_data", Boolean, server_default="false", nullable=False),
```

### 5. Plugin Manager Enhancement

#### File: src/clerk/utils.py (UPDATE)
```python
def get_plugin_manager():
    """Get or create the plugin manager instance.

    Returns:
        pluggy.PluginManager: Configured plugin manager
    """
    global _plugin_manager

    if _plugin_manager is None:
        _plugin_manager = pluggy.PluginManager("civicband.clerk")
        _plugin_manager.add_hookspecs(ClerkSpec)

    return _plugin_manager


def discover_entry_point_plugins():
    """Discover and load plugins via setuptools entry points.

    This allows pip-installed packages to register as plugins.
    """
    import importlib.metadata

    pm = get_plugin_manager()

    # Look for clerk.plugins entry points
    for entry_point in importlib.metadata.entry_points(group='clerk.plugins'):
        try:
            plugin_class = entry_point.load()
            plugin_instance = plugin_class()
            pm.register(plugin_instance, name=entry_point.name)
            logger.info(f"Loaded plugin from entry point: {entry_point.name}")
        except Exception as e:
            logger.error(f"Failed to load plugin {entry_point.name}: {str(e)}")
```

#### File: src/clerk/plugin_loader.py (UPDATE)
```python
def load_plugins_from_directory(plugins_dir):
    """Load plugins from directory and entry points.

    Args:
        plugins_dir: Directory containing plugin files
    """
    # Load file-based plugins (existing code)
    # ... existing implementation ...

    # NEW: Also discover entry point plugins
    discover_entry_point_plugins()
```

### 6. Database Operations Enhancement

#### File: src/clerk/db.py (UPDATE)
Add new functions for finance data:

```python
def update_site_finance_status(subdomain: str, has_finance_data: bool) -> None:
    """Update site's finance data availability status.

    Args:
        subdomain: Site subdomain
        has_finance_data: Whether site has finance data
    """
    with get_db() as conn:
        conn.execute(
            text("""
                UPDATE sites
                SET has_finance_data = :has_finance_data,
                    last_updated = CURRENT_TIMESTAMP
                WHERE subdomain = :subdomain
            """),
            {"subdomain": subdomain, "has_finance_data": has_finance_data}
        )
        conn.commit()


def get_sites_with_finance_data() -> List[Dict[str, Any]]:
    """Get all sites that have finance data available.

    Returns:
        List of site dictionaries
    """
    with get_db() as conn:
        result = conn.execute(
            text("""
                SELECT * FROM sites
                WHERE has_finance_data = true
                ORDER BY last_updated ASC
            """)
        )
        return [dict(row) for row in result]


def get_next_finance_site() -> Optional[Dict[str, Any]]:
    """Get the next site that needs finance data update.

    Returns site with oldest finance update timestamp.

    Returns:
        Site dictionary or None
    """
    with get_db() as conn:
        result = conn.execute(
            text("""
                SELECT * FROM sites
                WHERE has_finance_data = true
                  AND state = 'CA'  -- Only California has finance data
                ORDER BY last_updated ASC
                LIMIT 1
            """)
        )
        row = result.first()
        return dict(row) if row else None
```

### 7. CLI Commands for Finance Support

#### File: src/clerk/cli.py (UPDATE)
Add new options to existing commands:

```python
@cli.command()
@click.option("--subdomain", help="Site subdomain")
@click.option("--next-site", is_flag=True, help="Process oldest site")
@click.option("--finance", is_flag=True, help="Process finance data (if available)")
def update(subdomain, next_site, finance):
    """Update a municipality's data."""

    if finance:
        # Check if finance plugin is available
        pm = get_plugin_manager()
        finance_processors = pm.hook.get_data_processors(data_type="finance")
        if not any(finance_processors):
            click.echo("Error: Finance plugin not installed", err=True)
            return

        if next_site:
            site = get_next_finance_site()
        elif subdomain:
            site = get_site_by_subdomain(subdomain)
        else:
            click.echo("Error: Specify --subdomain or --next-site", err=True)
            return

        if site:
            # Enqueue finance ETL job
            enqueue_job("finance-etl", site["subdomain"])
            click.echo(f"Enqueued finance ETL for {site['subdomain']}")
    else:
        # Existing update logic for meetings
        # ... existing code ...
```

## Testing Requirements

### Unit Tests
- Test new hookspec registration
- Test plugin command registration
- Test job type registration
- Test database operations for finance status

### Integration Tests
- Test with mock plugin implementation
- Test CLI command discovery
- Test job enqueueing for plugin jobs
- Test entry point plugin loading

## Migration Path

1. **Add new hookspecs** without breaking existing plugins
2. **Update database schema** via Alembic migration
3. **Enhance CLI** to support plugin commands
4. **Update queue system** for plugin jobs
5. **Add entry point discovery** for pip-installed plugins
6. **Test with sample plugin** before finance integration

## Backward Compatibility
- All existing hooks remain unchanged
- Existing plugins continue to work
- New features are additive only
- Database migration is non-destructive

## Dependencies
- pluggy (existing)
- click (existing)
- SQLAlchemy (existing)
- Alembic (existing)

## Files to Modify
1. `src/clerk/hookspecs.py` - Add new hook specifications
2. `src/clerk/cli.py` - Register plugin commands
3. `src/clerk/queue.py` - Support plugin job types
4. `src/clerk/utils.py` - Enhanced plugin manager
5. `src/clerk/plugin_loader.py` - Entry point discovery
6. `src/clerk/models.py` - Add has_finance_data column
7. `src/clerk/db.py` - Finance status operations
8. `alembic/versions/` - New migration file

## Success Criteria
- ✅ Plugins can register CLI commands
- ✅ Plugins can register job types
- ✅ Entry point plugins are discovered
- ✅ Finance status tracked in database
- ✅ Backward compatibility maintained
- ✅ Tests pass for all changes

## Timeline
- Day 1: Add hookspecs and database schema
- Day 2: Implement CLI and queue enhancements
- Day 3: Add entry point discovery
- Day 4: Testing and documentation