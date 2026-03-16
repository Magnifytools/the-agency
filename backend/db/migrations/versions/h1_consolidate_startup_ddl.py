"""Consolidate startup DDL (v2-v10) into Alembic.

All statements are idempotent (IF NOT EXISTS / IF EXISTS).
After this migration, the _ensure_columns_v2..v10 functions in main.py
become no-ops and can be safely removed.

Revision ID: h1_consolidate
Revises: None
Create Date: 2026-03-16
"""
from alembic import op

revision = "h1_consolidate"
down_revision = None  # standalone, additive
branch_labels = None
depends_on = None


DDL = [
    # ── v2: task fields, comments, attachments ──
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_created_by ON tasks (created_by)",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS scheduled_date DATE",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS waiting_for VARCHAR(255)",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS follow_up_date DATE",
    "DO $$ BEGIN ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'backlog'; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
    "DO $$ BEGIN ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'waiting'; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
    "DO $$ BEGIN ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'in_review'; EXCEPTION WHEN duplicate_object THEN NULL; END $$",
    """CREATE TABLE IF NOT EXISTS task_comments (
        id SERIAL PRIMARY KEY,
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id),
        text TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_task_comments_task_id ON task_comments (task_id)",
    """CREATE TABLE IF NOT EXISTS task_attachments (
        id SERIAL PRIMARY KEY,
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        mime_type VARCHAR(100) NOT NULL DEFAULT 'application/octet-stream',
        size_bytes INTEGER NOT NULL,
        content BYTEA NOT NULL,
        uploaded_by INTEGER REFERENCES users(id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_task_attachments_task_id ON task_attachments (task_id)",
    "ALTER TABLE monthly_closes ADD COLUMN IF NOT EXISTS reviewed_holded BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE task_checklists ADD COLUMN IF NOT EXISTS assigned_to INTEGER REFERENCES users(id)",
    "ALTER TABLE task_checklists ADD COLUMN IF NOT EXISTS due_date DATE",

    # ── v3: recurring tasks, news sources, discord bot ──
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS is_recurring BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence_pattern VARCHAR(20)",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence_day INTEGER",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence_end_date DATE",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurring_parent_id INTEGER REFERENCES tasks(id)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_recurring_parent_id ON tasks (recurring_parent_id)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_is_recurring ON tasks (is_recurring)",
    "ALTER TABLE tasks ALTER COLUMN client_id DROP NOT NULL",
    """CREATE TABLE IF NOT EXISTS news_sources (
        id SERIAL PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        url VARCHAR(500) NOT NULL,
        category VARCHAR(100),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "ALTER TABLE discord_settings ADD COLUMN IF NOT EXISTS bot_token VARCHAR(500)",
    "ALTER TABLE discord_settings ADD COLUMN IF NOT EXISTS channel_id VARCHAR(50)",

    # ── v4: tax regime + IRPF ──
    "ALTER TABLE income ADD COLUMN IF NOT EXISTS tax_regime VARCHAR(50) NOT NULL DEFAULT 'standard'",
    "ALTER TABLE income ADD COLUMN IF NOT EXISTS irpf_withholding_rate NUMERIC(5,2) NOT NULL DEFAULT 0",
    "ALTER TABLE income ADD COLUMN IF NOT EXISTS irpf_withholding_amount NUMERIC(12,2) NOT NULL DEFAULT 0",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS tax_regime VARCHAR(50) NOT NULL DEFAULT 'standard'",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS irpf_withholding_rate NUMERIC(5,2) NOT NULL DEFAULT 0",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS irpf_withholding_amount NUMERIC(12,2) NOT NULL DEFAULT 0",

    # ── v5: project pricing + client intermediary ──
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS pricing_model VARCHAR(20)",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS unit_price NUMERIC(12,2)",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS unit_label VARCHAR(50)",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS scope TEXT",
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS intermediary_name VARCHAR(200)",
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_intermediary_deal BOOLEAN NOT NULL DEFAULT false",

    # ── v6: my week (day statuses + holidays) ──
    """CREATE TABLE IF NOT EXISTS user_day_statuses (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        date DATE NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'available',
        label VARCHAR(100),
        note TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
        UNIQUE(user_id, date)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_user_day_statuses_user_id ON user_day_statuses(user_id)",
    "CREATE INDEX IF NOT EXISTS ix_user_day_statuses_date ON user_day_statuses(date)",
    """CREATE TABLE IF NOT EXISTS company_holidays (
        id SERIAL PRIMARY KEY,
        date DATE NOT NULL,
        name VARCHAR(100) NOT NULL,
        country VARCHAR(5) NOT NULL DEFAULT 'ES',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )""",

    # ── v7: project monthly fee ──
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS monthly_fee NUMERIC(12,2)",

    # ── v8: project templates ──
    """CREATE TABLE IF NOT EXISTS project_templates (
        id SERIAL PRIMARY KEY,
        key VARCHAR(50) NOT NULL UNIQUE,
        name VARCHAR(200) NOT NULL,
        description TEXT,
        project_type VARCHAR(50),
        is_recurring BOOLEAN NOT NULL DEFAULT FALSE,
        phases JSON NOT NULL DEFAULT '[]',
        default_tasks JSON NOT NULL DEFAULT '[]',
        pricing_model VARCHAR(20),
        monthly_fee NUMERIC(12,2),
        created_by INTEGER REFERENCES users(id),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )""",

    # ── v9: automation rules + logs ──
    """CREATE TABLE IF NOT EXISTS automation_rules (
        id SERIAL PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        description TEXT,
        trigger VARCHAR(50) NOT NULL,
        conditions JSON NOT NULL DEFAULT '{}',
        action_type VARCHAR(50) NOT NULL,
        action_config JSON NOT NULL DEFAULT '{}',
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        run_count INTEGER NOT NULL DEFAULT 0,
        last_run_at TIMESTAMP,
        created_by INTEGER REFERENCES users(id),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS automation_logs (
        id SERIAL PRIMARY KEY,
        rule_id INTEGER NOT NULL REFERENCES automation_rules(id) ON DELETE CASCADE,
        trigger_event VARCHAR(50) NOT NULL,
        trigger_data JSON,
        action_result JSON,
        success BOOLEAN NOT NULL DEFAULT TRUE,
        error_message TEXT,
        executed_at TIMESTAMP NOT NULL DEFAULT NOW(),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_automation_rules_trigger ON automation_rules(trigger)",

    # ── v10: region/locality on users + holidays ──
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS region VARCHAR(10)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS locality VARCHAR(100)",
    "ALTER TABLE company_holidays ADD COLUMN IF NOT EXISTS region VARCHAR(10)",
    "ALTER TABLE company_holidays ADD COLUMN IF NOT EXISTS locality VARCHAR(100)",
    "ALTER TABLE company_holidays DROP CONSTRAINT IF EXISTS company_holidays_date_key",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_holiday_date_region_locality ON company_holidays(date, COALESCE(region, ''), COALESCE(locality, ''))",
]


def upgrade() -> None:
    for stmt in DDL:
        op.execute(stmt)


def downgrade() -> None:
    pass  # Idempotent DDL, no destructive downgrade
