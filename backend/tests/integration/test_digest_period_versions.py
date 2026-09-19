# ruff: noqa: DTZ001
"""Closed-period and durable digest-version regressions."""

from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from backend.db.models import (
    Client,
    ClientStatus,
    DigestStatus,
    DigestTone,
    WeeklyDigest,
)
from backend.schemas.digest import DigestContent
from backend.services.digest_periods import (
    format_digest_period,
    last_closed_weekly_period,
)
from backend.services.digest_renderer import (
    render_discord,
    render_email,
    render_email_plain,
    render_slack,
)

pytestmark = pytest.mark.integration


def _content(*, title: str = "Hecho", date_text: str = "inventada") -> dict:
    return {
        "greeting": "Hola",
        "date": date_text,
        "sections": {
            "done": [{"title": title, "description": "Detalle"}],
            "need": [],
            "next": [],
            "metrics": [],
        },
        "closing": "Fin",
    }


def test_last_closed_period_and_cross_month_label_are_civil():
    assert last_closed_weekly_period(today=date(2026, 9, 16)) == (
        date(2026, 9, 7),
        date(2026, 9, 13),
    )
    assert format_digest_period(date(2025, 12, 29), date(2026, 1, 4)) == (
        "Período del 29 de diciembre de 2025 al 4 de enero de 2026"
    )


async def test_period_validation_rejects_partial_reversed_and_invalid(
    admin_client,
):
    partial = await admin_client.post("/api/digests/generate", json={
        "client_id": 1,
        "period_start": "2026-09-07",
    })
    reversed_period = await admin_client.post("/api/digests/generate", json={
        "client_id": 1,
        "period_start": "2026-09-14",
        "period_end": "2026-09-07",
    })
    invalid = await admin_client.post("/api/digests/generate", json={
        "client_id": 1,
        "period_start": "no-es-fecha",
        "period_end": "2026-09-07",
    })
    batch_partial = await admin_client.post(
        "/api/digests/generate-batch?period_start=2026-09-07"
    )

    assert partial.status_code == 422
    assert reversed_period.status_code == 422
    assert invalid.status_code == 422
    assert batch_partial.status_code == 410


async def test_generate_preserves_prior_versions_and_provider_failure(
    admin_client, db_session, admin_user
):
    client = Client(name="Cliente versiones", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    client_id = client.id
    generated = AsyncMock(return_value=_content())

    with (
        patch(
            "backend.api.routes.digests.collect_digest_data",
            new_callable=AsyncMock,
            return_value={"client_name": client.name},
        ),
        patch("backend.api.routes.digests.generate_digest_content", generated),
    ):
        first = await admin_client.post("/api/digests/generate", json={
            "client_id": client.id,
            "period_start": "2026-09-07",
            "period_end": "2026-09-13",
        })
        second = await admin_client.post("/api/digests/generate", json={
            "client_id": client.id,
            "period_start": "2026-09-07",
            "period_end": "2026-09-13",
        })
        generated.side_effect = RuntimeError("provider unavailable")
        failed = await admin_client.post("/api/digests/generate", json={
            "client_id": client.id,
            "period_start": "2026-09-14",
            "period_end": "2026-09-20",
        })

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["content"]["date"] == (
        "Período del 7 al 13 de septiembre de 2026"
    )
    assert failed.status_code == 502
    count = await db_session.scalar(select(func.count(WeeklyDigest.id)).where(
        WeeklyDigest.client_id == client_id
    ))
    assert count == 2


async def test_generate_default_uses_last_closed_madrid_week(
    admin_client, db_session
):
    client = Client(name="Cliente periodo default", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    with (
        patch(
            "backend.services.digest_periods.business_today",
            return_value=date(2026, 9, 16),
        ),
        patch(
            "backend.api.routes.digests.collect_digest_data",
            new_callable=AsyncMock,
            return_value={"client_name": client.name},
        ),
        patch(
            "backend.api.routes.digests.generate_digest_content",
            new_callable=AsyncMock,
            return_value=_content(),
        ),
    ):
        response = await admin_client.post(
            "/api/digests/generate", json={"client_id": client.id}
        )

    assert response.status_code == 200, response.text
    assert response.json()["period_start"] == "2026-09-07"
    assert response.json()["period_end"] == "2026-09-13"


async def test_put_is_idempotent_or_creates_new_source_version(
    admin_client, db_session, admin_user
):
    client = Client(name="Cliente editable", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    original = WeeklyDigest(
        client_id=client.id,
        period_start=date(2026, 9, 7),
        period_end=date(2026, 9, 13),
        status=DigestStatus.reviewed,
        tone=DigestTone.cercano,
        content={
            "date": "FECHA IA HISTÓRICA",
            "sections": {
                "done": [{"title": "Hecho", "description": "Detalle"}],
                "need": [],
                "next": [],
            },
        },
        raw_context={"client_name": client.name},
        generated_at=datetime(2026, 9, 14, 8),
        created_by=admin_user.id,
    )
    db_session.add(original)
    await db_session.flush()

    fetched = await admin_client.get(f"/api/digests/{original.id}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["content"]["date"] == (
        "Período del 7 al 13 de septiembre de 2026"
    )
    assert fetched.json()["content"]["greeting"] == ""
    assert fetched.json()["content"]["sections"]["metrics"] == []
    await db_session.refresh(original)
    assert original.content["date"] == "FECHA IA HISTÓRICA"

    identical = await admin_client.put(
        f"/api/digests/{original.id}",
        json={"content": fetched.json()["content"], "tone": "cercano"},
    )
    assert identical.status_code == 200, identical.text
    assert identical.json()["id"] == original.id

    changed_content = _content(title="Hecho corregido")
    changed = await admin_client.put(
        f"/api/digests/{original.id}",
        json={"content": changed_content, "tone": "cercano"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["id"] != original.id
    assert changed.json()["status"] == "draft"
    assert changed.json()["content"]["date"] == (
        "Período del 7 al 13 de septiembre de 2026"
    )

    await db_session.refresh(original)
    assert original.status == DigestStatus.reviewed
    assert original.content["sections"]["done"][0]["title"] == "Hecho"
    assert original.content["date"] == "FECHA IA HISTÓRICA"
    assert await db_session.scalar(select(func.count(WeeklyDigest.id)).where(
        WeeklyDigest.client_id == client.id
    )) == 2

    regenerated_content = _content(title="Regenerado", date_text="otra inventada")
    with patch(
        "backend.api.routes.digests.generate_digest_content",
        new_callable=AsyncMock,
        return_value=regenerated_content,
    ) as generator:
        regenerated = await admin_client.put(
            f"/api/digests/{original.id}", json={"tone": "formal"}
        )

    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.json()["id"] not in {original.id, changed.json()["id"]}
    assert regenerated.json()["tone"] == "formal"
    assert regenerated.json()["content"]["date"] == (
        "Período del 7 al 13 de septiembre de 2026"
    )
    generator.assert_awaited_once_with(original.raw_context, DigestTone.formal)
    await db_session.refresh(original)
    assert original.tone == DigestTone.cercano
    assert await db_session.scalar(select(func.count(WeeklyDigest.id)).where(
        WeeklyDigest.client_id == client.id
    )) == 3


async def test_retired_batch_keeps_existing_draft(db_session, admin_client, admin_user):
    client = Client(name="Cliente batch", status=ClientStatus.active)
    db_session.add(client)
    await db_session.flush()
    existing = WeeklyDigest(
        client_id=client.id,
        period_start=date(2026, 8, 31),
        period_end=date(2026, 9, 6),
        status=DigestStatus.draft,
        tone=DigestTone.cercano,
        content=_content(),
        raw_context={},
        created_by=admin_user.id,
    )
    db_session.add(existing)
    await db_session.flush()
    existing_id = existing.id

    with (
        patch(
            "backend.api.routes.digests.collect_digest_data",
            new_callable=AsyncMock,
            return_value={"client_name": client.name},
        ),
        patch(
            "backend.api.routes.digests.generate_digest_content",
            new_callable=AsyncMock,
            return_value=_content(),
        ),
        patch(
            "backend.services.notification_service.create_notification",
            new_callable=AsyncMock,
        ),
    ):
        response = await admin_client.post(
            "/api/digests/generate-batch",
            params={"period_start": "2026-09-07", "period_end": "2026-09-13"},
        )

    assert response.status_code == 410, response.text
    assert response.json()["detail"]["code"] == "legacy_batch_retired"
    assert await db_session.get(WeeklyDigest, existing_id) is not None


def test_all_renderers_ignore_generated_date_when_period_is_available():
    content = DigestContent(**_content(date_text="FECHA INVENTADA"))
    start, end = date(2025, 12, 29), date(2026, 1, 4)
    expected = "Período del 29 de diciembre de 2025 al 4 de enero de 2026"

    rendered = [
        render_slack(content, period_start=start, period_end=end),
        render_discord(content, period_start=start, period_end=end),
        render_email(content, period_start=start, period_end=end),
        render_email_plain(content, period_start=start, period_end=end),
    ]
    assert all(expected in value for value in rendered)
    assert all("FECHA INVENTADA" not in value for value in rendered)
    assert "Resumen diario" not in rendered[1]
    assert "**📊 Resumen — Magnify" in rendered[1]
