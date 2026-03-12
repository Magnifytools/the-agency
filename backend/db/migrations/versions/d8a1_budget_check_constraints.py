"""Add check constraints for non-negative budgets

Revision ID: d8a1_budget_check
Revises: (manual)
"""

from alembic import op


revision = "d8a1_budget_check"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # First clean any existing negative values (set to 0)
    op.execute("UPDATE clients SET monthly_budget = 0 WHERE monthly_budget < 0")
    op.execute("UPDATE projects SET budget_amount = 0 WHERE budget_amount < 0")
    op.execute("UPDATE projects SET budget_hours = 0 WHERE budget_hours < 0")

    # Add constraints
    op.create_check_constraint(
        "ck_client_monthly_budget_positive", "clients", "monthly_budget >= 0"
    )
    op.create_check_constraint(
        "ck_project_budget_amount_positive", "projects", "budget_amount >= 0"
    )
    op.create_check_constraint(
        "ck_project_budget_hours_positive", "projects", "budget_hours >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_client_monthly_budget_positive", "clients")
    op.drop_constraint("ck_project_budget_amount_positive", "projects")
    op.drop_constraint("ck_project_budget_hours_positive", "projects")
