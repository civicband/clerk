"""add_has_finance_data_column

Revision ID: e2eeb77e18bc
Revises: 9daf09ff2554
Create Date: 2026-02-12 16:08:00.952253

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2eeb77e18bc'
down_revision: Union[str, Sequence[str], None] = '9daf09ff2554'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add has_finance_data column and index."""
    op.add_column('sites',
        sa.Column('has_finance_data', sa.Boolean(),
                  server_default='false', nullable=False))

    op.create_index('idx_sites_has_finance_data', 'sites', ['has_finance_data'])


def downgrade() -> None:
    """Remove has_finance_data column and index."""
    op.drop_index('idx_sites_has_finance_data', table_name='sites')
    op.drop_column('sites', 'has_finance_data')
