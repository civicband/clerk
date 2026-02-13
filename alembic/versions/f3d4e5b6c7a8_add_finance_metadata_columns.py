"""add_finance_metadata_columns

Revision ID: f3d4e5b6c7a8
Revises: e2eeb77e18bc
Create Date: 2026-02-13 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3d4e5b6c7a8'
down_revision: Union[str, Sequence[str], None] = 'e2eeb77e18bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add finance-specific metadata columns."""
    # Add finance metadata columns
    op.add_column('sites',
        sa.Column('finance_last_updated', sa.DateTime(timezone=True),
                  nullable=True,
                  comment='Last time finance data was updated'))

    op.add_column('sites',
        sa.Column('finance_source', sa.String(100),
                  nullable=True,
                  comment='Source of finance data (e.g., CAL-ACCESS, local records)'))

    op.add_column('sites',
        sa.Column('finance_coverage_start', sa.Date(),
                  nullable=True,
                  comment='Start date of finance data coverage'))

    op.add_column('sites',
        sa.Column('finance_coverage_end', sa.Date(),
                  nullable=True,
                  comment='End date of finance data coverage'))

    op.add_column('sites',
        sa.Column('finance_record_count', sa.Integer(),
                  nullable=True,
                  comment='Number of finance records available'))

    op.add_column('sites',
        sa.Column('finance_data_types', sa.JSON(),
                  nullable=True,
                  comment='Types of finance data available (contributions, expenditures, etc.)'))

    # Create composite index for finance queries
    op.create_index('idx_sites_finance_metadata', 'sites',
                    ['has_finance_data', 'finance_last_updated', 'state'])


def downgrade() -> None:
    """Remove finance-specific metadata columns."""
    op.drop_index('idx_sites_finance_metadata', table_name='sites')
    op.drop_column('sites', 'finance_data_types')
    op.drop_column('sites', 'finance_record_count')
    op.drop_column('sites', 'finance_coverage_end')
    op.drop_column('sites', 'finance_coverage_start')
    op.drop_column('sites', 'finance_source')
    op.drop_column('sites', 'finance_last_updated')