"""Add per-task billing fields and onboarding intelligence.

Revision ID: c1d2e3f4g5h6
Revises: ad7ddd307f60
Create Date: 2026-03-19
"""
from alembic import op

revision = "c1d2e3f4g5h6"
down_revision = "ad7ddd307f60"
branch_labels = None
depends_on = None

DDL_UP = [
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS unit_cost NUMERIC(12,2)",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS invoiced_at TIMESTAMPTZ",
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS onboarding_intelligence JSONB",
]

DDL_DOWN = [
    "ALTER TABLE tasks DROP COLUMN IF EXISTS unit_cost",
    "ALTER TABLE tasks DROP COLUMN IF EXISTS invoiced_at",
    "ALTER TABLE clients DROP COLUMN IF EXISTS onboarding_intelligence",
]


def upgrade():
    for sql in DDL_UP:
        op.execute(sql)


def downgrade():
    for sql in DDL_DOWN:
        op.execute(sql)
