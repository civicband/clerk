"""Database abstraction layer for civic.db.

Supports both SQLite (dev) and PostgreSQL (production) based on DATABASE_URL.
"""

from contextlib import contextmanager

import click
from sqlalchemy import create_engine, delete, insert, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import QueuePool
from sqlalchemy.sql import text

from .settings import get_env


def get_civic_db():
    """
    Returns a database engine based on environment.

    - If DATABASE_URL is set → SQLAlchemy engine for PostgreSQL
    - If not set → SQLAlchemy engine for SQLite civic.db

    Fails fast if PostgreSQL connection cannot be established.
    """
    database_url = get_env("DATABASE_URL")

    if database_url:
        # Normalize postgres:// to postgresql:// for SQLAlchemy 1.4+
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)

        # Production: PostgreSQL
        try:
            engine = create_engine(
                database_url,
                poolclass=QueuePool,
                pool_pre_ping=True,  # Verify connections before use
                pool_recycle=3600,  # Recycle connections every hour
                connect_args={"connect_timeout": 10} if "postgresql" in database_url else {},
            )
            # Test connection immediately
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return engine
        except OperationalError as e:
            error_msg = f"Cannot connect to database: {e}"
            print(f"ERROR: {error_msg}")
            print("DATABASE_URL is set but connection failed.")
            # Raise exception instead of sys.exit() so RQ workers can handle job failure properly
            raise RuntimeError(error_msg) from e
    else:
        # Development: SQLite
        return create_engine("sqlite:///civic.db")


@contextmanager
def civic_db_connection():
    """
    Context manager for database connections.

    Automatically handles commit/rollback and connection cleanup.

    Usage:
        with civic_db_connection() as conn:
            insert_site(conn, {"subdomain": "alameda", "name": "Alameda"})
    """
    engine = get_civic_db()
    conn = engine.connect()
    trans = conn.begin()
    try:
        yield conn
        trans.commit()
    except Exception:
        trans.rollback()
        raise
    finally:
        conn.close()


# Helper functions for common operations


def insert_site(conn, site_data):
    """Insert a site record.

    Args:
        conn: SQLAlchemy connection
        site_data: Dictionary with site fields

    Returns:
        The inserted row ID (for SQLite) or None (for PostgreSQL with RETURNING)
    """
    from .models import sites_table

    stmt = insert(sites_table).values(**site_data)
    result = conn.execute(stmt)
    return result.inserted_primary_key[0] if result.inserted_primary_key else None


def upsert_site(conn, site_data):
    """Insert or update a site record.

    Uses INSERT ... ON CONFLICT for PostgreSQL, INSERT OR REPLACE for SQLite.

    Args:
        conn: SQLAlchemy connection
        site_data: Dictionary with site fields (must include subdomain)
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from .models import sites_table

    # Detect which dialect we're using
    dialect_name = conn.dialect.name

    if dialect_name == "postgresql":
        stmt = pg_insert(sites_table).values(**site_data)
        stmt = stmt.on_conflict_do_update(index_elements=["subdomain"], set_=site_data)
    elif dialect_name == "sqlite":
        stmt = sqlite_insert(sites_table).values(**site_data)
        stmt = stmt.on_conflict_do_update(index_elements=["subdomain"], set_=site_data)
    else:
        # Fallback: delete then insert
        delete_site(conn, site_data["subdomain"])
        stmt = insert(sites_table).values(**site_data)

    conn.execute(stmt)


def get_site_by_subdomain(conn, subdomain):
    """Get a site by subdomain.

    Args:
        conn: SQLAlchemy connection
        subdomain: Site subdomain

    Returns:
        Dictionary with site data or None if not found
    """
    from .models import sites_table

    stmt = select(sites_table).where(sites_table.c.subdomain == subdomain)
    result = conn.execute(stmt)
    row = result.fetchone()
    return dict(row._mapping) if row else None


def update_site(conn, subdomain, updates):
    """Update site fields.

    Args:
        conn: SQLAlchemy connection
        subdomain: Site subdomain
        updates: Dictionary with fields to update
    """
    from .models import sites_table

    stmt = update(sites_table).where(sites_table.c.subdomain == subdomain).values(**updates)
    conn.execute(stmt)


def delete_site(conn, subdomain):
    """Delete a site by subdomain.

    Args:
        conn: SQLAlchemy connection
        subdomain: Site subdomain
    """
    from .models import sites_table

    stmt = delete(sites_table).where(sites_table.c.subdomain == subdomain)
    conn.execute(stmt)


def get_all_sites(conn, order_by=None):
    """Get all sites.

    Args:
        conn: SQLAlchemy connection
        order_by: Column name to order by (optional)

    Returns:
        List of dictionaries with site data
    """
    from .models import sites_table

    stmt = select(sites_table)
    if order_by and hasattr(sites_table.c, order_by):
        stmt = stmt.order_by(getattr(sites_table.c, order_by))

    result = conn.execute(stmt)
    return [dict(row._mapping) for row in result]


def get_oldest_site(lookback_hours=23):
    """Find site with oldest last_updated timestamp.

    Args:
        lookback_hours: Skip sites updated within this many hours (default: 23)

    Returns:
        Subdomain string or None if no eligible sites
    """
    from datetime import datetime, timedelta

    from sqlalchemy import cast, or_
    from sqlalchemy.types import DateTime

    from .models import sites_table

    cutoff = datetime.now() - timedelta(hours=lookback_hours)

    # Cast last_updated from String to DateTime for comparison
    # (last_updated is stored as String for backward compatibility)
    last_updated_dt = cast(sites_table.c.last_updated, DateTime)

    stmt = (
        select(sites_table.c.subdomain)
        .where(
            or_(
                sites_table.c.last_updated.is_(None),
                last_updated_dt < cutoff,
            )
        )
        .order_by(sites_table.c.last_updated.asc().nulls_first())
        .limit(1)
    )

    with civic_db_connection() as conn:
        result = conn.execute(stmt).fetchone()
        return result[0] if result else None


def _find_alembic_ini():
    """Find alembic.ini file in current directory or package location.

    Returns:
        Path to alembic.ini file

    Raises:
        click.Abort: If alembic.ini is not found
    """
    import sys
    from pathlib import Path

    # Try current directory first
    cwd_ini = Path.cwd() / "alembic.ini"
    if cwd_ini.exists():
        return cwd_ini

    # Try package location (for installed package)
    package_ini = Path(sys.prefix) / "share" / "clerk" / "alembic.ini"
    if package_ini.exists():
        return package_ini

    click.secho(
        "Error: alembic.ini not found. Please run this command from the project root directory.",
        fg="red",
    )
    raise click.Abort()


def _run_alembic_command(*args):
    """Run an alembic command and display output.

    Args:
        *args: Arguments to pass to alembic command

    Raises:
        click.Abort: If alembic command fails
    """
    import subprocess

    alembic_ini = _find_alembic_ini()

    result = subprocess.run(
        ["alembic", "-c", str(alembic_ini), *args],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        click.secho(f"Error running alembic {args[0]}: {result.stderr}", fg="red")
        raise click.Abort()

    click.echo(result.stdout)
    if result.stderr:
        click.echo(result.stderr, err=True)


@click.group()
def db():
    """Database migration commands"""
    pass


@db.command()
def upgrade():
    """Run database migrations to latest version"""
    _run_alembic_command("upgrade", "head")


@db.command()
def current():
    """Show current database migration version"""
    _run_alembic_command("current")


@db.command()
def history():
    """Show database migration history"""
    _run_alembic_command("history")
