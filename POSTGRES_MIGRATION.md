# PostgreSQL Migration Guide

This guide documents the migration of `civic.db` from SQLite to PostgreSQL for production environments.

## Overview

As of version 0.1.0, clerk supports both SQLite (for development) and PostgreSQL (for production) for the `civic.db` site registry database. Per-site `meetings.db` files remain as SQLite.

## Key Changes

### Database Abstraction Layer

- **New module**: `clerk.db` provides database abstraction
- **New module**: `clerk.models` defines SQLAlchemy table schemas
- **Migration system**: Alembic manages schema migrations
- **Dependencies added**:
  - `sqlalchemy>=2.0.0`
  - `psycopg2-binary>=2.9.0`
  - `alembic>=1.13.0`

### Environment-Based Configuration

The system automatically detects which database to use based on the `DATABASE_URL` environment variable:

- **Development** (no `DATABASE_URL`): Uses SQLite `civic.db`
- **Production** (`DATABASE_URL` set): Uses PostgreSQL

Example:
```bash
# Development mode (SQLite)
clerk new my-city --name "My City"

# Production mode (PostgreSQL)
export DATABASE_URL="postgresql://user:pass@host:5432/civicband"
clerk new my-city --name "My City"
```

## Installation

### For Development

No changes needed! The system continues to use SQLite by default:

```bash
cd clerk/
uv pip install -e .
clerk --help
```

### For Production

1. **Provision PostgreSQL database** (managed service recommended)
2. **Set DATABASE_URL** environment variable:
   ```bash
   export DATABASE_URL="postgresql://user:password@host:5432/database"
   ```

3. **Run Alembic migrations** to create schema:
   ```bash
   cd clerk/
   alembic upgrade head
   ```

4. **Migrate existing data** (one-time):
   ```bash
   # See deployment runbook in docs/plans/2026-01-03-postgres-migration-design.md
   python ../public-works/scripts/migrate-civic-db.py
   ```

## API Changes

### Before (sqlite_utils)

```python
import sqlite_utils

db = sqlite_utils.Database("civic.db")
db["sites"].insert({"subdomain": "alameda", "name": "Alameda"})
site = db["sites"].get("alameda")
db["sites"].update("alameda", {"status": "deployed"})
```

### After (SQLAlchemy via abstraction)

```python
from clerk.db import civic_db_connection, insert_site, get_site_by_subdomain, update_site

# All operations use context manager for proper connection handling
with civic_db_connection() as conn:
    # Insert
    insert_site(conn, {"subdomain": "alameda", "name": "Alameda"})

    # Get
    site = get_site_by_subdomain(conn, "alameda")

    # Update
    update_site(conn, "alameda", {"status": "deployed"})
```

### Helper Functions Available

See `clerk/db.py` for full API:

- `get_civic_db()` - Get database engine
- `civic_db_connection()` - Context manager for connections
- `insert_site(conn, site_data)` - Insert new site
- `upsert_site(conn, site_data)` - Insert or update site
- `get_site_by_subdomain(conn, subdomain)` - Get single site
- `get_all_sites(conn)` - Get all sites
- `get_sites_where(conn, **filters)` - Filter sites
- `update_site(conn, subdomain, updates)` - Update site fields
- `delete_site(conn, subdomain)` - Delete site

## Schema Management

### Alembic Migrations

Schema changes are now managed via Alembic:

```bash
# Create a new migration
alembic revision --autogenerate -m "Add new column"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1
```

### Schema Definition

The schema is defined in `clerk/models.py` using SQLAlchemy Table objects:

```python
from clerk.models import sites_table, metadata

# Table definition
sites_table = Table(
    "sites",
    metadata,
    Column("subdomain", String, primary_key=True),
    Column("name", String),
    # ...
)
```

## Testing

### Running Tests

```bash
# SQLite tests (default)
pytest tests/test_db.py

# PostgreSQL tests (requires TEST_DATABASE_URL)
export TEST_DATABASE_URL="postgresql://test:test@localhost:5432/clerk_test"
pytest tests/test_db.py
```

### Test Database Setup (PostgreSQL)

If you want to run PostgreSQL tests locally:

```bash
# Using Docker
docker run -d \\
  --name clerk-test-db \\
  -e POSTGRES_PASSWORD=test \\
  -e POSTGRES_DB=clerk_test \\
  -p 5432:5432 \\
  postgres:15

# Run tests
export TEST_DATABASE_URL="postgresql://postgres:test@localhost:5432/clerk_test"
pytest tests/test_db.py::TestPostgreSQLBackend
```

## Backward Compatibility

### SQLite Remains Default

Existing workflows continue to work without changes. The system defaults to SQLite when `DATABASE_URL` is not set.

### Per-Site Databases Unchanged

Per-site `meetings.db` files remain as SQLite:
- `sites/{subdomain}/meetings.db` - Still SQLite
- No changes to datasette serving
- No changes to PDF/OCR/transform pipeline

### Plugin Compatibility

Plugins that use the hook system are automatically compatible:

```python
# This works for both SQLite and PostgreSQL
pm.hook.update_site(subdomain="test", updates={"status": "deployed"})
pm.hook.create_site(subdomain="test", site_data={...})
```

## Troubleshooting

### Connection Errors

If you see "Cannot connect to database" errors:

1. **Check DATABASE_URL format**:
   ```bash
   echo $DATABASE_URL
   # Should be: postgresql://user:pass@host:5432/database
   ```

2. **Test connection manually**:
   ```bash
   psql $DATABASE_URL -c "SELECT 1;"
   ```

3. **Check firewall rules**: Ensure your application server can reach PostgreSQL

### Migration Issues

If Alembic migrations fail:

1. **Check current migration state**:
   ```bash
   alembic current
   alembic history
   ```

2. **Reset and retry** (development only):
   ```bash
   # Drop all tables and re-create
   python -c "from clerk.models import metadata; from clerk.db import get_civic_db; metadata.drop_all(get_civic_db()); metadata.create_all(get_civic_db())"

   # Stamp with current migration
   alembic stamp head
   ```

### Rollback to SQLite

To rollback to SQLite in production:

```bash
# 1. Unset DATABASE_URL
unset DATABASE_URL

# 2. Verify fallback
python -c "from clerk.db import get_civic_db; print(get_civic_db().url)"
# Should show: sqlite:///civic.db

# 3. Restart application
```

## Performance Notes

### Connection Pooling

SQLAlchemy manages connection pooling automatically for PostgreSQL:

- Default pool size: 5 connections
- Max overflow: 10 connections
- Pool recycle: 3600 seconds (1 hour)

### Query Performance

PostgreSQL queries are generally faster than SQLite for:
- Concurrent access (multiple clerk processes)
- Complex WHERE clauses with indexes
- Large datasets (>10k sites)

SQLite is faster for:
- Single-process, sequential access
- Small datasets (<1k sites)
- Development/testing

## Additional Resources

- **Full design document**: `docs/plans/2026-01-03-postgres-migration-design.md`
- **Migration script**: `public-works/scripts/migrate-civic-db.py`
- **Tests**: `tests/test_db.py`
- **SQLAlchemy docs**: https://docs.sqlalchemy.org/
- **Alembic docs**: https://alembic.sqlalchemy.org/

## Support

For issues or questions:
1. Check this migration guide
2. Review test cases in `tests/test_db.py`
3. Consult the design document for architectural details
4. File an issue if you encounter bugs
