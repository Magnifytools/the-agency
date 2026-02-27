"""Move startup DDL to Alembic.

Revision ID: b7f3c2c61d1a
Revises: c5ed1dc5fc22
Create Date: 2026-02-27 22:10:00
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b7f3c2c61d1a"
down_revision: Union[str, None] = "c5ed1dc5fc22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DDL_STATEMENTS = [
    # Enum types used by newer features.
    (
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'digeststatus') THEN "
        "CREATE TYPE digeststatus AS ENUM ('draft', 'reviewed', 'sent'); "
        "END IF; "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'digesttone') THEN "
        "CREATE TYPE digesttone AS ENUM ('formal', 'cercano', 'equipo'); "
        "END IF; "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'leadstatus') THEN "
        "CREATE TYPE leadstatus AS ENUM ('new', 'contacted', 'discovery', 'proposal', 'negotiation', 'won', 'lost'); "
        "END IF; "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'leadsource') THEN "
        "CREATE TYPE leadsource AS ENUM ('website', 'referral', 'linkedin', 'conference', 'cold_outreach', 'other'); "
        "END IF; "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'leadactivitytype') THEN "
        "CREATE TYPE leadactivitytype AS ENUM ('note', 'email_sent', 'email_received', 'call', 'meeting', 'proposal_sent', 'status_change', 'followup_set'); "
        "END IF; "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'servicetype') THEN "
        "CREATE TYPE servicetype AS ENUM ('seo_sprint', 'migration', 'market_study', 'consulting_retainer', 'partnership_retainer', 'brand_audit', 'custom'); "
        "END IF; "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'dailyupdatestatus') THEN "
        "CREATE TYPE dailyupdatestatus AS ENUM ('draft', 'sent'); "
        "END IF; "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'resourcetype') THEN "
        "CREATE TYPE resourcetype AS ENUM ('spreadsheet', 'document', 'email', 'account', 'dashboard', 'other'); "
        "END IF; "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'billingcycle') THEN "
        "CREATE TYPE billingcycle AS ENUM ('monthly', 'bimonthly', 'quarterly', 'annual', 'one_time'); "
        "END IF; "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'billingeventtype') THEN "
        "CREATE TYPE billingeventtype AS ENUM ('invoice_sent', 'payment_received', 'reminder_sent', 'note'); "
        "END IF; "
        "END $$;"
    ),
    "ALTER TABLE IF EXISTS tasks ADD COLUMN IF NOT EXISTS priority VARCHAR(10) NOT NULL DEFAULT 'medium'",
    "ALTER TABLE IF EXISTS tasks ADD COLUMN IF NOT EXISTS start_date TIMESTAMP",
    "ALTER TABLE IF EXISTS clients ADD COLUMN IF NOT EXISTS holded_contact_id VARCHAR(100)",
    "ALTER TABLE IF EXISTS clients ADD COLUMN IF NOT EXISTS vat_number VARCHAR(50)",
    "ALTER TABLE IF EXISTS clients ADD COLUMN IF NOT EXISTS ga4_property_id VARCHAR(50)",
    "ALTER TABLE IF EXISTS clients ADD COLUMN IF NOT EXISTS gsc_url VARCHAR(255)",
    "ALTER TABLE IF EXISTS clients ADD COLUMN IF NOT EXISTS billing_cycle billingcycle",
    "ALTER TABLE IF EXISTS clients ADD COLUMN IF NOT EXISTS billing_day INTEGER",
    "ALTER TABLE IF EXISTS clients ADD COLUMN IF NOT EXISTS next_invoice_date DATE",
    "ALTER TABLE IF EXISTS clients ADD COLUMN IF NOT EXISTS last_invoiced_date DATE",
    (
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='proposals' AND column_name='client_id') THEN "
        "ALTER TABLE proposals ALTER COLUMN client_id DROP NOT NULL; "
        "END IF; "
        "END $$;"
    ),
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS lead_id INTEGER REFERENCES leads(id)",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id)",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS contact_name VARCHAR(200)",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS company_name VARCHAR(200) NOT NULL DEFAULT ''",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS service_type servicetype",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS situation TEXT",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS problem TEXT",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS cost_of_inaction TEXT",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS opportunity TEXT",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS approach TEXT",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS relevant_cases TEXT",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS pricing_options JSONB",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS internal_hours_david NUMERIC(10,1)",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS internal_hours_nacho NUMERIC(10,1)",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS internal_cost_estimate NUMERIC(10,2)",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS estimated_margin_percent NUMERIC(5,2)",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS generated_content JSONB",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS sent_at TIMESTAMP",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS responded_at TIMESTAMP",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS response_notes TEXT",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS valid_until DATE",
    "ALTER TABLE IF EXISTS proposals ADD COLUMN IF NOT EXISTS converted_project_id INTEGER REFERENCES projects(id)",
    "ALTER TABLE IF EXISTS communication_logs ADD COLUMN IF NOT EXISTS contact_id INTEGER REFERENCES client_contacts(id)",
    "ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS weekly_hours FLOAT NOT NULL DEFAULT 40.0",
    "ALTER TABLE IF EXISTS client_contacts ADD COLUMN IF NOT EXISTS department VARCHAR(100)",
    "ALTER TABLE IF EXISTS client_contacts ADD COLUMN IF NOT EXISTS preferred_channel VARCHAR(50)",
    "ALTER TABLE IF EXISTS client_contacts ADD COLUMN IF NOT EXISTS language VARCHAR(50)",
    "ALTER TABLE IF EXISTS client_contacts ADD COLUMN IF NOT EXISTS linkedin_url VARCHAR(300)",
    (
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'proposalstatus') THEN "
        "BEGIN ALTER TYPE proposalstatus ADD VALUE IF NOT EXISTS 'expired'; EXCEPTION WHEN OTHERS THEN NULL; END; "
        "END IF; "
        "END $$;"
    ),
]


def upgrade() -> None:
    for statement in DDL_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    # No destructive downgrade: this migration consolidates historically
    # idempotent startup DDL into Alembic ownership.
    pass
