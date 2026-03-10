"""add description to task_checklist

Revision ID: a1b2c3d4e5f6
Revises: 0eea1ee4b2c4
Create Date: 2026-03-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '0eea1ee4b2c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('task_checklist', sa.Column('description', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('task_checklist', 'description')
