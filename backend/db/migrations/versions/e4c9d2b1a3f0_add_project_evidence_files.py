"""add file support to project evidence

Revision ID: e4c9d2b1a3f0
Revises: f1x_checklist_desc, b2c3d4e5f6a7
Create Date: 2026-03-12 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


# revision identifiers, used by Alembic.
revision: str = "e4c9d2b1a3f0"
down_revision: Union[str, Sequence[str], None] = ("f1x_checklist_desc", "b2c3d4e5f6a7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    columns = {col["name"]: col for col in inspector.get_columns("project_evidence")}

    with op.batch_alter_table("project_evidence") as batch_op:
        if "file_name" not in columns:
            batch_op.add_column(sa.Column("file_name", sa.String(length=255), nullable=True))
        if "file_mime_type" not in columns:
            batch_op.add_column(sa.Column("file_mime_type", sa.String(length=100), nullable=True))
        if "file_size_bytes" not in columns:
            batch_op.add_column(sa.Column("file_size_bytes", sa.Integer(), nullable=True))
        if "file_content" not in columns:
            batch_op.add_column(sa.Column("file_content", sa.LargeBinary(), nullable=True))
        url_column = columns.get("url")
        if url_column and not url_column.get("nullable", False):
            batch_op.alter_column("url", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    columns = {col["name"]: col for col in inspector.get_columns("project_evidence")}

    if columns.get("url", {}).get("nullable", True):
        op.execute("UPDATE project_evidence SET url = '' WHERE url IS NULL")
        with op.batch_alter_table("project_evidence") as batch_op:
            batch_op.alter_column("url", existing_type=sa.Text(), nullable=False)

    with op.batch_alter_table("project_evidence") as batch_op:
        if "file_content" in columns:
            batch_op.drop_column("file_content")
        if "file_size_bytes" in columns:
            batch_op.drop_column("file_size_bytes")
        if "file_mime_type" in columns:
            batch_op.drop_column("file_mime_type")
        if "file_name" in columns:
            batch_op.drop_column("file_name")
