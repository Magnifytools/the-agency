"""Enlace de sólo lectura del cliente contra Postgres real."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from backend.core.rate_limiter import public_link_limiter
from backend.db.models import (
    Client,
    ClientShareLink,
    ClientStatus,
    DigestExternalDeliveryEvent,
    DigestStatus,
    ExternalDeliveryAction,
    GscDaily,
    GscSiteSync,
    WeeklyDigest,
)
from backend.services import client_share_links as links

pytestmark = pytest.mark.integration

SITE = "sc-domain:ejemplo.com"


@pytest_asyncio.fixture(autouse=True)
async def _fresh_limiter():
    public_link_limiter._limiter._requests.clear()
    yield
    public_link_limiter._limiter._requests.clear()


@pytest_asyncio.fixture
async def public(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def client_row(db_session):
    client = Client(name="Fit Generation", status=ClientStatus.active, gsc_url=SITE,
                    notes="NOTA INTERNA: no renovar")
    db_session.add(client)
    await db_session.commit()
    return client


def _content(text_: str) -> dict:
    return {"greeting": f"Hola, {text_}", "sections": {"done": [{"title": text_, "description": "detalle"}]},
            "closing": "Un saludo"}


async def _digest(db, client, user, *, start, end, body, events=(), status=DigestStatus.sent):
    digest = WeeklyDigest(client_id=client.id, period_start=start, period_end=end, status=status,
                          content=_content(body), created_by=user.id,
                          raw_context={"internal_notes": "SECRETO-RAW", "seo": None})
    db.add(digest)
    await db.flush()
    for i, (action, at) in enumerate(events):
        db.add(DigestExternalDeliveryEvent(digest_id=digest.id, action=action, actor_id=user.id,
                                           request_key=f"k-{digest.id}-{i}", request_hash="0" * 64,
                                           created_at=at))
    await db.commit()
    return digest


async def _create(admin_client, client_id) -> str:
    r = await admin_client.post(f"/api/clients/{client_id}/share-link")
    assert r.status_code == 201, r.text
    path = r.json()["path"]
    assert path.startswith("/c/")
    return path.removeprefix("/c/")


async def test_only_the_hash_is_stored_and_status_never_returns_the_token(admin_client, db_session, client_row):
    token = await _create(admin_client, client_row.id)
    stored = (await db_session.scalars(select(ClientShareLink))).all()
    assert len(stored) == 1
    assert stored[0].token_hash == links.hash_token(token) and token not in stored[0].token_hash
    dump = await db_session.scalar(text("SELECT to_jsonb(l)::text FROM client_share_links l"))
    assert token not in dump

    status = (await admin_client.get(f"/api/clients/{client_row.id}/share-link")).json()
    assert status["active"] is True and status["created_by_name"] == "Admin Integration"
    assert token not in str(status) and "path" not in status


async def test_public_view_shows_name_and_noindex(admin_client, public, client_row):
    token = await _create(admin_client, client_row.id)
    r = await public.get(f"/api/public/clients/{token}")
    assert r.status_code == 200, r.text
    assert r.json()["client_name"] == "Fit Generation"
    assert "noindex" in r.headers["x-robots-tag"]
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "NOTA INTERNA" not in r.text


async def test_unknown_revoked_and_malformed_tokens_get_the_same_404(admin_client, public, client_row):
    old = await _create(admin_client, client_row.id)
    new = await _create(admin_client, client_row.id)  # regenerar revoca el anterior
    unknown = links.new_token()
    responses = [await public.get(f"/api/public/clients/{t}") for t in (old, unknown, "corto", "x" * 200)]
    assert {r.status_code for r in responses} == {404}
    assert len({r.text for r in responses}) == 1
    assert all("noindex" in r.headers["x-robots-tag"] for r in responses)
    assert (await public.get(f"/api/public/clients/{new}")).status_code == 200

    assert (await admin_client.delete(f"/api/clients/{client_row.id}/share-link")).status_code == 204
    assert (await public.get(f"/api/public/clients/{new}")).status_code == 404
    status = (await admin_client.get(f"/api/clients/{client_row.id}/share-link")).json()
    assert status == {"active": False, "created_at": None, "created_by_name": None, "last_viewed_at": None}


async def test_only_delivered_digests_are_exposed(admin_client, public, db_session, client_row, admin_user):
    t0 = datetime(2026, 10, 2, 9, tzinfo=UTC).replace(tzinfo=None)
    # Borrador sin entregar, aunque su etiqueta histórica diga "sent".
    await _digest(db_session, client_row, admin_user, start=date(2026, 9, 1), end=date(2026, 9, 30),
                  body="BORRADOR-SEPTIEMBRE")
    # Entregado y luego revocado: ya no cuenta.
    await _digest(db_session, client_row, admin_user, start=date(2026, 7, 1), end=date(2026, 7, 31),
                  body="REVOCADO-JULIO", events=[(ExternalDeliveryAction.confirmed, t0),
                                                 (ExternalDeliveryAction.revoked, t0 + timedelta(hours=1))])
    # Agosto: dos versiones entregadas → sólo la última.
    await _digest(db_session, client_row, admin_user, start=date(2026, 8, 1), end=date(2026, 8, 31),
                  body="AGOSTO-V1", events=[(ExternalDeliveryAction.confirmed, t0)])
    await _digest(db_session, client_row, admin_user, start=date(2026, 8, 1), end=date(2026, 8, 31),
                  body="AGOSTO-V2", events=[(ExternalDeliveryAction.confirmed, t0 + timedelta(days=1))])
    # Otro cliente: nunca.
    other = Client(name="Otro", status=ClientStatus.active)
    db_session.add(other)
    await db_session.commit()
    await _digest(db_session, other, admin_user, start=date(2026, 8, 1), end=date(2026, 8, 31),
                  body="DE-OTRO-CLIENTE", events=[(ExternalDeliveryAction.confirmed, t0)])

    token = await _create(admin_client, client_row.id)
    r = await public.get(f"/api/public/clients/{token}")
    digests = r.json()["digests"]
    assert [d["period_start"] for d in digests] == ["2026-08-01"]
    assert "AGOSTO-V2" in digests[0]["html"] and digests[0]["delivered_at"].startswith("2026-10-03")
    for leaked in ("BORRADOR-SEPTIEMBRE", "REVOCADO-JULIO", "AGOSTO-V1", "DE-OTRO-CLIENTE", "SECRETO-RAW"):
        assert leaked not in r.text


async def test_traffic_is_monthly_only_closed_months_and_weighted_position(admin_client, public, db_session, client_row):
    rows = []
    day = date(2025, 4, 1)
    while day <= date(2026, 10, 15):
        rows.append(GscDaily(site_url=SITE, date=day, clicks=10, impressions=100, position=10.0))
        day += timedelta(days=1)
    # Septiembre: un día con muchas impresiones en posición 2 pesa más.
    rows.append(GscDaily(site_url="sc-domain:otro.com", date=date(2026, 9, 1), clicks=999, impressions=999, position=1))
    db_session.add_all(rows)
    await db_session.flush()
    await db_session.execute(text(
        "UPDATE gsc_daily SET impressions=2900, position=2 WHERE site_url=:s AND date='2026-09-30'"), {"s": SITE})
    db_session.add(GscSiteSync(site_url=SITE, last_data_date=date(2026, 10, 15),
                               backfilled_at=datetime.now(UTC)))
    await db_session.commit()

    token = await _create(admin_client, client_row.id)
    traffic = (await public.get(f"/api/public/clients/{token}")).json()["traffic"]
    months = traffic["months"]
    assert len(months) == 16
    assert months[0]["month"] == "2025-06" and months[-1]["month"] == "2026-09"
    assert traffic["complete_through"] == "2026-09-30"
    sept = months[-1]
    assert sept == {"month": "2026-09", "clicks": 300, "impressions": 29 * 100 + 2900,
                    "position": round((29 * 100 * 10 + 2900 * 2) / (29 * 100 + 2900), 1)}


async def test_without_search_console_there_is_no_traffic_block(admin_client, public, db_session):
    client = Client(name="Sin GSC", status=ClientStatus.active)
    db_session.add(client)
    await db_session.commit()
    token = await _create(admin_client, client.id)
    body = (await public.get(f"/api/public/clients/{token}")).json()
    assert body["traffic"] is None and body["digests"] == []


async def test_last_view_is_recorded_once_per_hour(admin_client, public, db_session, client_row):
    client_id = client_row.id
    token = await _create(admin_client, client_id)
    await public.get(f"/api/public/clients/{token}")
    first = await db_session.scalar(select(ClientShareLink.last_viewed_at))
    assert first is not None
    await public.get(f"/api/public/clients/{token}")
    db_session.expire_all()
    assert await db_session.scalar(select(ClientShareLink.last_viewed_at)) == first
    status = (await admin_client.get(f"/api/clients/{client_id}/share-link")).json()
    assert status["last_viewed_at"] is not None


async def test_public_view_is_rate_limited(admin_client, public, client_row):
    token = await _create(admin_client, client_row.id)
    codes = [(await public.get(f"/api/public/clients/{token}")).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429


async def test_managing_the_link_follows_client_and_digest_permissions(make_member_client, client_row):
    reader = await make_member_client([("clients", True, False), ("digests", True, False)])
    writer_without_digests = await make_member_client([("clients", True, True)])
    writer = await make_member_client([("clients", True, True), ("digests", True, False)])
    nobody = await make_member_client([])
    try:
        assert (await reader.get(f"/api/clients/{client_row.id}/share-link")).status_code == 200
        assert (await reader.post(f"/api/clients/{client_row.id}/share-link")).status_code == 403
        assert (await reader.delete(f"/api/clients/{client_row.id}/share-link")).status_code == 403
        assert (await writer_without_digests.post(f"/api/clients/{client_row.id}/share-link")).status_code == 403
        assert (await nobody.get(f"/api/clients/{client_row.id}/share-link")).status_code == 403
        assert (await writer.post(f"/api/clients/{client_row.id}/share-link")).status_code == 201
        assert (await writer.post("/api/clients/999999/share-link")).status_code == 404
        assert (await writer.delete(f"/api/clients/{client_row.id}/share-link")).status_code == 204
    finally:
        for c in (reader, writer_without_digests, writer, nobody):
            await c.aclose()


async def test_one_active_link_per_client_is_enforced_by_the_database(db_session, client_row, admin_user):
    db_session.add(ClientShareLink(client_id=client_row.id, token_hash="a" * 64, created_by=admin_user.id))
    await db_session.flush()
    db_session.add(ClientShareLink(client_id=client_row.id, token_hash="b" * 64, created_by=admin_user.id))
    with pytest.raises(Exception):
        await db_session.flush()
