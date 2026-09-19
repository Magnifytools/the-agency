"""Locked digest generation shared by individual and cohort entry points."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

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
from backend.services.digest_periods import canonicalize_digest_content, policy_digest_period
from backend.services.temporal import utc_now_naive


@dataclass
class DigestGenerationRejected(Exception):
    reason: str


def coverage_lock_key(client_id: int, period_start: date, period_end: date) -> int:
    raw = f"digest:{client_id}:{period_start.isoformat()}:{period_end.isoformat()}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big", signed=True)


async def _try_coverage_lock(db, client_id: int, period_start: date, period_end: date) -> bool:
    return bool(await db.scalar(
        text("SELECT pg_try_advisory_xact_lock(:key)"),
        {"key": coverage_lock_key(client_id, period_start, period_end)},
    ))


async def _snapshot(db, *, actor_id: int, client_id: int, expected_revision: int | None, require_enabled: bool, expected_period: tuple[date, date] | None):
    actor = (await db.execute(select(User.id, User.role, User.is_active).where(User.id == actor_id))).one_or_none()
    if not actor or not actor.is_active or not await user_has_digest_permission(db, actor_id, write=True):
        raise DigestGenerationRejected("permission_changed")
    client = (await db.execute(
        select(Client.id, Client.status, Client.is_internal).where(Client.id == client_id)
    )).one_or_none()
    if not client:
        raise DigestGenerationRejected("client_missing")
    if client.status != ClientStatus.active:
        raise DigestGenerationRejected("client_inactive")
    if client.is_internal:
        raise DigestGenerationRejected("internal_client")
    policy = (await db.execute(
        select(
            ClientReportPolicy.revision,
            ClientReportPolicy.enabled,
            ClientReportPolicy.cadence,
            ClientReportPolicy.responsible_user_id,
        ).where(ClientReportPolicy.client_id == client_id)
    )).one_or_none()
    if not policy:
        if expected_revision == -1:
            return None
        if actor.role == UserRole.admin and not require_enabled:
            return None
        raise DigestGenerationRejected("policy_missing")
    if expected_revision == -1:
        raise DigestGenerationRejected("policy_changed")
    if expected_revision is not None and policy.revision != expected_revision:
        raise DigestGenerationRejected("policy_changed")
    if require_enabled and not policy.enabled:
        raise DigestGenerationRejected("policy_disabled")
    if require_enabled or actor.role != UserRole.admin:
        if policy.responsible_user_id is None or not await user_has_digest_permission(db, policy.responsible_user_id, write=True):
            raise DigestGenerationRejected("responsible_unavailable")
        if actor.role != UserRole.admin and policy.responsible_user_id != actor_id:
            raise DigestGenerationRejected("permission_changed")
    if expected_period is not None and policy_digest_period(policy.cadence.value) != expected_period:
        raise DigestGenerationRejected("period_changed")
    return policy


async def generate_locked_digest(
    db,
    *,
    actor_id: int,
    client_id: int,
    period_start: date,
    period_end: date,
    tone: DigestTone,
    expected_revision: int | None,
    require_enabled: bool,
    reject_existing: bool,
    collector=collect_digest_data,
    generator=generate_digest_content,
) -> WeeklyDigest:
    if not await _try_coverage_lock(db, client_id, period_start, period_end):
        raise DigestGenerationRejected("concurrent_generation")
    expected_period = (period_start, period_end) if require_enabled else None
    initial = await _snapshot(
        db,
        actor_id=actor_id,
        client_id=client_id,
        expected_revision=expected_revision,
        require_enabled=require_enabled,
        expected_period=expected_period,
    )
    if reject_existing and await db.scalar(select(
        select(WeeklyDigest.id).where(
            WeeklyDigest.client_id == client_id,
            WeeklyDigest.period_start == period_start,
            WeeklyDigest.period_end == period_end,
        ).exists()
    )):
        raise DigestGenerationRejected("already_exists")

    raw_data = await collector(db, client_id, period_start, period_end)
    generated = await generator(raw_data, tone)

    # Permissions and policy are mutable while the provider runs. Re-read every
    # relevant scalar under the still-held coverage lock before persisting.
    await _snapshot(
        db,
        actor_id=actor_id,
        client_id=client_id,
        expected_revision=initial.revision if initial else -1,
        require_enabled=require_enabled,
        expected_period=expected_period,
    )
    if reject_existing and await db.scalar(select(
        select(WeeklyDigest.id).where(
            WeeklyDigest.client_id == client_id,
            WeeklyDigest.period_start == period_start,
            WeeklyDigest.period_end == period_end,
        ).exists()
    )):
        raise DigestGenerationRejected("already_exists")

    digest = WeeklyDigest(
        client_id=client_id,
        period_start=period_start,
        period_end=period_end,
        status=DigestStatus.draft,
        tone=tone,
        content=canonicalize_digest_content(generated, period_start, period_end),
        raw_context=raw_data,
        generated_at=utc_now_naive(),
        created_by=actor_id,
    )
    db.add(digest)
    await db.flush()
    return digest
