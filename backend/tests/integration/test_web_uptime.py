"""Monitor de caídas contra Postgres real: ciclo del job, outbox de Slack,
incidencias, estado del cliente, retención y permisos del API. Sin red."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from backend.config import settings
from backend.core.security import decrypt_vault_secret, encrypt_vault_secret
from backend.db.models import (
    Client, ClientStatus, ClientWebSettings, Notification, Project, ProjectStatus, User, UserPermission,
    UserRole, WebOutage, WebUptimeProbe, WebUptimeState, WebUptimeTarget,
)
from backend.services.client_status import Viewer, portfolio
from backend.services.incident_web_conditions import CLIENT_SITE_BLOCKED, CLIENT_SITE_DOWN
from backend.services.incidents import reconcile_recipient, visible_incident_clause
from backend.services.web import uptime
from backend.services.web.safe_http import FetchResult
from backend.services.web.slack import DeliveryResult

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 21, 8, 0, tzinfo=UTC)
HOOK = "https://hooks.slack.com/services/T0/B1/abc123"
CANARY = "https://canary.test/"


class _Factory:
    """async_session de mentira que devuelve la sesión del test (sin cerrarla)."""

    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def uptime_settings(monkeypatch):
    monkeypatch.setattr(settings, "UPTIME_CANARY_URLS", CANARY)
    monkeypatch.setattr(settings, "UPTIME_INTERVAL_SECONDS", 300)
    monkeypatch.setattr(settings, "UPTIME_RECHECK_SECONDS", 60)
    monkeypatch.setattr(settings, "UPTIME_FAILURES_TO_ALERT", 2)
    monkeypatch.setattr(settings, "UPTIME_RECOVERIES_TO_CLOSE", 2)
    monkeypatch.setattr(settings, "UPTIME_BLOCKED_ALERT_MINUTES", 60)


def _ok(code=200):
    return FetchResult(status_code=code, elapsed_ms=80, final_url="")


def _err(kind="timeout"):
    return FetchResult(status_code=None, elapsed_ms=15000, final_url="", error=kind)


class Web:
    """Internet de mentira: qué responde cada URL en este momento."""

    def __init__(self):
        self.answers: dict[str, FetchResult] = {}
        self.canary = _ok(204)
        self.calls: list[str] = []

    async def fetch(self, url, **_kw):
        self.calls.append(url)
        if url == CANARY:
            return self.canary
        return self.answers[url]


class Slack:
    def __init__(self):
        self.messages: list[tuple[str, str]] = []
        self.reply = DeliveryResult(ok=True, status=200)

    async def post(self, webhook, text, blocks=None):
        self.messages.append((webhook, text + " | " + (blocks[0]["text"]["text"] if blocks else "")))
        return self.reply


async def _no_sleep(_seconds):
    return None


async def _client(db, *, name=None, slack=True, **fields):
    client = Client(name=name or f"Cliente {uuid4().hex[:6]}", website="https://ejemplo.com", **fields)
    db.add(client)
    await db.flush()
    if slack:
        db.add(ClientWebSettings(client_id=client.id, slack_webhook_url=encrypt_vault_secret(HOOK),
                                 slack_enabled=True, downtime_to_slack=True))
    await db.flush()
    return client


async def _target(db, client, url=None):
    target = WebUptimeTarget(client_id=client.id, url=url or f"https://{uuid4().hex[:8]}.com/", label="Home")
    db.add(target)
    await db.flush()
    db.add(WebUptimeState(target_id=target.id, status="unknown", next_check_at=T0 - timedelta(seconds=1)))
    await db.flush()
    return target


async def _cycle(db, web, slack, at):
    return await uptime.run_cycle(_Factory(db), now=at, fetcher=web.fetch, sleep=_no_sleep, post=slack.post)


async def _outages(db, target):
    return (await db.scalars(select(WebOutage).where(WebOutage.target_id == target.id)
                             .order_by(WebOutage.id).execution_options(populate_existing=True))).all()


async def _state(db, target):
    return (await db.execute(select(WebUptimeState).where(WebUptimeState.target_id == target.id)
                             .execution_options(populate_existing=True))).scalar_one()


# ── Ciclo del job ────────────────────────────────────────────────────


async def test_caida_confirmada_avisa_a_slack_y_la_recuperacion_cierra_con_duracion(db_session):
    client = await _client(db_session, name="Fit Generation")
    target = await _target(db_session, client)
    web, slack = Web(), Slack()

    web.answers[target.url] = _err("timeout")
    await _cycle(db_session, web, slack, T0)
    state = await _state(db_session, target)
    assert state.status == "suspect" and await _outages(db_session, target) == []
    assert state.next_check_at == T0 + timedelta(seconds=60)
    # El fallo se reintenta dentro del ciclo: dos peticiones a la web.
    assert web.calls.count(target.url) == 2

    result = await _cycle(db_session, web, slack, T0 + timedelta(seconds=60))
    assert result.opened == 1
    (outage,) = await _outages(db_session, target)
    assert outage.kind == "down" and outage.started_at == T0 and outage.ended_at is None
    assert outage.cause == "timeout" and outage.slack_down_status == "sent"
    assert len(slack.messages) == 1
    webhook, message = slack.messages[0]
    assert webhook == HOOK and "La web de Fit Generation no responde" in message and "10:00" in message

    web.answers[target.url] = _ok()
    await _cycle(db_session, web, slack, T0 + timedelta(seconds=120))
    assert (await _state(db_session, target)).status == "down"
    await _cycle(db_session, web, slack, T0 + timedelta(seconds=180))
    (outage,) = await _outages(db_session, target)
    assert outage.ended_at == T0 + timedelta(seconds=180) and outage.slack_recovery_status == "sent"
    assert len(slack.messages) == 2 and "vuelve a responder" in slack.messages[1][1]
    assert "caída de 3 min" in slack.messages[1][1]
    state = await _state(db_session, target)
    assert state.status == "up" and state.next_check_at == T0 + timedelta(seconds=180 + 300)
    probes = await db_session.scalar(select(func.count()).select_from(WebUptimeProbe)
                                     .where(WebUptimeProbe.target_id == target.id))
    assert probes == 4


async def test_sin_slack_la_caida_queda_en_la_app_y_no_se_avisa(db_session):
    client = await _client(db_session, slack=False)
    target = await _target(db_session, client)
    web, slack = Web(), Slack()
    web.answers[target.url] = _ok(503)
    await _cycle(db_session, web, slack, T0)
    await _cycle(db_session, web, slack, T0 + timedelta(seconds=60))
    (outage,) = await _outages(db_session, target)
    assert outage.slack_down_status == "skipped" and outage.cause == "http_503" and slack.messages == []


async def test_webhook_revocado_apaga_slack_del_cliente(db_session):
    client = await _client(db_session)
    target = await _target(db_session, client)
    web, slack = Web(), Slack()
    slack.reply = DeliveryResult(ok=False, status=404, revoked=True, error="gone")
    web.answers[target.url] = _err("connect")
    await _cycle(db_session, web, slack, T0)
    await _cycle(db_session, web, slack, T0 + timedelta(seconds=60))
    (outage,) = await _outages(db_session, target)
    assert outage.slack_down_status == "failed"
    settings_row = (await db_session.execute(select(ClientWebSettings).where(
        ClientWebSettings.client_id == client.id).execution_options(populate_existing=True))).scalar_one()
    assert settings_row.slack_enabled is False and settings_row.slack_revoked_at is not None


async def test_fallo_transitorio_de_slack_se_reintenta_en_el_siguiente_ciclo(db_session):
    client = await _client(db_session)
    target = await _target(db_session, client)
    web, slack = Web(), Slack()
    slack.reply = DeliveryResult(ok=False, status=500, error="boom")
    web.answers[target.url] = _err("dns")
    await _cycle(db_session, web, slack, T0)
    await _cycle(db_session, web, slack, T0 + timedelta(seconds=60))
    (outage,) = await _outages(db_session, target)
    assert outage.slack_down_status == "pending" and outage.slack_attempts == 1
    slack.reply = DeliveryResult(ok=True, status=200)
    # Ciclo sin nada que mirar (la siguiente comprobación es a los 60 s): sólo el outbox.
    result = await _cycle(db_session, web, slack, T0 + timedelta(seconds=61))
    assert result.slack["sent"] == 1
    (outage,) = await _outages(db_session, target)
    assert outage.slack_down_status == "sent"


async def test_canario_caido_no_toca_nada(db_session):
    client = await _client(db_session)
    target = await _target(db_session, client)
    web, slack = Web(), Slack()
    web.canary = _err("timeout")
    web.answers[target.url] = _err("timeout")
    result = await _cycle(db_session, web, slack, T0)
    assert result.canary_failed and result.probed == 0 and target.url not in web.calls
    state = await _state(db_session, target)
    assert state.status == "unknown" and state.last_checked_at is None


async def test_fallos_de_red_correlacionados_no_avanzan_contadores(db_session):
    web, slack = Web(), Slack()
    targets = []
    for _ in range(3):
        targets.append(await _target(db_session, await _client(db_session)))
    healthy = await _target(db_session, await _client(db_session))
    for target in targets:
        web.answers[target.url] = _err("timeout")
    web.answers[healthy.url] = _ok()
    for minute in range(3):
        result = await _cycle(db_session, web, slack, T0 + timedelta(minutes=minute))
        assert result.network_issue
    for target in targets:
        state = await _state(db_session, target)
        assert state.status == "unknown" and state.consecutive_failures == 0
        assert await _outages(db_session, target) == []
    assert (await _state(db_session, healthy)).status == "up"


async def test_solo_clientes_activos_externos_y_urls_activas(db_session):
    web, slack = Web(), Slack()
    internal = await _target(db_session, await _client(db_session, is_internal=True))
    paused = await _target(db_session, await _client(db_session, status=ClientStatus.paused))
    inactive = await _target(db_session, await _client(db_session))
    inactive.is_active = False
    await db_session.flush()
    result = await _cycle(db_session, web, slack, T0)
    assert result.due == 0 and web.calls == []
    for target in (internal, paused, inactive):
        assert (await _state(db_session, target)).last_checked_at is None


async def test_bloqueo_largo_abre_aviso_sin_slack(db_session):
    client = await _client(db_session)
    target = await _target(db_session, client)
    web, slack = Web(), Slack()
    web.answers[target.url] = _ok(403)
    await _cycle(db_session, web, slack, T0)
    assert (await _state(db_session, target)).status == "blocked"
    await _cycle(db_session, web, slack, T0 + timedelta(minutes=61))
    (outage,) = await _outages(db_session, target)
    assert outage.kind == "blocked" and outage.started_at == T0 and outage.slack_down_status == "skipped"
    assert slack.messages == []


# ── Incidencias ──────────────────────────────────────────────────────


async def _user(db, role=UserRole.member, modules=("web",)):
    user = User(email=f"web-{uuid4().hex}@test.local", full_name="Web", hashed_password="x", role=role, is_active=True)
    db.add(user)
    await db.flush()
    db.add_all([UserPermission(user_id=user.id, module=m, can_read=True, can_write=False) for m in modules])
    await db.flush()
    return user


async def _open(db, target, kind="down", started=None):
    outage = WebOutage(target_id=target.id, kind=kind, started_at=started or T0, confirmed_at=T0,
                       cause="http_503" if kind == "down" else "http_403", slack_down_status="skipped")
    db.add(outage)
    await db.flush()
    return outage


async def _incidents(db, user, kind=CLIENT_SITE_DOWN):
    return (await db.execute(select(Notification).where(
        Notification.type == kind, visible_incident_clause(user.id, current_only=True),
    ).execution_options(populate_existing=True))).scalars().all()


async def test_caida_abierta_llega_a_admins_y_responsables_con_lectura_de_web(db_session):
    admin = await _user(db_session, role=UserRole.admin, modules=())
    owner = await _user(db_session)
    owner_without_web = await _user(db_session, modules=("clients",))
    stranger = await _user(db_session)
    client = await _client(db_session, name="Tienda Sol")
    for person in (owner, owner_without_web):
        db_session.add(Project(name="SEO", client_id=client.id, owner_id=person.id, status=ProjectStatus.active))
    await db_session.flush()
    target = await _target(db_session, client)
    outage = await _open(db_session, target)
    now = datetime(2026, 10, 21, 9)  # noqa: DTZ001 - las incidencias guardan UTC naive

    for person in (admin, owner, owner_without_web, stranger):
        await reconcile_recipient(db_session, person.id, now=now)
    (row,) = await _incidents(db_session, admin)
    assert row.incident_severity == "critical" and row.title == "La web no responde: Tienda Sol"
    assert row.dedupe_key == f"client_site_down:client:{client.id}:open"
    assert row.link_url == f"/clients/{client.id}?tab=web"
    assert "no responde desde el 21/10 a las 10:00" in row.message and "error HTTP 503" in row.message
    assert len(await _incidents(db_session, owner)) == 1
    assert await _incidents(db_session, owner_without_web) == []
    assert await _incidents(db_session, stranger) == []

    # Se cierra la caída: la incidencia se resuelve sola.
    outage.ended_at = T0 + timedelta(minutes=5)
    await db_session.flush()
    await reconcile_recipient(db_session, admin.id, now=now)
    row = (await db_session.execute(select(Notification).where(Notification.id == row.id)
                                    .execution_options(populate_existing=True))).scalar_one()
    assert row.incident_state == "resolved" and row.incident_resolution_reason == "condition_cleared"

    # Una caída NUEVA vuelve a avisar aunque la anterior se hubiera descartado.
    row.incident_dismissal_reason = "ya lo sé"
    await db_session.flush()
    await _open(db_session, target, started=T0 + timedelta(hours=1))
    await reconcile_recipient(db_session, admin.id, now=now)
    row = (await db_session.execute(select(Notification).where(Notification.id == row.id)
                                    .execution_options(populate_existing=True))).scalar_one()
    assert row.incident_state == "active"


async def test_bloqueo_es_un_aviso_y_perder_el_permiso_lo_oculta(db_session):
    owner = await _user(db_session)
    client = await _client(db_session)
    db_session.add(Project(name="SEO", client_id=client.id, owner_id=owner.id, status=ProjectStatus.planning))
    await db_session.flush()
    await _open(db_session, await _target(db_session, client), kind="blocked")
    await reconcile_recipient(db_session, owner.id, now=datetime(2026, 10, 21, 9))  # noqa: DTZ001
    (row,) = await _incidents(db_session, owner, CLIENT_SITE_BLOCKED)
    assert row.incident_severity == "warning" and row.title.startswith("No podemos comprobar la web")
    await db_session.execute(UserPermission.__table__.delete().where(UserPermission.user_id == owner.id))
    assert await _incidents(db_session, owner, CLIENT_SITE_BLOCKED) == []


# ── Estado del cliente ───────────────────────────────────────────────


async def test_estado_del_cliente_caida_es_actuar_y_bloqueo_vigilar(db_session):
    down_client = await _client(db_session, name="Caída")
    target = await _target(db_session, down_client)
    state = await _state(db_session, target)
    state.status, state.last_checked_at = "down", T0
    await _open(db_session, target)
    blocked_client = await _client(db_session, name="Bloqueo")
    blocked = await _target(db_session, blocked_client)
    bstate = await _state(db_session, blocked)
    bstate.status, bstate.last_checked_at = "blocked", T0
    await _open(db_session, blocked, kind="blocked")
    fine_client = await _client(db_session, name="Bien")
    fine = await _target(db_session, fine_client)
    fstate = await _state(db_session, fine)
    fstate.status, fstate.last_checked_at = "up", T0
    await db_session.flush()

    viewer = Viewer(is_admin=False, tasks=False, digests=False, timesheet=False, web=True)
    rows = {r["client_id"]: r for r in await portfolio(db_session, [down_client, blocked_client, fine_client], viewer)}
    assert rows[down_client.id]["status"] == "act"
    assert rows[down_client.id]["reasons"] == ["La web no responde desde el 21/10 a las 10:00"]
    assert rows[down_client.id]["uptime"]["alert"] == "down"
    assert rows[blocked_client.id]["status"] == "watch"
    assert rows[blocked_client.id]["reasons"] == ["No podemos comprobar la web (bloqueo)"]
    assert rows[fine_client.id]["status"] == "ok" and rows[fine_client.id]["uptime"]["status"] == "up"

    blind = Viewer(is_admin=False, tasks=False, digests=False, timesheet=False)
    row = (await portfolio(db_session, [down_client], blind))[0]
    assert row["uptime"] is None and row["status"] == "no_data"


# ── Retención ────────────────────────────────────────────────────────


async def test_retencion_borra_sondeos_de_mas_de_30_dias_y_conserva_caidas(db_session, monkeypatch):
    from backend.db import database
    from backend.startup import background_tasks

    target = await _target(db_session, await _client(db_session))
    now = datetime.now(UTC)
    db_session.add_all([
        WebUptimeProbe(target_id=target.id, checked_at=now - timedelta(days=31), outcome="up"),
        WebUptimeProbe(target_id=target.id, checked_at=now - timedelta(days=29), outcome="down"),
    ])
    old = await _open(db_session, target, started=now - timedelta(days=200))
    old.ended_at = now - timedelta(days=199)
    await db_session.flush()
    monkeypatch.setattr(database, "async_session", _Factory(db_session))
    await background_tasks._retention_cleanup_once()
    left = (await db_session.scalars(select(WebUptimeProbe.outcome).where(WebUptimeProbe.target_id == target.id))).all()
    assert left == ["down"]
    assert len(await _outages(db_session, target)) == 1


# ── API y permisos ───────────────────────────────────────────────────


async def test_api_lectura_escritura_y_validacion(db_session, make_member_client, monkeypatch):
    client = await _client(db_session, slack=False)
    reader = await make_member_client([("web", True, False)])
    writer = await make_member_client([("web", True, True)])
    nobody = await make_member_client([("clients", True, True)])
    base = f"/api/clients/{client.id}/web/uptime-targets"

    assert (await nobody.get(base)).status_code == 403
    assert (await nobody.get("/api/web/uptime")).status_code == 403
    assert (await reader.post(base, json={"url": "https://fit.es"})).status_code == 403

    created = await writer.post(base, json={"url": "Fit.es", "label": "Home"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["url"] == "https://fit.es/" and body["status"] == "unknown" and body["uptime_24h"] is None
    assert (await writer.post(base, json={"url": "https://fit.es/"})).status_code == 409
    for bad in ("http://10.0.0.1/", "https://fit.es:8080/", "http://db.railway.internal/", "http://169.254.169.254/"):
        assert (await writer.post(base, json={"url": bad})).status_code == 422, bad

    listed = (await reader.get(base)).json()
    assert listed["monitored"] is True and [t["url"] for t in listed["targets"]] == ["https://fit.es/"]
    overview = (await reader.get("/api/web/uptime")).json()
    assert any(row["client_id"] == client.id and len(row["targets"]) == 1 for row in overview["clients"])

    target_id = body["id"]
    paused = await writer.patch(f"{base}/{target_id}", json={"is_active": False})
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    assert (await reader.patch(f"{base}/{target_id}", json={"label": "x"})).status_code == 403
    history = await reader.get(f"/api/web/uptime-targets/{target_id}/history?days=30")
    assert history.status_code == 200 and history.json()["days"] == []

    async def fake_probe(url, **kwargs):
        assert url == "https://fit.es/" and kwargs["retry"] is False
        return uptime.Probe("up", None, 200, 95)

    from backend.api.routes import web_uptime as routes
    monkeypatch.setattr(routes, "probe", fake_probe)
    assert (await reader.post(f"/api/web/uptime-targets/{target_id}/probe")).status_code == 403
    probed = await writer.post(f"/api/web/uptime-targets/{target_id}/probe")
    assert probed.status_code == 200 and probed.json()["outcome"] == "up"
    # Probar ahora no cambia el estado ni deja sondeo.
    assert (await _state(db_session, (await db_session.get(WebUptimeTarget, target_id)))).last_checked_at is None

    assert (await writer.delete(f"{base}/{target_id}")).status_code == 204
    assert (await reader.get(base)).json()["targets"] == []
    for c in (reader, writer, nobody):
        await c.aclose()


async def test_slack_solo_admin_y_el_webhook_nunca_vuelve(db_session, admin_client, make_member_client, monkeypatch):
    client = await _client(db_session, slack=False)
    writer = await make_member_client([("web", True, True), ("clients", True, True)])
    url = f"/api/clients/{client.id}/web/settings/slack"
    assert (await writer.get(url)).status_code == 403
    assert (await writer.put(url, json={"webhook_url": HOOK})).status_code == 403
    await writer.aclose()

    empty = (await admin_client.get(url)).json()
    assert empty["configured"] is False and empty["active"] is False
    assert (await admin_client.put(url, json={"enabled": True})).status_code == 422
    assert (await admin_client.put(url, json={"webhook_url": "https://evil.com/x"})).status_code == 422

    saved = await admin_client.put(url, json={"webhook_url": HOOK, "channel_hint": "fit-avisos", "enabled": True,
                                              "user_agent": "Mozilla/5.0 Agency"})
    assert saved.status_code == 200 and saved.headers["cache-control"] == "no-store"
    assert HOOK not in saved.text and "hooks.slack.com" not in saved.text
    data = saved.json()
    assert data["configured"] and data["active"] and data["channel_hint"] == "#fit-avisos"
    row = (await db_session.execute(select(ClientWebSettings).where(ClientWebSettings.client_id == client.id)
                                    .execution_options(populate_existing=True))).scalar_one()
    assert row.slack_webhook_url.startswith("v1:") and decrypt_vault_secret(row.slack_webhook_url) == HOOK
    assert row.user_agent == "Mozilla/5.0 Agency"
    assert "hooks.slack.com" not in (await admin_client.get(url)).text

    # Cambiar sólo el canal conserva el webhook.
    again = (await admin_client.put(url, json={"channel_hint": "#otro", "enabled": True})).json()
    assert again["configured"] and again["channel_hint"] == "#otro"

    from backend.api.routes import web_uptime as routes

    async def revoked(webhook, name):
        assert webhook == HOOK
        return DeliveryResult(ok=False, status=404, revoked=True, error="El webhook ya no existe en Slack.")

    monkeypatch.setattr(routes.slack_service, "send_test_message", revoked)
    tested = await admin_client.post(f"{url}/test")
    assert tested.status_code == 200 and tested.json()["revoked"] is True
    after = (await admin_client.get(url)).json()
    assert after["active"] is False and after["revoked_at"] is not None

    removed = (await admin_client.delete(url)).json()
    assert removed["configured"] is False and removed["enabled"] is False
    assert (await admin_client.post(f"{url}/test")).status_code == 422


# ── Alta inicial ─────────────────────────────────────────────────────


async def test_seed_crea_la_home_de_clientes_activos_externos_sin_urls(db_session):
    from backend.scripts.seed_uptime_targets import build_plan

    fresh = await _client(db_session, slack=False)
    fresh.website = "Fit.es"
    internal = await _client(db_session, slack=False, is_internal=True)
    covered = await _client(db_session, slack=False)
    await _target(db_session, covered)
    weird = await _client(db_session, slack=False)
    weird.website = "http://intranet:8080"
    await db_session.flush()
    plan, skipped = await build_plan(db_session)
    planned = {client_id: url for client_id, _name, url in plan}
    assert planned.get(fresh.id) == "https://fit.es/"
    assert internal.id not in planned and covered.id not in planned
    assert weird.id in {client_id for client_id, _n, _r in skipped}
