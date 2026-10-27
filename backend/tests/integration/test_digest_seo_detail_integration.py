"""Foto del mes de Search Console en el resumen mensual, contra Postgres real:
se calcula al pintar un borrador, se congela al entregarlo, la lee el enlace del
cliente y sigue la retención del detalle."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.core.rate_limiter import pdf_export_limiter, public_link_limiter, public_pdf_limiter
from backend.db.models import (
    Client, ClientStatus, DigestExternalDeliveryEvent, DigestSeoDetail, DigestStatus,
    ExternalDeliveryAction, GscDaily, GscDetailSync, GscPageDaily, GscQueryDaily, GscSiteSync,
    WeeklyDigest,
)
from backend.services import digest_seo_detail, gsc_detail_service

pytestmark = pytest.mark.integration

SITE = "https://www.fit.es/"
TODAY = date(2026, 10, 27)
SEO = {
    "status": "ok", "site_url": SITE,
    "month": {"start": "2026-09-01", "end": "2026-09-30", "days": 30, "clicks": 1000,
              "impressions": 30000, "ctr": 3.33, "position": 7.5},
    "previous": None, "year_ago": None, "vs_previous": None, "vs_year_ago": None,
}


@pytest_asyncio.fixture(autouse=True)
async def _setup(monkeypatch):
    monkeypatch.setattr(digest_seo_detail, "business_today", lambda: TODAY)
    for limiter in (pdf_export_limiter, public_pdf_limiter, public_link_limiter):
        limiter._limiter._requests.clear()
    yield
    for limiter in (pdf_export_limiter, public_pdf_limiter, public_link_limiter):
        limiter._limiter._requests.clear()


@pytest_asyncio.fixture
async def public(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as c:
        yield c


def _days(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


@pytest_asyncio.fixture
async def fit(db_session):
    """Cliente con agosto y septiembre enteros en el detalle."""
    client = Client(name="Fit Generation", status=ClientStatus.active, gsc_url=SITE, brand_terms=["Fit"])
    db_session.add(client)
    synced = datetime(2026, 10, 26, 6, tzinfo=UTC)
    db_session.add(GscSiteSync(site_url=SITE, backfilled_at=synced, last_synced_at=synced,
                               last_data_date=date(2026, 10, 24)))
    db_session.add(GscDetailSync(site_url=SITE, backfilled_at=synced, last_synced_at=synced,
                                 last_data_date=date(2026, 10, 24)))
    for day in _days(date(2026, 8, 1), date(2026, 9, 30)):
        september = day.month == 9
        db_session.add(GscDaily(site_url=SITE, date=day, clicks=40 if september else 30,
                                impressions=1000, position=7.5))
        db_session.add(GscQueryDaily(site_url=SITE, date=day, query="rutina gimnasio",
                                     clicks=20 if september else 10, impressions=300, position=3.0))
        db_session.add(GscQueryDaily(site_url=SITE, date=day, query="fit generation",
                                     clicks=10, impressions=50, position=1.0))
        db_session.add(GscQueryDaily(site_url=SITE, date=day, query="dieta definicion",
                                     clicks=1, impressions=200, position=12.0))
        db_session.add(GscPageDaily(site_url=SITE, date=day, page="https://www.fit.es/rutinas/",
                                    clicks=20 if september else 10, impressions=300, position=3.0))
    await db_session.commit()
    return client


async def _digest(db, client, user, *, delivered=False, start=date(2026, 9, 1), end=date(2026, 9, 30)):
    digest = WeeklyDigest(
        client_id=client.id, period_start=start, period_end=end, status=DigestStatus.draft,
        content={"greeting": "Hola", "sections": {"done": [{"title": "Hecho", "description": "x"}]},
                 "closing": "Un saludo"},
        created_by=user.id, raw_context={"seo": SEO},
    )
    db.add(digest)
    await db.flush()
    if delivered:
        await _deliver(db, digest, user)
    await db.commit()
    return digest


async def _deliver(db, digest, user):
    db.add(DigestExternalDeliveryEvent(
        digest_id=digest.id, action=ExternalDeliveryAction.confirmed, actor_id=user.id,
        request_key=f"k-{digest.id}", request_hash="0" * 64,
        created_at=datetime(2026, 10, 2, 9, tzinfo=UTC).replace(tzinfo=None)))
    await db.commit()


async def _email(admin_client, digest_id) -> str:
    r = await admin_client.get(f"/api/digests/{digest_id}/render", params={"format": "email"})
    assert r.status_code == 200, r.text
    return r.json()["rendered"]


async def test_un_borrador_lleva_la_foto_y_se_guarda(admin_client, db_session, fit, admin_user):
    digest = await _digest(db_session, fit, admin_user)
    html = await _email(admin_client, digest.id)
    assert "Búsquedas que más visitas trajeron" in html and "rutina gimnasio" in html
    assert "Frente a agosto" in html and "+93,5 %" in html  # 600 clics frente a 310
    assert "dieta definicion" in html  # oportunidad: posición 12 con 6.000 impresiones

    stored = await db_session.get(DigestSeoDetail, digest.id)
    assert stored is not None and stored.site_url == SITE
    detail = stored.payload
    assert [q["key"] for q in detail["queries"]] == ["rutina gimnasio", "fit generation", "dieta definicion"]
    assert detail["brand"] == {"brand": 300, "non_brand": 630, "unclassified": 270,
                               "previous": {"brand": 310, "non_brand": 341, "unclassified": 279},
                               "non_brand_pct": 84.8, "brand_pct": -3.2}

    # El editor la recibe junto a los totales; el raw_context guardado no cambia.
    body = (await admin_client.get(f"/api/digests/{digest.id}")).json()
    assert body["raw_context"]["seo"]["detail"]["queries"][0]["key"] == "rutina gimnasio"
    await db_session.refresh(digest)
    assert "detail" not in digest.raw_context["seo"]


async def test_mientras_es_borrador_se_recalcula_y_al_entregarlo_se_congela(admin_client, db_session, fit, admin_user):
    digest = await _digest(db_session, fit, admin_user)
    await _email(admin_client, digest.id)
    fit.brand_terms = ["rutina"]
    await db_session.commit()
    html = await _email(admin_client, digest.id)
    assert (await db_session.get(DigestSeoDetail, digest.id, populate_existing=True)).payload["brand"]["brand"] == 600
    assert "rutina gimnasio" in html

    await _deliver(db_session, digest, admin_user)
    fit.brand_terms = []
    await db_session.commit()
    await _email(admin_client, digest.id)
    frozen = await db_session.get(DigestSeoDetail, digest.id, populate_existing=True)
    assert frozen.payload["brand"]["brand"] == 600  # lo que se envió


async def test_lo_entregado_antes_no_gana_el_bloque_y_el_enlace_lee_la_foto(admin_client, public, db_session, fit, admin_user):
    old = await _digest(db_session, fit, admin_user, start=date(2026, 8, 1), end=date(2026, 8, 31), delivered=True)
    current = await _digest(db_session, fit, admin_user)
    await _email(admin_client, current.id)      # foto del borrador
    await _deliver(db_session, current, admin_user)

    assert "Búsquedas que más" not in await _email(admin_client, old.id)
    assert await db_session.get(DigestSeoDetail, old.id) is None

    r = await admin_client.post(f"/api/clients/{fit.id}/share-link")
    token = r.json()["path"].removeprefix("/c/")
    view = (await public.get(f"/api/public/clients/{token}")).json()
    html = {d["id"]: d["html"] for d in view["digests"]}
    assert "rutina gimnasio" in html[current.id] and "Búsquedas que más" not in html[old.id]
    pdf = await public.get(f"/api/public/clients/{token}/digests/{current.id}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")


async def test_sin_el_detalle_del_mes_entero_no_hay_foto(admin_client, db_session, fit, admin_user):
    digest = await _digest(db_session, fit, admin_user)
    await _email(admin_client, digest.id)
    state = await db_session.get(GscDetailSync, SITE)
    state.last_data_date = date(2026, 9, 20)
    await db_session.commit()
    html = await _email(admin_client, digest.id)
    assert "Búsquedas que más" not in html and "Visibilidad en Google" in html
    assert await db_session.get(DigestSeoDetail, digest.id, populate_existing=True) is None


async def test_un_resumen_semanal_no_lleva_foto(admin_client, db_session, fit, admin_user):
    digest = await _digest(db_session, fit, admin_user, start=date(2026, 9, 21), end=date(2026, 9, 27))
    assert digest_seo_detail.is_full_month(digest.period_start, digest.period_end) is False
    await _email(admin_client, digest.id)
    assert await db_session.get(DigestSeoDetail, digest.id) is None


async def test_la_retencion_borra_la_foto_de_una_web_sin_cliente_activo(admin_client, db_session, fit, admin_user):
    digest = await _digest(db_session, fit, admin_user)
    await _email(admin_client, digest.id)
    await gsc_detail_service.prune(db_session, today=TODAY)
    assert await db_session.get(DigestSeoDetail, digest.id, populate_existing=True) is not None
    fit.status = ClientStatus.finished
    await db_session.commit()
    await gsc_detail_service.prune(db_session, today=TODAY)
    assert (await db_session.scalars(select(DigestSeoDetail))).all() == []
