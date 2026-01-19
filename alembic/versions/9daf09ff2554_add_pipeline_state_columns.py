"""add_pipeline_state_columns

Revision ID: 9daf09ff2554
Revises: s9z7il1abnmz
Create Date: 2026-01-18 18:03:34.722317

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9daf09ff2554"
down_revision: str | Sequence[str] | None = "s9z7il1abnmz"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add pipeline state tracking columns to sites table."""
    # Pipeline state tracking
    op.add_column("sites", sa.Column("current_stage", sa.String(), nullable=True))
    op.add_column("sites", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sites", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    # Fetch stage counters
    op.add_column(
        "sites", sa.Column("fetch_total", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "sites", sa.Column("fetch_completed", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "sites", sa.Column("fetch_failed", sa.Integer(), server_default="0", nullable=False)
    )

    # OCR stage counters
    op.add_column("sites", sa.Column("ocr_total", sa.Integer(), server_default="0", nullable=False))
    op.add_column(
        "sites", sa.Column("ocr_completed", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "sites", sa.Column("ocr_failed", sa.Integer(), server_default="0", nullable=False)
    )

    # Compilation stage counters
    op.add_column(
        "sites", sa.Column("compilation_total", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "sites",
        sa.Column("compilation_completed", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "sites", sa.Column("compilation_failed", sa.Integer(), server_default="0", nullable=False)
    )

    # Extraction stage counters
    op.add_column(
        "sites", sa.Column("extraction_total", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "sites", sa.Column("extraction_completed", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "sites", sa.Column("extraction_failed", sa.Integer(), server_default="0", nullable=False)
    )

    # Deploy stage counters
    op.add_column(
        "sites", sa.Column("deploy_total", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "sites", sa.Column("deploy_completed", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "sites", sa.Column("deploy_failed", sa.Integer(), server_default="0", nullable=False)
    )

    # Coordinator tracking
    op.add_column(
        "sites",
        sa.Column("coordinator_enqueued", sa.Boolean(), server_default="false", nullable=False),
    )

    # Error observability
    op.add_column("sites", sa.Column("last_error_stage", sa.String(), nullable=True))
    op.add_column("sites", sa.Column("last_error_message", sa.Text(), nullable=True))
    op.add_column("sites", sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True))

    # Indexes for performance
    op.create_index("idx_sites_current_stage", "sites", ["current_stage"])
    op.create_index("idx_sites_updated_at", "sites", ["updated_at"])
    op.create_index(
        "idx_sites_coordinator_enqueued",
        "sites",
        ["subdomain", "coordinator_enqueued"],
        postgresql_where=sa.text("coordinator_enqueued = false"),
    )


def downgrade() -> None:
    """Remove pipeline state tracking columns."""
    # Drop indexes
    op.drop_index("idx_sites_coordinator_enqueued", table_name="sites")
    op.drop_index("idx_sites_updated_at", table_name="sites")
    op.drop_index("idx_sites_current_stage", table_name="sites")

    # Drop columns (in reverse order)
    op.drop_column("sites", "last_error_at")
    op.drop_column("sites", "last_error_message")
    op.drop_column("sites", "last_error_stage")
    op.drop_column("sites", "coordinator_enqueued")
    op.drop_column("sites", "deploy_failed")
    op.drop_column("sites", "deploy_completed")
    op.drop_column("sites", "deploy_total")
    op.drop_column("sites", "extraction_failed")
    op.drop_column("sites", "extraction_completed")
    op.drop_column("sites", "extraction_total")
    op.drop_column("sites", "compilation_failed")
    op.drop_column("sites", "compilation_completed")
    op.drop_column("sites", "compilation_total")
    op.drop_column("sites", "ocr_failed")
    op.drop_column("sites", "ocr_completed")
    op.drop_column("sites", "ocr_total")
    op.drop_column("sites", "fetch_failed")
    op.drop_column("sites", "fetch_completed")
    op.drop_column("sites", "fetch_total")
    op.drop_column("sites", "updated_at")
    op.drop_column("sites", "started_at")
    op.drop_column("sites", "current_stage")
