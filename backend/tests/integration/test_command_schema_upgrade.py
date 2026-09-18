"""Real command DDL, isolated from the model-created schema used by API tests."""
import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from backend.startup.command_schema import ensure_command_schema


async def test_command_upgrade_concurrent_idempotent_and_preserves_receipts(engine):
    schema = "command_upgrade_" + uuid4().hex
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = create_async_engine(engine.url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with isolated.begin() as conn:
            await conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
            await conn.execute(text("CREATE TABLE change_logs (id INTEGER PRIMARY KEY)"))
            await conn.execute(text("INSERT INTO users VALUES (1), (2)"))
            await conn.execute(text("INSERT INTO change_logs VALUES (7)"))
        await asyncio.gather(*(ensure_command_schema(isolated) for _ in range(3)))
        async with isolated.begin() as conn:
            await conn.execute(text("""INSERT INTO command_receipts
                (id,user_id,request_key,request_hash,channel,raw_text,status,result,change_log_id)
                VALUES ('a',1,'same-key','hash','app','Synthetic request','executed',
                        '{"message":"Saved"}',7)"""))
        await ensure_command_schema(isolated)
        async with isolated.begin() as conn:
            row = (await conn.execute(text("SELECT result,revision,step_replays,change_log_id FROM command_receipts WHERE id='a'"))).one()
            assert row == ({"message": "Saved"}, 1, {}, 7)
            # A request key belongs to one actor, not the whole installation.
            await conn.execute(text("""INSERT INTO command_receipts
                (id,user_id,request_key,request_hash,channel,raw_text,status)
                VALUES ('b',2,'same-key','hash','app','Synthetic request','executed')"""))
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(text("""INSERT INTO command_receipts
                        (id,user_id,request_key,request_hash,channel,raw_text,status)
                        VALUES ('c',1,'same-key','hash','app','Duplicate','executed')"""))
            await conn.execute(text("DELETE FROM change_logs WHERE id=7"))
            assert await conn.scalar(text("SELECT change_log_id FROM command_receipts WHERE id='a'")) is None
            assert await conn.scalar(text("SELECT count(*) FROM command_receipts")) == 2
    finally:
        await isolated.dispose()
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
