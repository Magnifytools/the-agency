from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from backend.db.models import (
    ChangeLog,
    ClientOnboardingReceipt,
    User,
    UserPermission,
    UserRole,
)
from backend.core.modules import is_enabled
from backend.schemas.client_onboarding import (
    ClientOnboardingCreate,
    ClientOnboardingResponse,
)
from backend.services.change_journal import prepare_entry
from backend.services.domain_writes import create_client, create_contact, create_project


ONBOARDING_LOCK_NAMESPACE = 76241323


def canonical_request_hash(payload: ClientOnboardingCreate) -> str:
    normalized = payload.model_dump(mode="json")
    encoded = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _lock_id(user_id: int, request_key: str) -> int:
    digest = hashlib.sha256(f"{user_id}:{request_key}".encode()).digest()
    return int.from_bytes(digest[:4], "big", signed=True)


async def _lock_attempt(
    db: AsyncSession, user_id: int, request_key: str, *, wait: bool,
) -> bool:
    lock_id = _lock_id(user_id, request_key)
    if wait:
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :lock_id)"),
            {"namespace": ONBOARDING_LOCK_NAMESPACE, "lock_id": lock_id},
        )
        return True
    acquired = await db.scalar(
        text("SELECT pg_try_advisory_xact_lock(:namespace, :lock_id)"),
        {"namespace": ONBOARDING_LOCK_NAMESPACE, "lock_id": lock_id},
    )
    return bool(acquired)


async def _lock_fresh_actor(db: AsyncSession, user_id: int) -> User:
    actor = (await db.execute(
        select(User).options(noload("*")).where(User.id == user_id)
        .with_for_update(key_share=True).execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if actor is None or not actor.is_active:
        raise HTTPException(403, "Tu sesión ya no tiene acceso. Vuelve a entrar.")
    return actor


async def _require_fresh_write_permissions(
    db: AsyncSession, actor: User, modules: set[str],
) -> None:
    for module in sorted(modules):
        if not is_enabled(module):
            raise HTTPException(404, f"El módulo {module} no está disponible")
    if actor.role == UserRole.admin:
        return
    allowed = set((await db.scalars(
        select(UserPermission.module).where(
            UserPermission.user_id == actor.id,
            UserPermission.module.in_(sorted(modules)),
            UserPermission.can_write.is_(True),
        )
    )).all())
    missing = modules - allowed
    if missing:
        module = sorted(missing)[0]
        raise HTTPException(
            403,
            f"Sin acceso de escritura al módulo: {module}. Pide a un administrador que te dé acceso.",
        )


async def _owned_receipt(
    db: AsyncSession, user_id: int, request_key: str,
) -> ClientOnboardingReceipt | None:
    return await db.scalar(
        select(ClientOnboardingReceipt).where(
            ClientOnboardingReceipt.user_id == user_id,
            ClientOnboardingReceipt.request_key == request_key,
        )
    )


def _confirmed_result(receipt: ClientOnboardingReceipt) -> tuple[int, list[int], int | None]:
    result = receipt.result
    if not isinstance(result, dict):
        raise HTTPException(500, "El recibo de alta no contiene un resultado válido")
    client_id = result.get("client_id")
    contact_ids = result.get("contact_ids")
    project_id = result.get("project_id")
    if (
        not isinstance(client_id, int) or isinstance(client_id, bool)
        or not isinstance(contact_ids, list)
        or any(not isinstance(value, int) or isinstance(value, bool) for value in contact_ids)
        or (project_id is not None and (not isinstance(project_id, int) or isinstance(project_id, bool)))
    ):
        raise HTTPException(500, "El recibo de alta no contiene un resultado válido")
    return client_id, contact_ids, project_id


async def _undo_state(
    db: AsyncSession, receipt: ClientOnboardingReceipt, actor: User,
) -> tuple[str, int | None]:
    if receipt.change_log_id is None:
        return "unavailable", None
    journal = await db.scalar(
        select(ChangeLog).where(
            ChangeLog.id == receipt.change_log_id,
            ChangeLog.user_id == actor.id,
        )
    )
    if journal is None:
        return "unavailable", None
    if journal.undone_at is not None:
        return "undone", journal.id
    return "available", journal.id


async def confirmed_response(
    db: AsyncSession,
    receipt: ClientOnboardingReceipt,
    actor: User,
    *,
    replayed: bool,
) -> ClientOnboardingResponse:
    client_id, contact_ids, project_id = _confirmed_result(receipt)
    undo_state, change_log_id = await _undo_state(db, receipt, actor)
    return ClientOnboardingResponse(
        status="confirmed",
        client_id=client_id,
        contact_ids=contact_ids,
        project_id=project_id,
        replayed=replayed,
        undo_state=undo_state,
        change_log_id=change_log_id,
    )


async def create_onboarding(
    db: AsyncSession,
    actor: User,
    request_key: str,
    payload: ClientOnboardingCreate,
) -> tuple[ClientOnboardingResponse, bool]:
    """Create the reviewed bundle once. Returns (response, was_created)."""
    request_hash = canonical_request_hash(payload)
    await _lock_attempt(db, actor.id, request_key, wait=True)
    actor = await _lock_fresh_actor(db, actor.id)
    modules = {"clients"}
    if payload.project is not None:
        modules.add("projects")
    await _require_fresh_write_permissions(db, actor, modules)

    receipt = await _owned_receipt(db, actor.id, request_key)
    if receipt is not None:
        if receipt.status == "cancelled":
            raise HTTPException(409, {"code": "attempt_cancelled"})
        if receipt.status != "confirmed" or receipt.request_hash != request_hash:
            raise HTTPException(409, {"code": "idempotency_conflict"})
        response = await confirmed_response(db, receipt, actor, replayed=True)
        await db.commit()
        return response, False

    receipt = ClientOnboardingReceipt(
        user_id=actor.id,
        request_key=request_key,
        status="confirmed",
        request_hash=request_hash,
        result={},
    )
    db.add(receipt)
    await db.flush()

    client = await create_client(db, payload.client.model_dump())
    contacts = [
        await create_contact(db, client.id, contact.model_dump())
        for contact in payload.contacts
    ]
    project = None
    if payload.project is not None:
        project_data = payload.project.model_dump()
        project_data["client_id"] = client.id
        project = await create_project(db, project_data)

    journal = await db.run_sync(prepare_entry)
    if journal is None:
        raise HTTPException(500, "No se pudo preparar el historial del alta")
    result: dict[str, Any] = {
        "client_id": client.id,
        "contact_ids": [contact.id for contact in contacts],
        "project_id": project.id if project else None,
    }
    receipt.result = result
    receipt.change_log_id = journal.id
    await db.flush()
    response = await confirmed_response(db, receipt, actor, replayed=False)
    await db.commit()
    return response, True


async def recover_onboarding(
    db: AsyncSession, actor: User, request_key: str,
) -> tuple[ClientOnboardingResponse, int]:
    if not await _lock_attempt(db, actor.id, request_key, wait=False):
        await db.rollback()
        return ClientOnboardingResponse(status="processing"), 202

    actor = await _lock_fresh_actor(db, actor.id)
    await _require_fresh_write_permissions(db, actor, {"clients"})
    receipt = await _owned_receipt(db, actor.id, request_key)
    if receipt is not None and receipt.status == "confirmed":
        _, _, project_id = _confirmed_result(receipt)
        if project_id is not None:
            await _require_fresh_write_permissions(db, actor, {"projects"})
        response = await confirmed_response(db, receipt, actor, replayed=True)
        await db.commit()
        return response, 200
    if receipt is None:
        db.add(ClientOnboardingReceipt(
            user_id=actor.id,
            request_key=request_key,
            status="cancelled",
            request_hash=None,
            result=None,
            change_log_id=None,
        ))
        await db.flush()
    elif receipt.status != "cancelled":
        raise HTTPException(500, "El recibo de alta tiene un estado inválido")
    await db.commit()
    return ClientOnboardingResponse(status="not_committed"), 200
