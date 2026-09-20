"""Daily startup never discards historical drafts to enforce uniqueness."""
import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from backend.startup.daily_schema import ensure_daily_schema


@pytest.mark.parametrize("duplicates", [False, True])
async def test_daily_upgrade_preserves_every_raw_text(engine, duplicates):
    schema = "daily_upgrade_" + uuid4().hex
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = create_async_engine(engine.url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with isolated.begin() as conn:
            await conn.execute(text("CREATE TABLE daily_updates (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, date DATE NOT NULL, raw_text TEXT NOT NULL)"))
            await conn.execute(text("INSERT INTO daily_updates VALUES (1, 7, '2026-09-10', 'Original')"))
            if duplicates:
                await conn.execute(text("INSERT INTO daily_updates VALUES (2, 7, '2026-09-10', 'Otra versión histórica')"))
        if duplicates:
            with pytest.raises(IntegrityError):
                await ensure_daily_schema(isolated)
            async with isolated.connect() as conn:
                rows = (await conn.execute(text("SELECT raw_text FROM daily_updates ORDER BY id"))).scalars().all()
                assert rows == ["Original", "Otra versión histórica"]
        else:
            await asyncio.gather(ensure_daily_schema(isolated), ensure_daily_schema(isolated))
            async with isolated.begin() as conn:
                row = (await conn.execute(text("SELECT raw_text, revision, source_facts FROM daily_updates"))).one()
                assert row == ("Original", 1, [])
                with pytest.raises(IntegrityError):
                    async with conn.begin_nested():
                        await conn.execute(text("INSERT INTO daily_updates(id,user_id,date,raw_text) VALUES (2,7,'2026-09-10','Duplicate')"))
                await conn.execute(text("INSERT INTO daily_updates(id,user_id,date,raw_text) VALUES (3,8,'2026-09-10','Other actor')"))
            await ensure_daily_schema(isolated)
            async with isolated.connect() as conn:
                assert await conn.scalar(text("SELECT count(*) FROM daily_updates")) == 2
    finally:
        await isolated.dispose()
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
