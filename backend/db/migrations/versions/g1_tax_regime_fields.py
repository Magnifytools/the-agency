"""Add tax_regime and IRPF withholding fields to income and expenses

Revision ID: g1_tax_regime
Revises: f1x_checklist_description_col
Create Date: 2026-03-15
"""
from alembic import op
import sqlalchemy as sa

revision = "g1_tax_regime"
down_revision = None  # standalone migration, applies additively
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Income: tax regime + IRPF withholding
    op.add_column("income", sa.Column("tax_regime", sa.String(50), nullable=False, server_default="standard"))
    op.add_column("income", sa.Column("irpf_withholding_rate", sa.Numeric(5, 2), nullable=False, server_default="0"))
    op.add_column("income", sa.Column("irpf_withholding_amount", sa.Numeric(12, 2), nullable=False, server_default="0"))

    # Expenses: tax regime + IRPF withholding
    op.add_column("expenses", sa.Column("tax_regime", sa.String(50), nullable=False, server_default="standard"))
    op.add_column("expenses", sa.Column("irpf_withholding_rate", sa.Numeric(5, 2), nullable=False, server_default="0"))
    op.add_column("expenses", sa.Column("irpf_withholding_amount", sa.Numeric(12, 2), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("income", "tax_regime")
    op.drop_column("income", "irpf_withholding_rate")
    op.drop_column("income", "irpf_withholding_amount")
    op.drop_column("expenses", "tax_regime")
    op.drop_column("expenses", "irpf_withholding_rate")
    op.drop_column("expenses", "irpf_withholding_amount")
