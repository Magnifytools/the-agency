"""A deployment must preserve business data and reject incomplete schema."""
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Client, Project, Task, User, UserRole
from backend.startup.readiness import check_database_ready


async def test_readiness_checks_real_schema(engine):
    await check_database_ready(engine)


async def test_release_step_adds_owner_before_readonly_web_startup(engine, monkeypatch):
    import backend.main as main
    import backend.db.database as database
    from backend.startup.project_schema import ensure_project_owner_schema
    from backend.startup.schema_baseline import migrate_schema

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(main, "_ensure_pg_enums", AsyncMock())
    monkeypatch.setattr(main, "_ensure_enum_values", AsyncMock())
    monkeypatch.setattr(main, "start_background_tasks", lambda: [])
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE projects DROP COLUMN owner_id CASCADE"))
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS agency_schema_versions"))
    await migrate_schema(engine)
    lifecycle = main.lifespan(main.app)
    try:
        await lifecycle.__anext__()
        await check_database_ready(engine)
        # Repeated starts must be safe and must not assign anyone.
        await ensure_project_owner_schema(engine)
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM projects WHERE owner_id IS NOT NULL")) == 0
    finally:
        await lifecycle.aclose()
        await ensure_project_owner_schema(engine)


async def test_readiness_rejects_missing_project_owner_column(engine):
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE projects RENAME COLUMN owner_id TO owner_id_missing"))
    try:
        with pytest.raises(Exception, match="owner_id"):
            await check_database_ready(engine)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE projects RENAME COLUMN owner_id_missing TO owner_id"))


async def test_readiness_accepts_equivalent_legacy_index_name(engine):
    async with engine.begin() as conn:
        await conn.execute(text("ALTER INDEX uq_time_entries_active_timer RENAME TO uq_one_active_timer"))
    try:
        await check_database_ready(engine)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER INDEX uq_one_active_timer RENAME TO uq_time_entries_active_timer"))


async def test_readiness_rejects_wrong_columns_under_expected_index_name(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DROP INDEX uq_notifications_user_dedupe"))
        await conn.execute(text("CREATE UNIQUE INDEX uq_notifications_user_dedupe ON notifications (id)"))
    try:
        with pytest.raises(RuntimeError, match="Required unique index"):
            await check_database_ready(engine)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DROP INDEX uq_notifications_user_dedupe"))
            await conn.execute(text("CREATE UNIQUE INDEX uq_notifications_user_dedupe ON notifications (user_id,dedupe_key)"))


async def test_web_startup_preserves_business_rows(engine, monkeypatch):
    import backend.main as main
    import backend.db.database as database

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(main, "_ensure_pg_enums", AsyncMock())
    monkeypatch.setattr(main, "_ensure_enum_values", AsyncMock())
    monkeypatch.setattr(main, "start_background_tasks", lambda: [])
    password_reset = AsyncMock()
    monkeypatch.setattr(main, "_reset_admin_password", password_reset)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = User(email="david@example.com", full_name="QA David", hashed_password="preserve", role=UserRole.admin, cost_per_hour=0)
        fit = Client(name="Fit Generation")
        sage = Client(name="Sage")
        qa = Client(name="QA Agency")
        session.add_all([user, fit, sage, qa])
        await session.flush()
        project = Project(name="Fit SEO", client_id=fit.id, monthly_fee=0)
        task = Task(title="QA Task preserve", assigned_to=user.id, client_id=qa.id)
        session.add_all([project, task])
        await session.commit()
        ids = (user.id, fit.id, sage.id, qa.id, project.id, task.id)
    try:
        from backend.startup.schema_baseline import migrate_schema
        await migrate_schema(engine)
        for _ in range(2):
            lifecycle = main.lifespan(main.app)
            await anext(lifecycle)
            await lifecycle.aclose()
        password_reset.assert_not_awaited()
        async with engine.connect() as conn:
            row = (await conn.execute(text("SELECT cost_per_hour, hashed_password FROM users WHERE id=:id"), {"id": ids[0]})).one()
            assert row == (0, "preserve")
            assert await conn.scalar(text("SELECT monthly_fee FROM projects WHERE id=:id"), {"id": ids[4]}) == 0
            assert await conn.scalar(text("SELECT vat_treatment::text FROM clients WHERE id=:id"), {"id": ids[1]}) == "domestic_21"
            assert await conn.scalar(text("SELECT count(*) FROM projects WHERE client_id=:id"), {"id": ids[2]}) == 0
            assert await conn.scalar(text("SELECT assigned_to FROM tasks WHERE id=:id"), {"id": ids[5]}) == ids[0]
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tasks WHERE id=:id"), {"id": ids[5]})
            await conn.execute(text("DELETE FROM projects WHERE id=:id"), {"id": ids[4]})
            await conn.execute(text("DELETE FROM clients WHERE id IN (:a,:b,:c)"), dict(zip(("a","b","c"), ids[1:4])))
            await conn.execute(text("DELETE FROM users WHERE id=:id"), {"id": ids[0]})


async def test_readiness_requires_atomic_journal_schema(engine):
    from sqlalchemy.exc import DBAPIError
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE change_logs RENAME COLUMN operations TO operations_unavailable"))
    try:
        with pytest.raises(DBAPIError):
            await check_database_ready(engine)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE change_logs RENAME COLUMN operations_unavailable TO operations"))


async def test_web_refuses_unversioned_schema_without_ddl_or_jobs(engine, monkeypatch):
    import backend.main as main
    import backend.db.database as database
    from unittest.mock import Mock

    monkeypatch.setattr(database, "engine", engine)
    jobs = Mock(return_value=[])
    monkeypatch.setattr(main, "start_background_tasks", jobs)
    async with engine.begin() as conn:
        exists = await conn.scalar(text("SELECT to_regclass('agency_schema_versions')"))
        if exists:
            await conn.execute(text("ALTER TABLE agency_schema_versions RENAME TO schema_versions_test_backup"))
    try:
        lifecycle = main.lifespan(main.app)
        with pytest.raises(Exception, match="agency_schema_versions"):
            await anext(lifecycle)
        await lifecycle.aclose()
        jobs.assert_not_called()
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT to_regclass('agency_schema_versions')")) is None
    finally:
        if exists:
            async with engine.begin() as conn:
                await conn.execute(text("ALTER TABLE schema_versions_test_backup RENAME TO agency_schema_versions"))
