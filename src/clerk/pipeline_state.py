"""Pipeline state management helpers.

Provides atomic operations for updating pipeline state in sites table.
"""

from datetime import UTC, datetime
from sqlalchemy import select, update

from .db import civic_db_connection
from .models import sites_table


def initialize_stage(subdomain: str, stage: str, total_jobs: int) -> None:
    """Initialize a pipeline stage with job counters.

    Args:
        subdomain: Site subdomain
        stage: Pipeline stage (fetch/ocr/compilation/extraction/deploy)
        total_jobs: Total number of jobs for this stage
    """
    with civic_db_connection() as conn:
        conn.execute(
            update(sites_table)
            .where(sites_table.c.subdomain == subdomain)
            .values(
                current_stage=stage,
                **{
                    f"{stage}_total": total_jobs,
                    f"{stage}_completed": 0,
                    f"{stage}_failed": 0,
                },
                coordinator_enqueued=False,
                updated_at=datetime.now(UTC),
            )
        )


def increment_completed(subdomain: str, stage: str) -> None:
    """Atomically increment completed counter for a stage.

    Args:
        subdomain: Site subdomain
        stage: Pipeline stage
    """
    with civic_db_connection() as conn:
        stage_completed_col = getattr(sites_table.c, f"{stage}_completed")

        conn.execute(
            update(sites_table)
            .where(sites_table.c.subdomain == subdomain)
            .values(
                **{f"{stage}_completed": stage_completed_col + 1},
                updated_at=datetime.now(UTC),
            )
        )


def increment_failed(
    subdomain: str,
    stage: str,
    error_message: str,
    error_class: str,
) -> None:
    """Atomically increment failed counter and record error.

    Args:
        subdomain: Site subdomain
        stage: Pipeline stage
        error_message: Error message to record
        error_class: Error class name
    """
    with civic_db_connection() as conn:
        stage_failed_col = getattr(sites_table.c, f"{stage}_failed")

        # Truncate error message to avoid database overflow
        truncated_message = f"{error_class}: {error_message}"[:500]

        conn.execute(
            update(sites_table)
            .where(sites_table.c.subdomain == subdomain)
            .values(
                **{f"{stage}_failed": stage_failed_col + 1},
                last_error_stage=stage,
                last_error_message=truncated_message,
                last_error_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )


def should_trigger_coordinator(subdomain: str, stage: str) -> bool:
    """Check if all jobs for a stage are complete.

    Args:
        subdomain: Site subdomain
        stage: Pipeline stage

    Returns:
        True if completed + failed == total (all jobs done)
    """
    with civic_db_connection() as conn:
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == subdomain)
        ).fetchone()

    if not site:
        return False

    total = getattr(site, f"{stage}_total")
    completed = getattr(site, f"{stage}_completed")
    failed = getattr(site, f"{stage}_failed")

    return (completed + failed) == total and not site.coordinator_enqueued


def claim_coordinator_enqueue(subdomain: str) -> bool:
    """Atomically claim the right to enqueue coordinator.

    Uses database-level constraint to ensure only one job succeeds.

    Args:
        subdomain: Site subdomain

    Returns:
        True if this call successfully claimed, False if already claimed
    """
    with civic_db_connection() as conn:
        result = conn.execute(
            update(sites_table)
            .where(
                sites_table.c.subdomain == subdomain,
                sites_table.c.coordinator_enqueued == False,  # Critical: prevents duplicates
            )
            .values(
                coordinator_enqueued=True,
                updated_at=datetime.now(UTC),
            )
        )

        return result.rowcount == 1
