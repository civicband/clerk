"""Initial schema

Revision ID: 45db71312424
Revises: 
Create Date: 2026-01-03 13:56:48.784183

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '45db71312424'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'sites',
        sa.Column('subdomain', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('state', sa.String(), nullable=True),
        sa.Column('kind', sa.String(), nullable=True),
        sa.Column('scraper', sa.String(), nullable=True),
        sa.Column('pages', sa.Integer(), nullable=True),
        sa.Column('start_year', sa.Integer(), nullable=True),
        sa.Column('extra', sa.String(), nullable=True),
        sa.Column('country', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('last_updated', sa.String(), nullable=True),
        sa.Column('last_deployed', sa.String(), nullable=True),
        sa.Column('lat', sa.String(), nullable=True),
        sa.Column('lng', sa.String(), nullable=True),
        sa.Column('extraction_status', sa.String(), server_default='pending', nullable=True),
        sa.Column('last_extracted', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('subdomain')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('sites')
