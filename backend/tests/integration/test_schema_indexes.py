"""Semantic PostgreSQL checks for the frozen unique-index contract."""

import pytest
from sqlalchemy import text

from backend.startup.schema_indexes import check_unique_indexes

USERS_EMAIL = ({"table": "users", "columns": ["email"], "predicate": ""},)
TASK_OCCURRENCE = ({
    "table": "tasks",
    "columns": ["recurring_parent_id", "recurrence_occurrence_date"],
    "predicate": "(recurring_parent_id IS NOT NULL)",
},)
HOLIDAYS = ({
    "table": "company_holidays",
    "columns": ["date", "region", "locality"],
    "predicate": "",
},)


async def test_missing_users_email_unique_is_rejected_without_repair(engine):
    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            await conn.execute(text("DROP INDEX ix_users_email"))
            with pytest.raises(RuntimeError, match=r"users\(email\)"):
                await check_unique_indexes(conn, USERS_EMAIL)
            assert await conn.scalar(text(
                "SELECT to_regclass('public.ix_users_email') IS NULL"
            )) is True
        finally:
            await transaction.rollback()


async def test_equivalent_renamed_unique_index_is_accepted(engine):
    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            await conn.execute(text("DROP INDEX ix_users_email"))
            await conn.execute(text(
                "CREATE UNIQUE INDEX equivalent_email_unique ON users(email) INCLUDE(id)"
            ))
            await check_unique_indexes(conn, USERS_EMAIL)
        finally:
            await transaction.rollback()


async def test_wrong_partial_predicate_is_rejected(engine):
    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            await conn.execute(text("DROP INDEX uq_task_recurring_occurrence"))
            await conn.execute(text("""CREATE UNIQUE INDEX wrong_task_occurrence
                ON tasks(recurring_parent_id, recurrence_occurrence_date)
                WHERE recurrence_occurrence_date IS NOT NULL"""))
            with pytest.raises(RuntimeError, match="tasks"):
                await check_unique_indexes(conn, TASK_OCCURRENCE)
        finally:
            await transaction.rollback()


async def test_company_holiday_legacy_coalesce_expression_is_accepted(engine):
    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            await conn.execute(text(
                "ALTER TABLE company_holidays DROP CONSTRAINT uq_holiday_date_region_locality"
            ))
            await conn.execute(text("""CREATE UNIQUE INDEX renamed_holiday_scope
                ON company_holidays(
                    date,
                    COALESCE(region, ''::character varying),
                    COALESCE(locality, ''::character varying)
                )"""))
            await check_unique_indexes(conn, HOLIDAYS)
        finally:
            await transaction.rollback()
