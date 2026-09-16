"""add run_id to job_tracking

Revision ID: bf2f44a2e00c
Revises: e032d9c68444
Create Date: 2026-09-16 13:53:28.173924

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bf2f44a2e00c"
down_revision: str | Sequence[str] | None = "e032d9c68444"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add run_id column and index to job_tracking."""
    op.add_column("job_tracking", sa.Column("run_id", sa.String(), nullable=True))

    op.create_index("ix_job_tracking_run_id", "job_tracking", ["run_id"])


def downgrade() -> None:
    """Remove run_id column and index from job_tracking."""
    op.drop_index("ix_job_tracking_run_id", table_name="job_tracking")
    op.drop_column("job_tracking", "run_id")
