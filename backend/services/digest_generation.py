"""Recoverable digest generation with short database transactions."""

from __future__ import annotations
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select, text

from backend.db.models import (
    Client,
    ClientReportPolicy,
    ClientStatus,
    DigestStatus,
    DigestTone,
    User,
    UserRole,
    WeeklyDigest,
)
from backend.services.digest_access import user_has_digest_permission
from backend.services.digest_collector import collect_digest_data
from backend.services.digest_generator import generate_digest_content
from backend.services.digest_periods import (
    canonicalize_digest_content,
    policy_digest_period,
)
from backend.services.temporal import utc_now_naive


@dataclass
class DigestGenerationRejected(Exception):
    reason: str


def _hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def coverage_lock_key(client_id: int, period_start: date, period_end: date) -> int:
    raw = f"digest:{client_id}:{period_start.isoformat()}:{period_end.isoformat()}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big", signed=True)


def generation_lock_key(actor_id: int, generation_key: str) -> int:
    raw = f"digest-generation:{actor_id}:{generation_key}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big", signed=True)


async def _lock(db, key: int) -> None:
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def _generation(raw_context: dict | None) -> dict:
    value = (raw_context or {}).get("_generation")
    return value if isinstance(value, dict) else {}


async def find_generation(
    db, *, actor_id: int, generation_key: str
) -> WeeklyDigest | None:
    return (
        await db.execute(
            select(WeeklyDigest)
            .where(
                WeeklyDigest.created_by == actor_id,
                WeeklyDigest.raw_context["_generation"]["key"].as_string()
                == generation_key,
            )
            .order_by(WeeklyDigest.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _assert_replay(digest: WeeklyDigest, request_hash: str) -> WeeklyDigest:
    if _generation(digest.raw_context).get("request_hash") != request_hash:
        raise DigestGenerationRejected("generation_key_conflict")
    return digest


async def _snapshot(
    db,
    *,
    actor_id: int,
    client_id: int,
    expected_revision: int | None,
    require_enabled: bool,
    expected_period: tuple[date, date] | None,
):
    actor = (
        await db.execute(
            select(User.id, User.role, User.is_active).where(User.id == actor_id)
        )
    ).one_or_none()
    if (
        not actor
        or not actor.is_active
        or not await user_has_digest_permission(db, actor_id, write=True)
    ):
        raise DigestGenerationRejected("permission_changed")
    client = (
        await db.execute(
            select(Client.id, Client.status, Client.is_internal).where(
                Client.id == client_id
            )
        )
    ).one_or_none()
    if not client:
        raise DigestGenerationRejected("client_missing")
    if client.status != ClientStatus.active:
        raise DigestGenerationRejected("client_inactive")
    if client.is_internal:
        raise DigestGenerationRejected("internal_client")
    policy = (
        await db.execute(
            select(
                ClientReportPolicy.revision,
                ClientReportPolicy.enabled,
                ClientReportPolicy.cadence,
                ClientReportPolicy.responsible_user_id,
            ).where(ClientReportPolicy.client_id == client_id)
        )
    ).one_or_none()
    if not policy:
        if expected_revision not in (None, -1):
            raise DigestGenerationRejected("policy_changed")
        if actor.role == UserRole.admin and not require_enabled:
            return None
        if expected_revision == -1:
            raise DigestGenerationRejected("permission_changed")
        raise DigestGenerationRejected("policy_missing")
    if expected_revision == -1:
        raise DigestGenerationRejected("policy_changed")
    if expected_revision is not None and policy.revision != expected_revision:
        raise DigestGenerationRejected("policy_changed")
    if require_enabled and not policy.enabled:
        raise DigestGenerationRejected("policy_disabled")
    if require_enabled or actor.role != UserRole.admin:
        if policy.responsible_user_id is None or not await user_has_digest_permission(
            db, policy.responsible_user_id, write=True
        ):
            raise DigestGenerationRejected("responsible_unavailable")
        if actor.role != UserRole.admin and policy.responsible_user_id != actor_id:
            raise DigestGenerationRejected("permission_changed")
    if (
        expected_period is not None
        and policy_digest_period(policy.cadence.value) != expected_period
    ):
        raise DigestGenerationRejected("period_changed")
    return policy


def generation_request_hash(
    *,
    client_id: int,
    period_start: date,
    period_end: date,
    tone: DigestTone,
    source_digest_id: int | None = None,
    source_hash: str | None = None,
) -> str:
    return _hash(
        {
            "client_id": client_id,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "tone": tone.value,
            "source_digest_id": source_digest_id,
            "source_hash": source_hash,
        }
    )


def legacy_source_context(raw_context: dict) -> dict:
    context = dict(raw_context)
    if not isinstance(context.get("source_catalog"), dict):
        context["source_catalog"] = {
            "legacy:raw_context": {
                "kind": "legacy",
                "class": "legacy",
                "label": "Contexto guardado de la versión anterior",
            }
        }
    return context


async def generate_locked_digest(
    db,
    *,
    actor_id: int,
    client_id: int,
    period_start: date,
    period_end: date,
    tone: DigestTone,
    generation_key: str,
    expected_revision: int | None,
    require_enabled: bool,
    reject_existing: bool,
    collector=collect_digest_data,
    generator=generate_digest_content,
) -> WeeklyDigest:
    request_hash = generation_request_hash(
        client_id=client_id, period_start=period_start, period_end=period_end, tone=tone
    )
    existing = await find_generation(
        db, actor_id=actor_id, generation_key=generation_key
    )
    if existing:
        return _assert_replay(existing, request_hash)
    expected_period = (period_start, period_end) if require_enabled else None
    initial = await _snapshot(
        db,
        actor_id=actor_id,
        client_id=client_id,
        expected_revision=expected_revision,
        require_enabled=require_enabled,
        expected_period=expected_period,
    )
    if reject_existing and await db.scalar(
        select(
            select(WeeklyDigest.id)
            .where(
                WeeklyDigest.client_id == client_id,
                WeeklyDigest.period_start == period_start,
                WeeklyDigest.period_end == period_end,
            )
            .exists()
        )
    ):
        raise DigestGenerationRejected("already_exists")
    raw_data = await collector(db, client_id, period_start, period_end)
    if not isinstance(raw_data.get("source_catalog"), dict):
        raise DigestGenerationRejected("source_catalog_missing")
    await db.commit()

    generated = await generator(raw_data, tone)

    await _lock(db, generation_lock_key(actor_id, generation_key))
    replay = await find_generation(db, actor_id=actor_id, generation_key=generation_key)
    if replay:
        return _assert_replay(replay, request_hash)
    await _lock(db, coverage_lock_key(client_id, period_start, period_end))
    await _snapshot(
        db,
        actor_id=actor_id,
        client_id=client_id,
        expected_revision=initial.revision if initial else -1,
        require_enabled=require_enabled,
        expected_period=expected_period,
    )
    if reject_existing and await db.scalar(
        select(
            select(WeeklyDigest.id)
            .where(
                WeeklyDigest.client_id == client_id,
                WeeklyDigest.period_start == period_start,
                WeeklyDigest.period_end == period_end,
            )
            .exists()
        )
    ):
        raise DigestGenerationRejected("already_exists")

    stored_context = dict(raw_data)
    stored_context["_generation"] = {
        "key": generation_key,
        "request_hash": request_hash,
        "actor_id": actor_id,
        "source_digest_id": None,
    }
    digest = WeeklyDigest(
        client_id=client_id,
        period_start=period_start,
        period_end=period_end,
        status=DigestStatus.draft,
        tone=tone,
        content=canonicalize_digest_content(generated, period_start, period_end),
        raw_context=stored_context,
        generated_at=utc_now_naive(),
        created_by=actor_id,
    )
    db.add(digest)
    await db.flush()
    return digest


async def regenerate_digest(
    db,
    *,
    actor_id: int,
    source: WeeklyDigest,
    tone: DigestTone,
    generation_key: str,
    generator: Callable[[dict, DigestTone], Awaitable[dict]] = generate_digest_content,
) -> WeeklyDigest:
    source_hash = _hash({"content": source.content, "raw_context": source.raw_context})
    request_hash = generation_request_hash(
        client_id=source.client_id,
        period_start=source.period_start,
        period_end=source.period_end,
        tone=tone,
        source_digest_id=source.id,
        source_hash=source_hash,
    )
    existing = await find_generation(
        db, actor_id=actor_id, generation_key=generation_key
    )
    if existing:
        return _assert_replay(existing, request_hash)
    source_id, client_id = source.id, source.client_id
    period_start, period_end = source.period_start, source.period_end
    context = legacy_source_context(source.raw_context or {})
    await db.commit()

    generated = await generator(context, tone)

    await _lock(db, generation_lock_key(actor_id, generation_key))
    replay = await find_generation(db, actor_id=actor_id, generation_key=generation_key)
    if replay:
        return _assert_replay(replay, request_hash)
    await _lock(db, coverage_lock_key(client_id, period_start, period_end))
    source_now = (
        await db.execute(
            select(WeeklyDigest)
            .where(WeeklyDigest.id == source_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if (
        source_now is None
        or _hash({"content": source_now.content, "raw_context": source_now.raw_context})
        != source_hash
    ):
        raise DigestGenerationRejected("source_changed")
    await _snapshot(
        db,
        actor_id=actor_id,
        client_id=client_id,
        expected_revision=None,
        require_enabled=False,
        expected_period=None,
    )
    stored_context = dict(context)
    stored_context["_generation"] = {
        "key": generation_key,
        "request_hash": request_hash,
        "actor_id": actor_id,
        "source_digest_id": source_id,
    }
    version = WeeklyDigest(
        client_id=client_id,
        period_start=period_start,
        period_end=period_end,
        status=DigestStatus.draft,
        tone=tone,
        content=canonicalize_digest_content(generated, period_start, period_end),
        raw_context=stored_context,
        generated_at=utc_now_naive(),
        edited_at=None,
        created_by=actor_id,
    )
    db.add(version)
    await db.flush()
    return version
