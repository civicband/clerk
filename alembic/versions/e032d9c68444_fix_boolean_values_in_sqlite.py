"""fix_boolean_values_in_sqlite

Revision ID: e032d9c68444
Revises: f3d4e5b6c7a8
Create Date: 2026-02-17 21:34:40.919161

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e032d9c68444'
down_revision: Union[str, Sequence[str], None] = 'f3d4e5b6c7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Fix boolean values stored as strings in SQLite.

    In SQLite, server_default='false' creates a string 'false', not a boolean.
    This migration converts string 'false'/'true' to integer 0/1 for proper
    boolean handling in SQLAlchemy.

    This is a data-only migration and is safe for PostgreSQL (where booleans
    are stored correctly) - the UPDATE statements will have no effect.
    """
    # Convert string 'false' to integer 0
    op.execute(
        "UPDATE sites SET has_finance_data = 0 WHERE has_finance_data = 'false'"
    )

    # Convert string 'true' to integer 1 (if any exist)
    op.execute(
        "UPDATE sites SET has_finance_data = 1 WHERE has_finance_data = 'true'"
    )

    # Also fix coordinator_enqueued if it has the same issue
    op.execute(
        "UPDATE sites SET coordinator_enqueued = 0 WHERE coordinator_enqueued = 'false'"
    )
    op.execute(
        "UPDATE sites SET coordinator_enqueued = 1 WHERE coordinator_enqueued = 'true'"
    )


def downgrade() -> None:
    """Downgrade not supported - this is a data fix."""
    pass
