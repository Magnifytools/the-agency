"""fix: ensure task_checklists has description column

This migration is a safety net. The original migration a1b2c3d4e5f6
targeted the wrong table name (task_checklist instead of task_checklists).
This migration adds the column if it doesn't already exist.

Revision ID: f1x_checklist_desc
Revises: a1b2c3d4e5f6
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision = "f1x_checklist_desc"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if column already exists before adding
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("task_checklists")]
    if "description" not in columns:
        op.add_column("task_checklists", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("task_checklists", "description")
