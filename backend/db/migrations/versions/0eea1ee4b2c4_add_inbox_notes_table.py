"""add inbox_notes table

Revision ID: 0eea1ee4b2c4
Revises: ad7ddd307f60
Create Date: 2026-03-04 18:16:00.770184

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0eea1ee4b2c4'
down_revision: Union[str, None] = 'ad7ddd307f60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('inbox_notes',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('raw_text', sa.Text(), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('status', sa.Enum('pending', 'classified', 'processed', 'dismissed', name='inboxnotestatus'), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=True),
    sa.Column('client_id', sa.Integer(), nullable=True),
    sa.Column('resolved_as', sa.String(length=20), nullable=True),
    sa.Column('resolved_entity_id', sa.Integer(), nullable=True),
    sa.Column('ai_suggestion', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_inbox_notes_client_id'), 'inbox_notes', ['client_id'], unique=False)
    op.create_index(op.f('ix_inbox_notes_project_id'), 'inbox_notes', ['project_id'], unique=False)
    op.create_index(op.f('ix_inbox_notes_user_id'), 'inbox_notes', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_inbox_notes_user_id'), table_name='inbox_notes')
    op.drop_index(op.f('ix_inbox_notes_project_id'), table_name='inbox_notes')
    op.drop_index(op.f('ix_inbox_notes_client_id'), table_name='inbox_notes')
    op.drop_table('inbox_notes')
    op.execute("DROP TYPE IF EXISTS inboxnotestatus")
