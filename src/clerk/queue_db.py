"""Database helpers for queue job tracking and progress."""

from datetime import UTC, datetime

from sqlalchemy import delete, insert, select, update

from .models import job_tracking_table, site_progress_table


def track_job(conn, rq_job_id, subdomain, job_type, stage):
    """Track an RQ job in PostgreSQL for observability.

    Args:
        conn: SQLAlchemy connection
        rq_job_id: RQ's job ID
        subdomain: Site subdomain
        job_type: Job type (fetch-site, ocr-page, etc.)
        stage: Processing stage (fetch, ocr, extraction, deploy)
    """
    stmt = insert(job_tracking_table).values(
        rq_job_id=rq_job_id,
        subdomain=subdomain,
        job_type=job_type,
        stage=stage,
        created_at=datetime.now(UTC),
    )
    conn.execute(stmt)
    conn.commit()


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
    conn.commit()


def update_site_progress(conn, subdomain, stage=None, stage_total=None):
    """Update site progress.

    Args:
        conn: SQLAlchemy connection
        subdomain: Site subdomain
        stage: New stage (optional)
        stage_total: Total items in stage (optional)
    """
    updates = {"updated_at": datetime.now(UTC)}
    if stage:
        updates["current_stage"] = stage
    if stage_total is not None:
        updates["stage_total"] = stage_total
        updates["stage_completed"] = 0  # Reset counter

    stmt = (
        update(site_progress_table)
        .where(site_progress_table.c.subdomain == subdomain)
        .values(**updates)
    )
    conn.execute(stmt)
    conn.commit()


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
    conn.commit()


def get_jobs_for_site(conn, subdomain):
    """Get all job tracking records for a site.

    Args:
        conn: SQLAlchemy connection
        subdomain: Site subdomain

    Returns:
        List of job tracking records as dictionaries
    """
    stmt = select(job_tracking_table).where(job_tracking_table.c.subdomain == subdomain)
    results = conn.execute(stmt).fetchall()
    return [dict(row._mapping) for row in results]


def delete_jobs_for_site(conn, subdomain):
    """Delete all job tracking records for a site.

    Args:
        conn: SQLAlchemy connection
        subdomain: Site subdomain
    """
    stmt = delete(job_tracking_table).where(job_tracking_table.c.subdomain == subdomain)
    conn.execute(stmt)
    conn.commit()


def delete_site_progress(conn, subdomain):
    """Delete site progress record.

    Args:
        conn: SQLAlchemy connection
        subdomain: Site subdomain
    """
    stmt = delete(site_progress_table).where(site_progress_table.c.subdomain == subdomain)
    conn.execute(stmt)
    conn.commit()
