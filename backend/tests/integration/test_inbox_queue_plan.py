"""The Inbox recovery poll must not rescan historical notes every 30 seconds."""
import json

from sqlalchemy import func, text
from sqlalchemy.dialects import postgresql

from backend.services.inbox_processing import CLASSIFICATION_BATCH_SIZE, pending_batch_query


def _nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from _nodes(child)


async def test_pending_queue_is_bounded_and_uses_partial_attempt_index(
    db_session, admin_user,
):
    await db_session.execute(text("""
        INSERT INTO inbox_notes
            (user_id, raw_text, source, status, created_at, updated_at)
        SELECT :user_id, 'historical-' || g, 'dashboard',
               'processed'::inboxnotestatus,
               clock_timestamp() - interval '60 days',
               clock_timestamp() - interval '30 days'
        FROM generate_series(1, 50000) AS g
    """), {"user_id": admin_user.id})
    await db_session.execute(text("""
        INSERT INTO inbox_notes
            (user_id, raw_text, source, status, classification_next_attempt_at,
             created_at, updated_at)
        SELECT :user_id, 'due-' || g, 'dashboard', 'pending'::inboxnotestatus,
               CASE WHEN g <= 7 THEN NULL
                    ELSE timezone('UTC', clock_timestamp()) + interval '1 hour' END,
               timezone('UTC', clock_timestamp()) - interval '1 day',
               timezone('UTC', clock_timestamp()) - (g || ' minutes')::interval
        FROM generate_series(1, 12) AS g
    """), {"user_id": admin_user.id})
    await db_session.execute(text("ANALYZE inbox_notes"))

    query = pending_batch_query(func.timezone("UTC", func.clock_timestamp()))
    ids = (await db_session.execute(query)).scalars().all()
    assert len(ids) == CLASSIFICATION_BATCH_SIZE

    compiled = query.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    )
    raw_plan = await db_session.scalar(text(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + str(compiled)
    ))
    plan_doc = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
    nodes = list(_nodes(plan_doc[0]["Plan"]))

    assert any(
        node.get("Index Name") == "ix_inbox_pending_attempt"
        for node in nodes
    ), plan_doc
    assert not any(
        node.get("Node Type") == "Seq Scan"
        and node.get("Relation Name") == "inbox_notes"
        for node in nodes
    ), plan_doc
