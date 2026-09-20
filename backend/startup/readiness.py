"""Read-only deployment readiness: database connectivity and required schema."""
import asyncio

from sqlalchemy import text


async def check_database_ready(engine) -> None:
    async def probe():
        async with engine.connect() as conn:
            # LIMIT 0 verifies the actual schema without reading business data.
            await conn.execute(text("SELECT completed_at FROM tasks LIMIT 0"))
            await conn.execute(text("SELECT dedupe_key, incident_state, incident_severity, incident_revision, incident_detected_at, incident_fingerprint, incident_snoozed_until, incident_resolved_at, incident_resolution_reason, incident_dismissal_reason, entity_key FROM notifications LIMIT 0"))
            await conn.execute(text("SELECT paused_at, accumulated_seconds FROM time_entries LIMIT 0"))
            await conn.execute(text("SELECT id, user_id, entity_type, entity_id, action, label, operations, undone_at, undone_by, created_at, updated_at FROM change_logs LIMIT 0"))
            await conn.execute(text("SELECT id, user_id, request_key, request_hash, channel, context, raw_text, status, intent, prompt, result, change_log_id, error_code, error_detail, revision, step_replays, created_at, updated_at FROM command_receipts LIMIT 0"))
            await conn.execute(text("SELECT owner_id FROM projects LIMIT 0"))
            owner_fk = await conn.scalar(text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_constraint c
                    JOIN pg_attribute a
                      ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
                    WHERE c.conrelid = 'projects'::regclass
                      AND c.contype = 'f'
                      AND c.confrelid = 'users'::regclass
                      AND a.attname = 'owner_id'
                )
            """))
            if owner_fk is not True:
                raise RuntimeError("Required project owner foreign key is missing")
            await conn.execute(text("SELECT id, request_key, owner_id, kind, scope, period_start, period_end, title, content, destination_kind, created_at, updated_at FROM communication_requests LIMIT 0"))
            await conn.execute(text("SELECT id, dedupe_key, actor_id, source_kind, source_id, source_version, destination_key, payload, status, available_at, expires_at, sent_at, error_code, message, resend_of, created_at, updated_at FROM deliveries LIMIT 0"))
            await conn.execute(text("SELECT id, delivery_id, number, steps, lease_until, status, created_at, updated_at FROM delivery_attempts LIMIT 0"))
            await conn.execute(text("SELECT google_calendar_synced_at FROM users LIMIT 0"))
            await conn.execute(text("SELECT source_calendar_id FROM events LIMIT 0"))
            await conn.execute(text("SELECT client_id, enabled, cadence, responsible_user_id, revision, created_at, updated_at FROM client_report_policies LIMIT 0"))
            await conn.execute(text("SELECT revision, source_facts FROM daily_updates LIMIT 0"))
            await conn.execute(text("SELECT id, digest_id, action, actor_id, request_key, request_hash, created_at FROM digest_external_delivery_events LIMIT 0"))
            await conn.execute(text("SELECT policy_key, destination_id, kind, approved_by, recipient_id, enabled, channels, time, minutes_before, quiet_start, quiet_end, revision, effective_from FROM communication_schedules LIMIT 0"))
            await conn.execute(text("SELECT occurrence_key, schedule_id, recipient_id, kind, channel, period_start, period_end, event_id, event_start, due_at, expires_at, state, reason, request_id, notification_id FROM communication_occurrences LIMIT 0"))
            # These source types enforce financial visibility in persisted PM
            # insights; do not serve a revision whose enum upgrade was skipped.
            await conn.execute(text("SELECT 'financial'::insighttype, 'operational_suggestion'::insighttype"))
            # Production's legacy timer index has a different name. Validate
            # semantics, so an equivalent index passes and a wrongly named one
            # with different keys cannot falsely certify the schema.
            for table, columns, predicate in (
                ("notifications", ["user_id", "dedupe_key"], ""),
                ("daily_updates", ["user_id", "date"], ""),
                ("time_entries", ["user_id"], "(minutes IS NULL)"),
                ("deliveries", ["dedupe_key"], ""),
                ("communication_requests", ["request_key"], ""),
                ("communication_schedules", ["policy_key"], ""),
                ("events", ["user_id", "source_calendar_id", "google_event_id"], ""),
                ("communication_occurrences", ["occurrence_key"], ""),
                ("communication_occurrences", ["request_id"], ""),
                ("communication_occurrences", ["notification_id"], ""),
                ("delivery_attempts", ["delivery_id", "number"], ""),
                ("command_receipts", ["user_id", "request_key"], ""),
                ("digest_external_delivery_events", ["actor_id", "request_key"], ""),
            ):
                valid = await conn.scalar(text("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_index i
                        WHERE i.indrelid = to_regclass(:table)
                          AND i.indisvalid AND i.indisunique
                          AND i.indnkeyatts = cardinality(CAST(:columns AS text[]))
                          AND ARRAY(
                            SELECT a.attname::text
                            FROM unnest(i.indkey::smallint[]) WITH ORDINALITY k(attnum, position)
                            JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
                            WHERE k.position <= i.indnkeyatts ORDER BY k.position
                          ) = CAST(:columns AS text[])
                          AND coalesce(pg_get_expr(i.indpred, i.indrelid), '') = :predicate
                    )
                """), {"table": table, "columns": columns, "predicate": predicate})
                if valid is not True:
                    raise RuntimeError("Required unique index is missing or invalid")
    await asyncio.wait_for(probe(), timeout=5)
