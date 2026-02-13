"""Database operations for finance data support."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import select, text, update

from .db import civic_db_connection
from .models import sites_table


def update_site_finance_status(subdomain: str, has_finance_data: bool) -> None:
    """Update site's finance data availability status.

    Args:
        subdomain: Site subdomain
        has_finance_data: Whether site has finance data
    """
    with civic_db_connection() as conn:
        stmt = (
            update(sites_table)
            .where(sites_table.c.subdomain == subdomain)
            .values(has_finance_data=has_finance_data, updated_at=text("CURRENT_TIMESTAMP"))
        )
        conn.execute(stmt)


def get_sites_with_finance_data() -> list[dict[str, Any]]:
    """Get all sites that have finance data available.

    Returns:
        List of site dictionaries
    """
    with civic_db_connection() as conn:
        stmt = (
            select(sites_table)
            .where(sites_table.c.has_finance_data)
            .order_by(sites_table.c.updated_at.asc())
        )
        result = conn.execute(stmt)
        return [dict(row._mapping) for row in result]


def get_next_finance_site() -> dict[str, Any] | None:
    """Get the next site that needs finance data update.

    Returns site with oldest finance update timestamp.

    Returns:
        Site dictionary or None
    """
    with civic_db_connection() as conn:
        stmt = (
            select(sites_table)
            .where(sites_table.c.has_finance_data)
            .where(sites_table.c.state == "CA")  # Only California has finance data
            .order_by(sites_table.c.updated_at.asc().nulls_first())
            .limit(1)
        )
        result = conn.execute(stmt).fetchone()
        return dict(result._mapping) if result else None


def get_all_sites() -> list[dict[str, Any]]:
    """Get all sites from the database.

    Returns:
        List of site dictionaries
    """
    with civic_db_connection() as conn:
        stmt = select(sites_table)
        result = conn.execute(stmt)
        return [dict(row._mapping) for row in result]


def update_site(subdomain: str, updates: dict[str, Any]) -> None:
    """Update a site with the given data.

    Args:
        subdomain: Site subdomain
        updates: Dictionary of fields to update
    """
    with civic_db_connection() as conn:
        stmt = update(sites_table).where(sites_table.c.subdomain == subdomain).values(**updates)
        conn.execute(stmt)


def update_site_finance_metadata(
    subdomain: str,
    source: str | None = None,
    coverage_start: date | None = None,
    coverage_end: date | None = None,
    record_count: int | None = None,
    data_types: list[str] | None = None,
) -> None:
    """Update site finance metadata.

    Args:
        subdomain: Site subdomain
        source: Source of finance data (e.g., 'CAL-ACCESS')
        coverage_start: Start date of data coverage
        coverage_end: End date of data coverage
        record_count: Number of finance records
        data_types: List of data types available
    """
    updates = {
        "finance_last_updated": datetime.utcnow(),
    }

    if source is not None:
        updates["finance_source"] = source
    if coverage_start is not None:
        updates["finance_coverage_start"] = coverage_start
    if coverage_end is not None:
        updates["finance_coverage_end"] = coverage_end
    if record_count is not None:
        updates["finance_record_count"] = record_count
    if data_types is not None:
        updates["finance_data_types"] = data_types

    with civic_db_connection() as conn:
        stmt = update(sites_table).where(sites_table.c.subdomain == subdomain).values(**updates)
        conn.execute(stmt)


def get_finance_metadata(subdomain: str) -> dict[str, Any] | None:
    """Get finance metadata for a site.

    Args:
        subdomain: Site subdomain

    Returns:
        Dictionary with finance metadata or None if site not found
    """
    with civic_db_connection() as conn:
        stmt = select(
            sites_table.c.has_finance_data,
            sites_table.c.finance_last_updated,
            sites_table.c.finance_source,
            sites_table.c.finance_coverage_start,
            sites_table.c.finance_coverage_end,
            sites_table.c.finance_record_count,
            sites_table.c.finance_data_types,
        ).where(sites_table.c.subdomain == subdomain)

        result = conn.execute(stmt).fetchone()
        if result:
            return {
                "has_finance_data": result.has_finance_data,
                "last_updated": result.finance_last_updated,
                "source": result.finance_source,
                "coverage_start": result.finance_coverage_start,
                "coverage_end": result.finance_coverage_end,
                "record_count": result.finance_record_count,
                "data_types": result.finance_data_types,
            }
        return None
