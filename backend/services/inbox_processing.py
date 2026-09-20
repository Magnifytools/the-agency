"""Durable, restart-safe processing for Inbox classification suggestions."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from pydantic import ValidationError
from sqlalchemy import DateTime, func, select, update
from sqlalchemy.orm import lazyload, load_only, selectinload

from backend.db.models import (
    Client, ClientStatus, InboxNote, InboxNoteStatus, Project, ProjectStatus, User,
)
from backend.services.inbox_classifier import InboxProviderUnavailable, classify_inbox_note


logger = logging.getLogger(__name__)
CLASSIFICATION_BATCH_SIZE = 5
CLASSIFICATION_TIMEOUT_SECONDS = 25
CLASSIFICATION_RETRY_SECONDS = 300


def _updated_clock():
    # InboxNote.updated_at is a legacy timestamp in the DB session timezone.
    # Cast clock_timestamp to that same type so a post-lock write is monotonic.
    return func.clock_timestamp().cast(DateTime(timezone=False))


def can_read(user, module: str) -> bool:
    if user.role.value == "admin":
        return True
    return any(p.module == module and p.can_read for p in (user.permissions or []))


async def fetch_context(db, user) -> tuple[list[dict], list[dict]]:
    """Return only active entities visible under the actor's current permissions."""
    projects: list[dict] = []
    clients: list[dict] = []
    if can_read(user, "projects"):
        rows = await db.execute(
            select(
                Project.id, Project.name, Project.client_id,
                Client.name.label("client_name"),
            )
            .join(Client, Project.client_id == Client.id)
            .where(
                Project.status == ProjectStatus.active,
                Client.status == ClientStatus.active,
            )
            .order_by(Project.name)
            .limit(200)
        )
        projects = [
            {
                "id": row.id,
                "name": row.name,
                "client_id": row.client_id,
                "client_name": row.client_name if can_read(user, "clients") else None,
            }
            for row in rows.all()
        ]
    if can_read(user, "clients"):
        rows = await db.execute(
            select(Client.id, Client.name)
            .where(Client.status == ClientStatus.active)
            .order_by(Client.name)
            .limit(200)
        )
        clients = [{"id": row.id, "name": row.name} for row in rows.all()]
    return projects, clients


def _canonical_suggestion(suggestion: dict, projects: list[dict], clients: list[dict]) -> dict:
    """Replace provider entity labels with the exact visible context or drop them."""
    result = dict(suggestion)
    for key, available in (("suggested_project", projects), ("suggested_client", clients)):
        proposed = result.get(key)
        by_id = {item["id"]: item for item in available}
        canonical = by_id.get(proposed.get("id")) if isinstance(proposed, dict) else None
        if canonical is None:
            result[key] = None
        else:
            result[key] = {
                "id": canonical["id"],
                "name": canonical["name"],
                "confidence": proposed["confidence"],
            }
    project = result.get("suggested_project")
    client = result.get("suggested_client")
    if project is not None and client is not None:
        project_context = next(item for item in projects if item["id"] == project["id"])
        if project_context["client_id"] != client["id"]:
            raise ValueError("Suggested project and client do not match")
    result["_context_modules"] = [
        module for module, values in (("projects", projects), ("clients", clients)) if values
    ]
    return result


async def _requeue_changed_context(session_factory, snapshot) -> None:
    async with session_factory() as db:
        await db.execute(
            update(InboxNote)
            .where(
                InboxNote.id == snapshot["id"],
                InboxNote.user_id == snapshot["user_id"],
                InboxNote.status == InboxNoteStatus.pending,
                InboxNote.raw_text == snapshot["raw_text"],
                InboxNote.updated_at == snapshot["updated_at"],
            )
            .values(
                classification_error_code=None,
                classification_next_attempt_at=None,
                updated_at=_updated_clock(),
            )
        )
        await db.commit()


async def _store_failure(session_factory, snapshot, code: str) -> bool:
    async with session_factory() as db:
        result = await db.execute(
            update(InboxNote)
            .where(
                InboxNote.id == snapshot["id"],
                InboxNote.user_id == snapshot["user_id"],
                InboxNote.status == InboxNoteStatus.pending,
                InboxNote.raw_text == snapshot["raw_text"],
                InboxNote.updated_at == snapshot["updated_at"],
            )
            .values(
                classification_error_code=code,
                classification_next_attempt_at=(
                    func.timezone("UTC", func.clock_timestamp())
                    + timedelta(seconds=CLASSIFICATION_RETRY_SECONDS)
                ),
                updated_at=_updated_clock(),
            )
        )
        await db.commit()
        return bool(result.rowcount)


async def _process_one(session_factory, note_id: int) -> bool:
    async with session_factory() as db:
        row = (await db.execute(
            select(InboxNote, User)
            .join(User, InboxNote.user_id == User.id)
            .where(
                InboxNote.id == note_id,
                InboxNote.status == InboxNoteStatus.pending,
                User.is_active.is_(True),
            )
            .options(
                lazyload("*"),
                load_only(
                    InboxNote.id, InboxNote.user_id, InboxNote.raw_text,
                    InboxNote.updated_at, InboxNote.status,
                ),
                load_only(User.id, User.role, User.is_active),
                selectinload(User.permissions),
            )
        )).one_or_none()
        if row is None:
            return False
        note, user = row
        snapshot = {
            "id": note.id,
            "user_id": note.user_id,
            "raw_text": note.raw_text,
            "updated_at": note.updated_at,
        }
        projects, clients = await fetch_context(db, user)

    if not projects and not clients:
        return await _store_failure(session_factory, snapshot, "context_unavailable")

    try:
        suggestion = await asyncio.wait_for(
            classify_inbox_note(snapshot["raw_text"], projects, clients),
            timeout=CLASSIFICATION_TIMEOUT_SECONDS,
        )
    except InboxProviderUnavailable:
        return await _store_failure(session_factory, snapshot, "provider_unavailable")
    except (ValidationError, ValueError, TypeError, KeyError):
        return await _store_failure(session_factory, snapshot, "invalid_response")
    except Exception:
        return await _store_failure(session_factory, snapshot, "provider_unavailable")

    # Permissions and active entities may have changed while the provider was
    # running. Rebuild the visible context before persisting any provider data.
    async with session_factory() as db:
        user = (await db.execute(
            select(User)
            .where(User.id == snapshot["user_id"], User.is_active.is_(True))
            .options(
                lazyload("*"),
                load_only(User.id, User.role, User.is_active),
                selectinload(User.permissions),
            )
        )).scalar_one_or_none()
        if user is None:
            return False
        fresh_projects, fresh_clients = await fetch_context(db, user)
        if not fresh_projects and not fresh_clients:
            await db.rollback()
            return await _store_failure(session_factory, snapshot, "context_unavailable")
        if fresh_projects != projects or fresh_clients != clients:
            await db.rollback()
            await _requeue_changed_context(session_factory, snapshot)
            return False
        try:
            canonical = _canonical_suggestion(suggestion, fresh_projects, fresh_clients)
        except (ValueError, TypeError, KeyError):
            await db.rollback()
            return await _store_failure(session_factory, snapshot, "invalid_response")
        await db.execute(
            update(InboxNote)
            .where(
                InboxNote.id == snapshot["id"],
                InboxNote.user_id == snapshot["user_id"],
                InboxNote.status == InboxNoteStatus.pending,
                InboxNote.raw_text == snapshot["raw_text"],
                InboxNote.updated_at == snapshot["updated_at"],
            )
            .values(
                ai_suggestion=canonical,
                status=InboxNoteStatus.classified,
                classification_error_code=None,
                classification_next_attempt_at=None,
                updated_at=_updated_clock(),
            )
        )
        await db.commit()
        return False


def pending_batch_query(now):
    """Canonical due-queue query, shared with the PostgreSQL plan regression."""
    return (
        select(InboxNote.id)
        .join(User, InboxNote.user_id == User.id)
        .where(
            InboxNote.status == InboxNoteStatus.pending,
            User.is_active.is_(True),
            (
                InboxNote.classification_next_attempt_at.is_(None)
                | (InboxNote.classification_next_attempt_at <= now)
            ),
        )
        .order_by(
            func.coalesce(
                InboxNote.classification_next_attempt_at, InboxNote.updated_at,
            ),
            InboxNote.id,
        )
        .limit(CLASSIFICATION_BATCH_SIZE)
    )


async def run_inbox_classification_once(session_factory=None) -> int:
    """Process a bounded durable batch and return the number of failed attempts."""
    if session_factory is None:
        from backend.db.database import async_session

        session_factory = async_session

    async with session_factory() as db:
        now = func.timezone("UTC", func.clock_timestamp())
        ids = (await db.scalars(pending_batch_query(now))).all()

    failed = 0
    for note_id in ids:
        try:
            failed += int(await _process_one(session_factory, note_id))
        except Exception as exc:
            failed += 1
            logger.error("Inbox classification failed for note %d (%s)", note_id, type(exc).__name__)
    return failed
