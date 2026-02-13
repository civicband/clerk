"""Database operations for finance data support."""

from typing import Any, Dict, List, Optional

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
            .values(
                has_finance_data=has_finance_data,
                updated_at=text("CURRENT_TIMESTAMP")
            )
        )
        conn.execute(stmt)


def get_sites_with_finance_data() -> List[Dict[str, Any]]:
    """Get all sites that have finance data available.

    Returns:
        List of site dictionaries
    """
    with civic_db_connection() as conn:
        stmt = (
            select(sites_table)
            .where(sites_table.c.has_finance_data == True)
            .order_by(sites_table.c.updated_at.asc())
        )
        result = conn.execute(stmt)
        return [dict(row._mapping) for row in result]


def get_next_finance_site() -> Optional[Dict[str, Any]]:
    """Get the next site that needs finance data update.

    Returns site with oldest finance update timestamp.

    Returns:
        Site dictionary or None
    """
    with civic_db_connection() as conn:
        stmt = (
            select(sites_table)
            .where(sites_table.c.has_finance_data == True)
            .where(sites_table.c.state == 'CA')  # Only California has finance data
            .order_by(sites_table.c.updated_at.asc().nulls_first())
            .limit(1)
        )
        result = conn.execute(stmt).fetchone()
        return dict(result._mapping) if result else None


def get_all_sites() -> List[Dict[str, Any]]:
    """Get all sites from the database.

    Returns:
        List of site dictionaries
    """
    with civic_db_connection() as conn:
        stmt = select(sites_table)
        result = conn.execute(stmt)
        return [dict(row._mapping) for row in result]


def update_site(subdomain: str, updates: Dict[str, Any]) -> None:
    """Update a site with the given data.

    Args:
        subdomain: Site subdomain
        updates: Dictionary of fields to update
    """
    with civic_db_connection() as conn:
        stmt = (
            update(sites_table)
            .where(sites_table.c.subdomain == subdomain)
            .values(**updates)
        )
        conn.execute(stmt)