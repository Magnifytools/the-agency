"""Descargar el resumen en PDF (con sesión y desde el enlace del cliente) contra Postgres real."""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.core.rate_limiter import pdf_export_limiter, public_link_limiter, public_pdf_limiter
from backend.db.models import (
    Client,
    ClientStatus,
    DigestExternalDeliveryEvent,
    DigestStatus,
    ExternalDeliveryAction,
    WeeklyDigest,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def _fresh_limiters():
    for limiter in (pdf_export_limiter, public_pdf_limiter, public_link_limiter):
        limiter._limiter._requests.clear()
    yield
    for limiter in (pdf_export_limiter, public_pdf_limiter, public_link_limiter):
        limiter._limiter._requests.clear()


@pytest_asyncio.fixture
async def public(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def client_row(db_session):
    client = Client(name="Fit Generation", status=ClientStatus.active)
    db_session.add(client)
    await db_session.commit()
    return client


async def _digest(db, client, user, *, start=date(2026, 9, 1), end=date(2026, 9, 30), delivered=False,
                  body="Hecho de septiembre"):
    digest = WeeklyDigest(
        client_id=client.id, period_start=start, period_end=end, status=DigestStatus.draft,
        content={"greeting": "Hola", "sections": {"done": [{"title": body, "description": "detalle"}]},
                 "closing": "Un saludo"},
        created_by=user.id, raw_context={"seo": None},
    )
    db.add(digest)
    await db.flush()
    if delivered:
        db.add(DigestExternalDeliveryEvent(
            digest_id=digest.id, action=ExternalDeliveryAction.confirmed, actor_id=user.id,
            request_key=f"k-{digest.id}", request_hash="0" * 64,
            created_at=datetime(2026, 10, 2, 9, tzinfo=UTC).replace(tzinfo=None)))
    await db.commit()
    return digest


def _assert_pdf(response, filename: str):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == f'attachment; filename="{filename}"'
    assert response.headers["cache-control"] == "no-store"
    assert response.content.startswith(b"%PDF-") and len(response.content) > 1500


async def test_admin_downloads_the_pdf(admin_client, db_session, client_row, admin_user):
    digest = await _digest(db_session, client_row, admin_user)
    _assert_pdf(await admin_client.get(f"/api/digests/{digest.id}/pdf"),
                "informe-fit-generation-2026-09.pdf")


async def test_pdf_follows_the_digest_access_rules(make_member_client, db_session, client_row, admin_user):
    digest = await _digest(db_session, client_row, admin_user)
    stranger = await make_member_client([("digests", True, False)])
    no_module = await make_member_client([])
    author = await make_member_client([("digests", True, False)])
    own = await _digest(db_session, client_row, author.test_user, start=date(2026, 8, 1), end=date(2026, 8, 31))
    try:
        # Lee resúmenes pero ni lo creó ni es responsable del cliente.
        assert (await stranger.get(f"/api/digests/{digest.id}/pdf")).status_code == 403
        assert (await no_module.get(f"/api/digests/{digest.id}/pdf")).status_code == 403
        assert (await stranger.get("/api/digests/999999/pdf")).status_code == 404
        _assert_pdf(await author.get(f"/api/digests/{own.id}/pdf"), "informe-fit-generation-2026-08.pdf")
    finally:
        for c in (stranger, no_module, author):
            await c.aclose()


async def test_pdf_without_content_is_400(admin_client, db_session, client_row, admin_user):
    digest = await _digest(db_session, client_row, admin_user)
    digest.content = None
    await db_session.commit()
    assert (await admin_client.get(f"/api/digests/{digest.id}/pdf")).status_code == 400


async def test_pdf_is_rate_limited_per_user(admin_client, db_session, client_row, admin_user):
    digest = await _digest(db_session, client_row, admin_user)
    codes = [(await admin_client.get(f"/api/digests/{digest.id}/pdf")).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


async def _token(admin_client, client_id) -> str:
    r = await admin_client.post(f"/api/clients/{client_id}/share-link")
    assert r.status_code == 201, r.text
    return r.json()["path"].removeprefix("/c/")


async def test_public_link_downloads_only_delivered_digests(admin_client, public, db_session, client_row, admin_user):
    delivered = await _digest(db_session, client_row, admin_user, delivered=True)
    draft = await _digest(db_session, client_row, admin_user, start=date(2026, 8, 1), end=date(2026, 8, 31))
    other = Client(name="Otro", status=ClientStatus.active)
    db_session.add(other)
    await db_session.commit()
    others = await _digest(db_session, other, admin_user, delivered=True)
    token = await _token(admin_client, client_row.id)

    view = (await public.get(f"/api/public/clients/{token}")).json()
    assert [d["id"] for d in view["digests"]] == [delivered.id]

    ok = await public.get(f"/api/public/clients/{token}/digests/{delivered.id}/pdf")
    _assert_pdf(ok, "informe-fit-generation-2026-09.pdf")
    assert "noindex" in ok.headers["x-robots-tag"] and ok.headers["referrer-policy"] == "no-referrer"

    misses = [
        await public.get(f"/api/public/clients/{token}/digests/{draft.id}/pdf"),
        await public.get(f"/api/public/clients/{token}/digests/{others.id}/pdf"),
        await public.get(f"/api/public/clients/{'x' * 43}/digests/{delivered.id}/pdf"),
        await public.get(f"/api/public/clients/corto/digests/{delivered.id}/pdf"),
    ]
    assert {r.status_code for r in misses} == {404}
    assert len({r.text for r in misses}) == 1
    assert all("noindex" in r.headers["x-robots-tag"] for r in misses)

    assert (await admin_client.delete(f"/api/clients/{client_row.id}/share-link")).status_code == 204
    assert (await public.get(f"/api/public/clients/{token}/digests/{delivered.id}/pdf")).status_code == 404


async def test_public_pdf_is_rate_limited_per_ip(admin_client, public, db_session, client_row, admin_user):
    delivered = await _digest(db_session, client_row, admin_user, delivered=True)
    token = await _token(admin_client, client_row.id)
    url = f"/api/public/clients/{token}/digests/{delivered.id}/pdf"
    codes = [(await public.get(url)).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429
