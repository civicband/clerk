"""Database helpers for site progress tracking."""

from datetime import UTC, datetime

from sqlalchemy import delete, update

from .models import site_progress_table


def create_site_progress(conn, subdomain, stage):
    """Create or update site progress tracking.

    Args:
        conn: SQLAlchemy connection
        subdomain: Site subdomain
        stage: Current processing stage
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    data = {
        "subdomain": subdomain,
        "current_stage": stage,
        "started_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }

    # Upsert (insert or update on conflict)
    if conn.dialect.name == "postgresql":
        stmt = pg_insert(site_progress_table).values(**data)
        stmt = stmt.on_conflict_do_update(index_elements=["subdomain"], set_=data)
    else:
        stmt = sqlite_insert(site_progress_table).values(**data)
        stmt = stmt.on_conflict_do_update(index_elements=["subdomain"], set_=data)

    conn.execute(stmt)


def update_site_progress(conn, subdomain, stage=None, stage_total=None):
    """Update site progress.

    Args:
        conn: SQLAlchemy connection
        subdomain: Site subdomain
        stage: New stage (optional)
        stage_total: Total items in stage (optional)
    """
    updates = {
        "updated_at": datetime.now(UTC),
    }
    if stage:
        updates["current_stage"] = stage
    if stage_total is not None:
        updates["stage_total"] = stage_total
        updates["stage_completed"] = 0  # type: ignore # Reset counter

    stmt = (
        update(site_progress_table)
        .where(site_progress_table.c.subdomain == subdomain)
        .values(**updates)
    )
    conn.execute(stmt)


def increment_stage_progress(conn, subdomain):
    """Increment the stage completion counter.

    Args:
        conn: SQLAlchemy connection
        subdomain: Site subdomain
    """
    stmt = (
        update(site_progress_table)
        .where(site_progress_table.c.subdomain == subdomain)
        .values(
            stage_completed=site_progress_table.c.stage_completed + 1, updated_at=datetime.now(UTC)
        )
    )
    conn.execute(stmt)


def delete_site_progress(conn, subdomain):
    """Delete site progress record.

    Args:
        conn: SQLAlchemy connection
        subdomain: Site subdomain
    """
    stmt = delete(site_progress_table).where(site_progress_table.c.subdomain == subdomain)
    conn.execute(stmt)
