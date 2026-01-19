"""rename site_id to subdomain

Revision ID: s9z7il1abnmz
Revises: c27bd77144ce
Create Date: 2026-01-14 18:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "s9z7il1abnmz"
down_revision: str | Sequence[str] | None = "c27bd77144ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - rename site_id to subdomain in both tables."""
    # Rename column in job_tracking table
    op.alter_column("job_tracking", "site_id", new_column_name="subdomain")

    # Rename the index on job_tracking
    op.drop_index("ix_job_tracking_site_id", table_name="job_tracking")
    op.create_index("ix_job_tracking_subdomain", "job_tracking", ["subdomain"])

    # Rename column in site_progress table
    op.alter_column("site_progress", "site_id", new_column_name="subdomain")


def downgrade() -> None:
    """Downgrade schema - rename subdomain back to site_id."""
    # Rename column back in site_progress table
    op.alter_column("site_progress", "subdomain", new_column_name="site_id")

    # Rename the index back on job_tracking
    op.drop_index("ix_job_tracking_subdomain", table_name="job_tracking")
    op.create_index("ix_job_tracking_site_id", "job_tracking", ["site_id"])

    # Rename column back in job_tracking table
    op.alter_column("job_tracking", "subdomain", new_column_name="site_id")
