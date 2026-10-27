"""Salud diaria de las webs y revisión tras publicar contra Postgres real:
migración, pasadas del job, incidencias, API y aviso en la campana. Sin red."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from backend.config import settings
from backend.db.models import (
    Base, Client, ClientWebSettings, Notification, Project, ProjectStatus, Task, TaskPublishCheck, TaskStatus,
    User, UserPermission, UserRole, WebHostExpiry, WebRobotsState, WebUptimeTarget, WebWatch,
)
from backend.services.incident_web_conditions import (
    CLIENT_CERT_EXPIRING, CLIENT_DOMAIN_EXPIRING, CLIENT_ROBOTS_BLOCKED, CLIENT_ROBOTS_CHANGED,
    CLIENT_SITEMAP_BROKEN,
)
from backend.services.incidents import reconcile_recipient, visible_incident_clause
from backend.services.notification_checks import visible_notification_condition
from backend.services.web import health, publish_check
from backend.services.web.safe_http import FetchResult, TlsCertificate
from backend.startup import deployment_schema, schema_baseline
from backend.startup.schema_runner import run_schema_migrations
from backend.startup.web_health_schema import MIGRATION, apply, verify

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC).replace(microsecond=0)
BOOTSTRAP = {"services": [[["com"], ["https://rdap.test/com/"]]]}
URLSET = (b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          b"<url><loc>https://ejemplo.com/a</loc></url></urlset>")


class _Factory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


def _res(code=None, body=b"", url="", error=None, headers=None):
    return FetchResult(status_code=code, elapsed_ms=10, final_url=url, body=body, error=error,
                       headers=headers or {})


class Internet:
    """Qué responde cada URL ahora mismo (y qué se pidió)."""

    def __init__(self):
        self.answers: dict[str, FetchResult] = {"https://data.iana.org/rdap/dns.json": _res(
            200, json.dumps(BOOTSTRAP).encode())}
        self.calls: list[str] = []

    def domain(self, name: str, expires: datetime | None):
        events = [{"eventAction": "expiration", "eventDate": expires.isoformat()}] if expires else []
        self.answers[f"https://rdap.test/com/domain/{name}"] = _res(200, json.dumps({"events": events}).encode())

    async def fetch(self, url, **_kw):
        self.calls.append(url)
        found = self.answers.get(url)
        return found if found is not None else _res(404, url=url)


def _certs(mapping):
    async def reader(host, **_kw):
        return mapping.get(host) or TlsCertificate(error="connect")
    return reader


async def _user(db, role=UserRole.member, modules=("web",), write=False):
    user = User(email=f"wh-{uuid4().hex}@test.local", full_name="Persona Web", hashed_password="x", role=role,
                is_active=True)
    db.add(user)
    await db.flush()
    db.add_all([UserPermission(user_id=user.id, module=m, can_read=True, can_write=write) for m in modules])
    await db.flush()
    return user


async def _client(db, name="Tienda Sol", website="https://www.ejemplo.com", changes=False):
    client = Client(name=name, website=website)
    db.add(client)
    await db.flush()
    db.add(ClientWebSettings(client_id=client.id, slack_enabled=False, downtime_to_slack=True,
                             changes_enabled=changes))
    await db.flush()
    return client


async def _incidents(db, user, kind):
    return (await db.execute(select(Notification).where(
        Notification.type == kind, visible_incident_clause(user.id, current_only=True),
    ).execution_options(populate_existing=True))).scalars().all()


# ── Migración ────────────────────────────────────────────────────────


async def _reset(engine):
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@pytest_asyncio.fixture
async def clean_schema(engine):
    await _reset(engine)
    yield
    await _reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "CREATE UNIQUE INDEX uq_time_entries_active_timer ON time_entries(user_id) WHERE minutes IS NULL"))


async def test_migracion_subida_instalacion_limpia_y_orm(engine, clean_schema):
    prior = deployment_schema.MIGRATIONS[:deployment_schema.MIGRATIONS.index(MIGRATION)]
    await run_schema_migrations(engine, prior, schema_baseline.preflight)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.migrate_schema(engine)
    await deployment_schema.check_deployment_ready(engine)
    async with engine.begin() as conn:
        await apply(conn)
        await verify(conn)
    await _reset(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await verify(conn)


# ── Caducidad de certificado y dominio ───────────────────────────────


async def test_caducidades_se_guardan_avisan_y_se_resuelven(db_session):
    admin = await _user(db_session, role=UserRole.admin, modules=())
    owner = await _user(db_session)
    stranger = await _user(db_session)
    client = await _client(db_session)
    db_session.add(Project(name="SEO", client_id=client.id, owner_id=owner.id, status=ProjectStatus.active))
    db_session.add_all([
        WebUptimeTarget(client_id=client.id, url="https://www.ejemplo.com/", is_active=True),
        WebUptimeTarget(client_id=client.id, url="http://tienda.ejemplo.com/", is_active=True),
    ])
    await db_session.flush()
    net = Internet()
    net.domain("ejemplo.com", NOW + timedelta(days=5, hours=1))
    certs = {"www.ejemplo.com": TlsCertificate(not_after=NOW + timedelta(days=10, hours=1), issuer="R3",
                                               verified=True)}

    result = await health.run_cycle(_Factory(db_session), now=NOW, fetcher=net.fetch, cert_reader=_certs(certs),
                                    expiry=True, robots=False)
    assert result.hosts == 2 and not result.bootstrap_failed
    rows = {r.host: r for r in (await db_session.scalars(select(WebHostExpiry)
                                                          .where(WebHostExpiry.client_id == client.id))).all()}
    assert rows["www.ejemplo.com"].cert_status == "ok" and rows["www.ejemplo.com"].cert_issuer == "R3"
    assert rows["tienda.ejemplo.com"].cert_status == "no_https"  # sólo URL http: ni se intenta
    assert rows["www.ejemplo.com"].domain_name == "ejemplo.com"
    # tienda.ejemplo.com da 404 en RDAP y cae a ejemplo.com: una sola fecha de dominio.
    assert rows["tienda.ejemplo.com"].domain_expires_at == rows["www.ejemplo.com"].domain_expires_at

    now_naive = NOW.replace(tzinfo=None)
    for person in (admin, owner, stranger):
        await reconcile_recipient(db_session, person.id, now=now_naive)
    (cert,) = await _incidents(db_session, admin, CLIENT_CERT_EXPIRING)
    assert cert.incident_severity == "warning" and "www.ejemplo.com caduca en 10 días" in cert.message
    (domain,) = await _incidents(db_session, owner, CLIENT_DOMAIN_EXPIRING)
    assert domain.incident_severity == "critical" and domain.message.count("ejemplo.com caduca en 5 días") == 1
    assert domain.link_url == f"/clients/{client.id}?tab=web"
    assert await _incidents(db_session, stranger, CLIENT_DOMAIN_EXPIRING) == []

    # Se renuevan: la pasada siguiente guarda las fechas nuevas y las incidencias se resuelven.
    net.domain("ejemplo.com", NOW + timedelta(days=365))
    certs["www.ejemplo.com"] = TlsCertificate(not_after=NOW + timedelta(days=89), issuer="R3", verified=True)
    await health.run_cycle(_Factory(db_session), now=NOW, fetcher=net.fetch, cert_reader=_certs(certs),
                           expiry=True, robots=False)
    await reconcile_recipient(db_session, admin.id, now=now_naive)
    assert await _incidents(db_session, admin, CLIENT_CERT_EXPIRING) == []
    assert await _incidents(db_session, admin, CLIENT_DOMAIN_EXPIRING) == []

    # Un host que ya no se vigila desaparece en la pasada siguiente.
    target = await db_session.scalar(select(WebUptimeTarget).where(WebUptimeTarget.url == "http://tienda.ejemplo.com/"))
    target.is_active = False
    await db_session.flush()
    await health.run_cycle(_Factory(db_session), now=NOW, fetcher=net.fetch, cert_reader=_certs(certs),
                           expiry=True, robots=False)
    hosts = (await db_session.scalars(select(WebHostExpiry.host).where(WebHostExpiry.client_id == client.id))).all()
    assert hosts == ["www.ejemplo.com"]


# ── robots.txt y sitemap ─────────────────────────────────────────────


async def test_robots_bloqueo_cambio_revision_y_sitemap(db_session, make_member_client):
    admin = await _user(db_session, role=UserRole.admin, modules=())
    client = await _client(db_session, changes=True)
    other = await _client(db_session, name="Sin vigilancia", website="https://otra.com", changes=False)
    db_session.add(WebWatch(client_id=client.id, url="https://www.ejemplo.com/servicios", source="manual"))
    await db_session.flush()
    net = Internet()
    origin = "https://www.ejemplo.com"
    net.answers[f"{origin}/robots.txt"] = _res(200, b"User-agent: *\nDisallow: /admin/\n"
                                                     b"Sitemap: https://www.ejemplo.com/s.xml\n")
    net.answers[f"{origin}/s.xml"] = _res(200, URLSET)

    await health.run_cycle(_Factory(db_session), now=NOW, fetcher=net.fetch, expiry=False, robots=True)
    row = await db_session.get(WebRobotsState, (client.id, origin))
    assert row.robots_status == "ok" and not row.robots_blocks_all and row.robots_changed_at is None
    assert (row.sitemap_source, row.sitemap_status, row.sitemap_url_count) == ("declared", "ok", 1)
    assert await db_session.get(WebRobotsState, (other.id, "https://otra.com")) is None
    assert "https://otra.com/robots.txt" not in net.calls

    # Alguien publica «Disallow: /» y quita el sitemap.
    net.answers[f"{origin}/robots.txt"] = _res(200, b"User-agent: *\nDisallow: /\n")
    later = NOW + timedelta(days=1)
    await health.run_cycle(_Factory(db_session), now=later, fetcher=net.fetch, expiry=False, robots=True)
    await db_session.refresh(row)
    assert row.robots_blocks_all and row.robots_changed_at == later and "Disallow: /admin/" in row.robots_previous_body
    assert (row.sitemap_source, row.sitemap_status) == ("default", "error")

    now_naive = later.replace(tzinfo=None)
    await reconcile_recipient(db_session, admin.id, now=now_naive)
    (blocked,) = await _incidents(db_session, admin, CLIENT_ROBOTS_BLOCKED)
    assert blocked.incident_severity == "critical" and "Disallow: /" in blocked.message
    (changed,) = await _incidents(db_session, admin, CLIENT_ROBOTS_CHANGED)
    assert changed.incident_severity == "warning"
    (sitemap,) = await _incidents(db_session, admin, CLIENT_SITEMAP_BROKEN)
    assert "https://www.ejemplo.com/sitemap.xml: no responde (error HTTP 404)" in sitemap.message

    # API: leer con permiso de web; revisar sólo con escritura.
    reader = await make_member_client([("web", True, False)])
    writer = await make_member_client([("web", True, True)])
    nobody = await make_member_client([("clients", True, True)])
    base = f"/api/clients/{client.id}/web"
    assert (await nobody.get(f"{base}/health")).status_code == 403
    body = (await reader.get(f"{base}/health")).json()
    (robots,) = body["robots"]
    assert robots["blocks_all"] and robots["pending_review"] and robots["sitemap"]["status"] == "error"
    assert (await reader.post(f"{base}/robots/review", json={"origin": origin})).status_code == 403
    assert (await writer.post(f"{base}/robots/review", json={"origin": "https://nada.com"})).status_code == 404
    assert (await writer.post(f"{base}/robots/review", json={"origin": origin})).status_code == 200
    reviewed = (await reader.get(f"{base}/health")).json()["robots"][0]
    assert not reviewed["pending_review"] and reviewed["reviewed_by"] == writer.test_user.full_name
    await reconcile_recipient(db_session, admin.id, now=now_naive)
    assert await _incidents(db_session, admin, CLIENT_ROBOTS_CHANGED) == []
    assert len(await _incidents(db_session, admin, CLIENT_ROBOTS_BLOCKED)) == 1  # el bloqueo sigue

    # Apagar la vigilancia de cambios: ni API ni incidencias de robots.
    settings_row = await db_session.get(ClientWebSettings, client.id)
    settings_row.changes_enabled = False
    await db_session.flush()
    assert (await reader.get(f"{base}/health")).json()["robots"] == []
    await reconcile_recipient(db_session, admin.id, now=now_naive)
    assert await _incidents(db_session, admin, CLIENT_ROBOTS_BLOCKED) == []


# ── Revisión tras publicar ───────────────────────────────────────────

GOOD = (b'<html><head><title>Guia</title><meta name="description" content="Desc">'
        b'<link rel="canonical" href="https://www.ejemplo.com/guia"></head></html>')


async def _task(db, client, assignee, link, *, minutes_ago=5):
    task = Task(title="Publicar la guía", client_id=client.id, assigned_to=assignee.id, link_url=link,
                status=TaskStatus.completed,
                completed_at=(NOW - timedelta(minutes=minutes_ago)).replace(tzinfo=None))
    db.add(task)
    await db.flush()
    return task


async def test_revision_tras_publicar(db_session, make_member_client, monkeypatch):
    client = await _client(db_session)
    owner = await _user(db_session, modules=("tasks",))
    good = await _task(db_session, client, owner, "https://www.ejemplo.com/guia")
    broken = await _task(db_session, client, owner, "https://ejemplo.com/rota")
    doc = await _task(db_session, client, owner, "https://docs.google.com/document/d/1")
    slow = await _task(db_session, client, owner, "https://www.ejemplo.com/lenta")
    old = await _task(db_session, client, owner, "https://www.ejemplo.com/vieja", minutes_ago=60 * 24 * 5)
    net = Internet()
    net.answers["https://www.ejemplo.com/guia"] = _res(200, GOOD, url="https://www.ejemplo.com/guia")
    net.answers["https://ejemplo.com/rota"] = _res(200, b"<html><head><title>x</title></head></html>",
                                                   url="https://ejemplo.com/rota",
                                                   headers={"x-robots-tag": "noindex"})
    net.answers["https://www.ejemplo.com/lenta"] = _res(error="timeout")

    result = await publish_check.run_cycle(_Factory(db_session), now=NOW, fetcher=net.fetch)
    assert result.due == 4 and result.failed == 0
    checks = {c.task_id: c for c in (await db_session.scalars(select(TaskPublishCheck))).all()}
    assert old.id not in checks
    assert checks[good.id].status == "ok"
    assert checks[broken.id].status == "problems"
    assert (checks[doc.id].status, checks[doc.id].error) == ("skipped", "other_site")
    assert "https://docs.google.com/document/d/1" not in net.calls
    assert checks[slow.id].status == "pending" and checks[slow.id].next_attempt_at == NOW + timedelta(minutes=2)

    notes = (await db_session.scalars(select(Notification).where(
        Notification.user_id == owner.id, Notification.type == "task_publish_check",
        visible_notification_condition(owner.id)))).all()
    assert [n.entity_id for n in notes] == [broken.id]
    assert "noindex" in notes[0].message and notes[0].link_url == f"/tasks?task={broken.id}"

    # Una segunda pasada no repite nada; los reintentos siguen su calendario hasta rendirse.
    assert (await publish_check.run_cycle(_Factory(db_session), now=NOW, fetcher=net.fetch)).due == 0
    at = NOW
    for delay in (2, 10, 30):
        at += timedelta(minutes=delay)
        await publish_check.run_cycle(_Factory(db_session), now=at, fetcher=net.fetch)
    await db_session.refresh(checks[slow.id])
    assert checks[slow.id].status == "unreachable" and checks[slow.id].attempts == 4
    notes = (await db_session.scalars(select(Notification).where(
        Notification.user_id == owner.id, Notification.type == "task_publish_check"))).all()
    assert sorted(n.entity_id for n in notes) == sorted([broken.id, slow.id])

    # API: leer con tareas; volver a comprobar con escritura y el job encendido.
    reader = await make_member_client([("tasks", True, False)])
    writer = await make_member_client([("tasks", True, True)])
    view = (await reader.get(f"/api/tasks/{broken.id}/publish-check")).json()
    assert view["status"] == "problems" and any(not c["ok"] and c["code"] == "indexable" for c in view["results"])
    assert (await reader.get(f"/api/tasks/{doc.id}/publish-check")).json()["error"].startswith("El enlace no es de la web")
    assert (await reader.post(f"/api/tasks/{broken.id}/publish-check")).status_code == 403
    monkeypatch.setattr(settings, "PUBLISH_CHECK_ENABLED", False)
    assert (await writer.post(f"/api/tasks/{broken.id}/publish-check")).status_code == 409
    monkeypatch.setattr(settings, "PUBLISH_CHECK_ENABLED", True)
    queued = await writer.post(f"/api/tasks/{broken.id}/publish-check")
    assert queued.status_code == 200 and queued.json()["status"] == "pending"
    net.answers["https://ejemplo.com/rota"] = _res(200, GOOD.replace(b"www.ejemplo.com/guia", b"ejemplo.com/rota"),
                                                   url="https://ejemplo.com/rota")
    await publish_check.run_cycle(_Factory(db_session), now=datetime.now(UTC) + timedelta(seconds=5),
                                  fetcher=net.fetch)
    assert (await reader.get(f"/api/tasks/{broken.id}/publish-check")).json()["status"] == "ok"

    # Reabrir la tarea deja la revisión sin efecto hasta que se vuelva a completar.
    good.status, good.completed_at = TaskStatus.in_progress, None
    await db_session.flush()
    assert (await reader.get(f"/api/tasks/{good.id}/publish-check")).json()["status"] == "none"
