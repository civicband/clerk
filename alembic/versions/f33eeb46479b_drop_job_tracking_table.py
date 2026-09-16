"""drop job_tracking table

Revision ID: f33eeb46479b
Revises: bf2f44a2e00c
Create Date: 2026-09-16 14:49:36.147875

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import func

# revision identifiers, used by Alembic.
revision: str = "f33eeb46479b"
down_revision: str | Sequence[str] | None = "bf2f44a2e00c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the job_tracking table (indexes are dropped with it)."""
    op.drop_table("job_tracking")


def downgrade() -> None:
    """Recreate the table as it existed at bf2f44a2e00c (run_id included)."""
    op.create_table(
        "job_tracking",
        sa.Column("rq_job_id", sa.String(), nullable=False),
        sa.Column("subdomain", sa.String(), nullable=False),
        sa.Column("job_type", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=True),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=func.now(), nullable=True
        ),
        sa.PrimaryKeyConstraint("rq_job_id"),
    )
    op.create_index("ix_job_tracking_subdomain", "job_tracking", ["subdomain"], unique=False)
    op.create_index("ix_job_tracking_run_id", "job_tracking", ["run_id"], unique=False)
