"""Vigilancia de cambios contra Postgres real, sin red (fetch y Slack de mentira).

Portado de Vigil: test_sweep_e2e.py (ciclo de cuatro noches, críticos, Slack),
test_barrido_manual.py (varias comprobaciones al día, una programada, progreso,
recogida de huérfanos), test_html_diff.py (endpoint) y test_lista_cambios.py
(contadores que ignoran el filtro, marcar todo). Además: el job (manual primero,
un cliente programado por ciclo, calendario), el trabajo de CPU en un hilo, la
incidencia ``client_web_critical_change``, el estado del cliente, la retención,
los permisos del API y que nada de esto entra en el Deshacer.
"""
from __future__ import annotations

import asyncio
import gzip
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from backend.config import settings
from backend.core.security import encrypt_vault_secret
from backend.db.models import (
    ChangeLog, Client, ClientStatus, ClientWebSettings, Notification, Project, ProjectStatus, User, UserPermission,
    UserRole, WebChange, WebChangeItem, WebRunError, WebSnapshot, WebSweepRun, WebUptimeState,
    WebUptimeTarget, WebWatch, WebWatchState,
)
from backend.services.client_status import Viewer, portfolio
from backend.services.incident_web_conditions import CLIENT_WEB_CRITICAL_CHANGE
from backend.services.incidents import reconcile_recipient, visible_incident_clause
from backend.services.web import sweep
from backend.services.web.changes_views import client_blocks as change_blocks
from backend.services.web.safe_http import FetchResult
from backend.services.web.slack import DeliveryResult

pytestmark = pytest.mark.integration

HOOK = "https://hooks.slack.com/services/T0/B0/xxxx"
URL = "https://fitgeneration.es/master-nutricion"


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


PAGINA = """<html lang="es"><head>
  <title>{title}</title>
  <meta name="description" content="Fórmate con los mejores.">
  <link rel="canonical" href="{canonical}">
  {robots}
  <script type="application/ld+json">{{"@type":"Course","name":"Máster"}}</script>
</head><body><main>
  <h1>{h1}</h1>
  <h2>Temario</h2>
  <p>{cuerpo}</p>
  <!-- comentario que no cuenta -->
  <a href="/contacto">Contacto</a>
</main></body></html>"""


def pagina(*, title="Máster en Nutrición | Fit Generation", h1="Máster en Nutrición", canonical=URL,
           robots='<meta name="robots" content="index, follow">',
           cuerpo="El temario cubre anatomía y fisiología aplicadas al deporte."):
    return PAGINA.format(title=title, h1=h1, canonical=canonical, robots=robots, cuerpo=cuerpo)


def _resp(html: str, status: int = 200, headers: dict | None = None) -> FetchResult:
    return FetchResult(status_code=status, elapsed_ms=50, final_url="", headers=headers or {},
                       body=html.encode())


class Web:
    """Internet de mentira: lo que responde cada URL (o todas) en este momento."""

    def __init__(self, html: str | None = None):
        self.default = _resp(html) if html is not None else None
        self.answers: dict[str, FetchResult] = {}
        self.calls: list[str] = []

    def serve(self, html: str, status: int = 200, headers: dict | None = None, url: str | None = None):
        result = _resp(html, status, headers)
        if url is None:
            self.default = result
        else:
            self.answers[url] = result

    async def fetch(self, url, **_kw):
        self.calls.append(url)
        result = self.answers.get(url, self.default)
        # El fetch real devuelve la URL final tras las redirecciones.
        return FetchResult(result.status_code, result.elapsed_ms, url, result.redirects, result.headers,
                           result.body, result.error)


class Slack:
    def __init__(self):
        self.messages: list[dict] = []
        self.reply = DeliveryResult(ok=True, status=200)

    async def post(self, webhook, text, blocks=None):
        self.messages.append({"webhook": webhook, "text": text, "blocks": blocks})
        return self.reply

    @property
    def n(self) -> int:
        return len(self.messages)

    def last(self) -> str:
        return str(self.messages[-1])


async def _no_sleep(_seconds):
    return None


async def _client(db, *, name=None, slack=True, changes=True, **fields) -> Client:
    """Cliente con la vigilancia de cambios encendida (salvo ``changes=False``)."""
    client = Client(name=name or f"Cliente {uuid4().hex[:6]}", website="https://ejemplo.com", **fields)
    db.add(client)
    await db.flush()
    if slack or changes:
        db.add(ClientWebSettings(client_id=client.id, changes_enabled=changes,
                                 slack_webhook_url=encrypt_vault_secret(HOOK) if slack else None,
                                 slack_enabled=slack))
    await db.commit()
    return client


async def _watch(db, client, url=URL, **flags) -> WebWatch:
    watch = WebWatch(client_id=client.id, url=url, label="Máster Nutrición", **flags)
    db.add(watch)
    await db.commit()
    return watch


async def _sweep(db, client, web, slack=None, *, trigger="manual", **kw) -> dict:
    slack = slack or Slack()
    return await sweep.sweep_client(_Factory(db), client.id, trigger=trigger, fetcher=web.fetch, post=slack.post,
                                    sleep=_no_sleep, **kw)


async def _rows(db, model, *where):
    return (await db.scalars(select(model).where(*where).execution_options(populate_existing=True))).all()


async def _state(db, watch) -> WebWatchState:
    return (await _rows(db, WebWatchState, WebWatchState.watch_id == watch.id))[0]


async def _settings(db, client) -> ClientWebSettings:
    return (await _rows(db, ClientWebSettings, ClientWebSettings.client_id == client.id))[0]


# ── El ciclo completo (de Vigil: test_sweep_e2e.py) ──────────────────


async def test_ciclo_completo_de_cuatro_noches(db_session):
    client = await _client(db_session, name="Fit Generation")
    watch = await _watch(db_session, client)
    web, slack = Web(pagina()), Slack()

    # 1ª: primera captura, ningún aviso.
    r1 = await _sweep(db_session, client, web, slack, trigger="scheduler")
    assert r1["changes"] == 0 and r1["notify"] == "skipped_no_changes" and slack.n == 0
    state = await _state(db_session, watch)
    assert state.hash_seo and state.seo_json["title"] == "Máster en Nutrición | Fit Generation"
    assert state.checking_since is None and state.last_snapshot_id is not None
    assert len(await _rows(db_session, WebSnapshot, WebSnapshot.watch_id == watch.id)) == 1

    # 2ª: nada cambia → NADA a Slack y ninguna captura nueva idéntica.
    r2 = await _sweep(db_session, client, web, slack)
    assert r2["changes"] == 0 and r2["notify"] == "skipped_no_changes" and slack.n == 0
    assert len(await _rows(db_session, WebSnapshot, WebSnapshot.watch_id == watch.id)) == 1

    # 3ª: cambia el title → aviso con el antes y el después, enlazado a The Agency.
    web.serve(pagina(title="Curso de Nutrición | Fit Generation"))
    r3 = await _sweep(db_session, client, web, slack, trigger="api")
    assert r3["changes"] == 1 and r3["notify"] == "sent" and slack.n == 1
    texto = slack.last()
    assert slack.messages[0]["webhook"] == HOOK
    assert "title cambiado" in texto and "Máster en Nutrición | Fit Generation" in texto
    assert "Curso de Nutrición | Fit Generation" in texto and "/master-nutricion" in texto
    (change,) = await _rows(db_session, WebChange, WebChange.watch_id == watch.id)
    assert change.max_severity == "warning" and f"/web/cambios/{change.id}" in texto
    assert [i.rule_code for i in await _rows(db_session, WebChangeItem, WebChangeItem.change_id == change.id)] == [
        "TITLE_CHANGED"]
    assert len(await _rows(db_session, WebSnapshot, WebSnapshot.watch_id == watch.id)) == 2
    run = (await _rows(db_session, WebSweepRun, WebSweepRun.id == change.run_id))[0]
    assert run.status == "done" and run.changes_found == 1 and run.notify_status == "sent" and run.notified_at

    # 4ª: noindex → crítico.
    web.serve(pagina(title="Curso de Nutrición | Fit Generation",
                     robots='<meta name="robots" content="noindex, follow">'))
    await _sweep(db_session, client, web, slack)
    assert "Críticos" in slack.last() and "noindex añadido" in slack.last()
    latest = (await db_session.scalars(select(WebChange).where(WebChange.watch_id == watch.id)
                                       .order_by(WebChange.detected_at.desc()).limit(1))).one()
    assert latest.max_severity == "critical" and latest.prev_snapshot_id == change.snapshot_id


async def test_pagina_caida_no_arrastra_falsos_cambios_seo(db_session):
    client = await _client(db_session)
    watch = await _watch(db_session, client)
    web = Web(pagina())
    await _sweep(db_session, client, web)
    web.serve("<html><head><title>404</title></head><body></body></html>", status=404)
    await _sweep(db_session, client, web)
    (change,) = await _rows(db_session, WebChange, WebChange.watch_id == watch.id)
    items = await _rows(db_session, WebChangeItem, WebChangeItem.change_id == change.id)
    assert [i.rule_code for i in items] == ["STATUS_ERROR"] and change.max_severity == "critical"


async def test_url_silenciada_no_entra_en_el_digest_pero_el_cambio_se_guarda(db_session):
    client = await _client(db_session)
    watch = await _watch(db_session, client)
    web, slack = Web(pagina()), Slack()
    await _sweep(db_session, client, web, slack)
    watch.muted = True
    await db_session.commit()
    web.serve(pagina(title="Otro título"))
    r = await _sweep(db_session, client, web, slack)
    assert r["notify"] == "skipped_no_changes" and slack.n == 0
    assert len(await _rows(db_session, WebChange, WebChange.watch_id == watch.id)) == 1


async def test_un_fallo_de_slack_no_invalida_el_barrido(db_session):
    client = await _client(db_session)
    watch = await _watch(db_session, client)
    web, slack = Web(pagina()), Slack()
    await _sweep(db_session, client, web, slack)
    slack.reply = DeliveryResult(ok=False, status=500, error="Slack caído")
    web.serve(pagina(title="Nuevo"))
    r = await _sweep(db_session, client, web, slack)
    assert r["notify"] == "failed"
    assert len(await _rows(db_session, WebChange, WebChange.watch_id == watch.id)) == 1
    run = (await _rows(db_session, WebSweepRun, WebSweepRun.id == r["run_id"]))[0]
    assert run.notify_error == "Slack caído" and run.status == "done"


async def test_webhook_revocado_se_distingue_y_se_apaga(db_session):
    """Volver a pegar el mismo webhook no arregla un 404 de Slack: hay que generar
    otro. El webhook se conserva; el aviso se apaga y queda la fecha."""
    client = await _client(db_session)
    await _watch(db_session, client)
    web, slack = Web(pagina()), Slack()
    await _sweep(db_session, client, web, slack)
    slack.reply = DeliveryResult(ok=False, status=404, revoked=True, error="El webhook ya no existe en Slack.")
    web.serve(pagina(title="Otro"))
    assert (await _sweep(db_session, client, web, slack))["notify"] == "revoked"
    row = await _settings(db_session, client)
    assert row.slack_enabled is False and row.slack_revoked_at is not None and row.slack_webhook_url
    # El siguiente barrido ya no lo intenta y lo dice igual.
    web.serve(pagina(title="Otro más"))
    sent = slack.n
    assert (await _sweep(db_session, client, web, slack))["notify"] == "revoked" and slack.n == sent


async def test_comprobar_una_url_no_avisa_y_sin_slack_se_dice_disabled(db_session):
    client = await _client(db_session)
    watch = await _watch(db_session, client)
    web, slack = Web(pagina()), Slack()
    r = await _sweep(db_session, client, web, slack, watch_ids=[watch.id], notify=False)
    assert r["notify"] == "no_procede" and slack.n == 0
    quiet = await _client(db_session, slack=False)
    await _watch(db_session, quiet)
    assert (await _sweep(db_session, quiet, web, slack, trigger="scheduler"))["notify"] == "disabled"


async def test_barrido_completo_manda_resumen_aunque_no_haya_cambios(db_session):
    client = await _client(db_session, name="Fit Generation")
    for i in range(3):
        await _watch(db_session, client, url=f"https://x.com/p{i}")
    web, slack = Web(pagina()), Slack()
    r = await _sweep(db_session, client, web, slack, completo=True)
    assert slack.n == 1 and "ninguna con cambios" in slack.messages[0]["text"] and r["notify"] == "summary_sent"
    # Se puede apagar por cliente.
    row = await _settings(db_session, client)
    row.sweep_summary_to_slack = False
    await db_session.commit()
    await _sweep(db_session, client, web, slack, completo=True)
    assert slack.n == 1


async def test_digest_min_severity_filtra_lo_que_va_a_slack(db_session):
    client = await _client(db_session)
    await _watch(db_session, client)
    row = await _settings(db_session, client)
    row.digest_min_severity = "critical"
    await db_session.commit()
    web, slack = Web(pagina()), Slack()
    await _sweep(db_session, client, web, slack)
    web.serve(pagina(title="Otro"))  # aviso, no crítico
    assert (await _sweep(db_session, client, web, slack))["notify"] == "skipped_no_changes" and slack.n == 0
    web.serve(pagina(title="Otro", robots='<meta name="robots" content="noindex">'))
    assert (await _sweep(db_session, client, web, slack))["notify"] == "sent" and "noindex añadido" in slack.last()


async def test_error_de_red_se_registra_y_no_pisa_el_estado(db_session):
    client = await _client(db_session)
    watch = await _watch(db_session, client)
    web, slack = Web(pagina()), Slack()
    await _sweep(db_session, client, web, slack)
    before = (await _state(db_session, watch)).hash_seo
    web.default = FetchResult(None, 20000, URL, error="timeout")
    r = await _sweep(db_session, client, web, slack)
    assert r["errors"] == 1 and slack.n == 0
    (error,) = await _rows(db_session, WebRunError, WebRunError.watch_id == watch.id)
    assert error.kind == "timeout" and error.message == "no responde a tiempo"
    state = await _state(db_session, watch)
    assert state.consecutive_errors == 1 and state.hash_seo == before and state.last_error == "no responde a tiempo"
    run = (await _rows(db_session, WebSweepRun, WebSweepRun.id == r["run_id"]))[0]
    assert run.status == "partial" and run.watches_error == 1


async def test_el_programado_es_uno_al_dia_y_lo_manual_se_repite(db_session):
    """Lección 0bis de Vigil: la 2ª comprobación manual del día se abortaba en
    silencio. Sólo el PROGRAMADO es único por cliente y día."""
    client = await _client(db_session)
    watches = [await _watch(db_session, client, url=f"https://x.com/p{i}") for i in range(3)]
    web = Web(pagina())
    for i, watch in enumerate(watches, start=1):
        r = await _sweep(db_session, client, web, watch_ids=[watch.id], notify=False)
        assert r.get("skipped") is None and r["watches"] == 1, f"la comprobación nº {i} se bloqueó"
    client_id = client.id  # el rollback del duplicado expira los objetos de la sesión compartida
    first = await _sweep(db_session, client, web, trigger="scheduler")
    second = await _sweep(db_session, client, web, trigger="scheduler")
    assert first.get("skipped") is None and second == {"client_id": client_id, "skipped": "ya_ejecutado_hoy"}
    runs = await _rows(db_session, WebSweepRun, WebSweepRun.client_id == client_id)
    assert sorted(r.trigger for r in runs) == ["manual", "manual", "manual", "scheduler"]
    assert all(r.run_date == sweep.local_date(datetime.now(UTC)) for r in runs)


# ── Poda y sección (lecciones 0quater y 0quinquies de Vigil) ─────────


CAFYD = """<html lang="es"><head><title>CAFYD Online | Fit Generation</title>
  <link rel="canonical" href="{url}"></head><body>
  <nav><a href="/menu">Menú</a></nav>
  <main><h1>CAFYD Online</h1>
  <section class="claustro">
    <div class="swiper-wrapper" aria-live="polite"><div class="fg-flipcard__inner" aria-live="polite">
      <h3>Eneko Baz</h3><p>Doctor en Ciencias del Deporte y preparador de culturismo{punto}</p>
    </div></div>
  </section>
  <section class="temario"><p>Fisiología, biomecánica y nutrición aplicadas.</p></section>
</main></body></html>"""


def _cafyd(punto: str = "") -> str:
    return CAFYD.format(url=URL, punto=punto)


async def test_un_punto_en_una_card_de_profesor_se_detecta_con_los_defaults(db_session):
    client = await _client(db_session)
    await _watch(db_session, client)
    web = Web(_cafyd())
    await _sweep(db_session, client, web)
    web.serve(_cafyd("."))
    assert (await _sweep(db_session, client, web))["changes"] == 1


async def test_acotar_la_seccion_y_que_desaparezca_se_denuncia(db_session):
    client = await _client(db_session)
    watch = await _watch(db_session, client, content_selector=".claustro")
    web = Web(_cafyd())
    await _sweep(db_session, client, web)
    web.serve(_cafyd().replace("Fisiología, biomecánica", "Otro temario distinto"))
    assert (await _sweep(db_session, client, web))["changes"] == 0
    web.serve(_cafyd().replace("Eneko Baz", "Eneko Baztarrika"))
    assert (await _sweep(db_session, client, web))["changes"] == 1
    web.serve(_cafyd().replace('class="claustro"', 'class="profesorado"'))
    await _sweep(db_session, client, web)
    assert (await _state(db_session, watch)).scope_missed is True


async def test_la_poda_por_defecto_del_cliente_y_su_override(db_session):
    """NULL = defaults del código (``nav`` fuera); una lista guardada manda."""
    client = await _client(db_session)
    watch = await _watch(db_session, client, watch_links=True)
    web = Web(_cafyd())
    await _sweep(db_session, client, web)
    assert "https://fitgeneration.es/menu" not in (await _state(db_session, watch)).links_json["internal"]
    row = await _settings(db_session, client)
    row.default_ignore_selectors = []
    await db_session.commit()
    await _sweep(db_session, client, web)
    assert "https://fitgeneration.es/menu" in (await _state(db_session, watch)).links_json["internal"]


# ── Circuit breaker cruzado con el monitor de caídas ─────────────────


async def test_un_waf_que_bloquea_todo_no_genera_avisos_y_se_cruza_con_el_monitor(db_session):
    client = await _client(db_session)
    watches = [await _watch(db_session, client, url=f"https://www.fit.es/p{i}") for i in range(4)]
    web, slack = Web(pagina()), Slack()
    await _sweep(db_session, client, web, slack)
    web.serve("<html>Forbidden</html>", status=403)
    r = await _sweep(db_session, client, web, slack, completo=True)
    assert r["changes"] == 0 and r["errors"] == 4 and r["hosts_cut"] == ["www.fit.es"]
    (cut,) = await _rows(db_session, WebRunError, WebRunError.run_id == r["run_id"])
    assert cut.kind == "host_circuit_open" and "Probable bloqueo" in cut.message
    assert "Probable bloqueo" in slack.last()
    # Su estado no se toca: mañana se compara contra la última captura buena.
    for w in watches:
        assert (await _state(db_session, w)).consecutive_errors == 0

    # Si el monitor de disponibilidad dice que esa web está caída, se dice eso.
    target = WebUptimeTarget(client_id=client.id, url="https://fit.es/")
    db_session.add(target)
    await db_session.flush()
    db_session.add(WebUptimeState(target_id=target.id, status="down"))
    await db_session.commit()
    web.default = FetchResult(None, 20000, "", error="connect")
    r = await _sweep(db_session, client, web, slack, completo=True)
    (cut,) = await _rows(db_session, WebRunError, WebRunError.run_id == r["run_id"],
                         WebRunError.kind == "host_circuit_open")
    assert "caída según el monitor de disponibilidad" in cut.message


# ── HTML guardado y su diff (de Vigil: test_html_diff.py) ────────────


def _cards(n: int, etiqueta: str = "Profesor") -> str:
    cards = "".join(f"<div class='card'><span>{etiqueta} {i}</span></div>" for i in range(n))
    return f"""<html lang="es"><head><title>Máster</title></head><body><main>
      <h1>Máster</h1><!-- nada --> <div class="fg-cards">{cards}</div></main></body></html>"""


async def test_html_diff_ensena_antes_y_despues_y_si_no_puede_dice_por_que(db_session, make_member_client):
    client = await _client(db_session)
    watch = await _watch(db_session, client, watch_seo=False, watch_content=False, watch_html=True)
    web = Web(_cards(3))
    await _sweep(db_session, client, web)
    snap = (await _rows(db_session, WebSnapshot, WebSnapshot.watch_id == watch.id))[0]
    stored = gzip.decompress(snap.html_gz).decode()
    # Se guarda el HTML NORMALIZADO que mira el detector, no el crudo.
    assert "<!--" not in stored and "> <" not in stored
    web.serve(_cards(3, "Docente"))
    assert (await _sweep(db_session, client, web))["changes"] == 1
    (change,) = await _rows(db_session, WebChange, WebChange.watch_id == watch.id)
    (item,) = await _rows(db_session, WebChangeItem, WebChangeItem.change_id == change.id)
    assert item.rule_code == "HTML_CHANGED" and item.detail["added"] > 0

    reader = await make_member_client([("web", True, False)])
    nobody = await make_member_client([("clients", True, True)])
    body = (await reader.get(f"/api/web/changes/{change.id}/html-diff")).json()
    assert body["available"] is True
    texto = " ".join(line["s"] for hunk in body["hunks"] for line in hunk["lines"])
    assert "Profesor 0" in texto and "Docente 0" in texto
    denied = await nobody.get(f"/api/web/changes/{change.id}/html-diff")
    assert denied.status_code == 403 and "fg-cards" not in denied.text

    # Sin captura anterior (p. ej. tras importar de Vigil): se explica, no se calla.
    await db_session.execute(update(WebWatchState).where(WebWatchState.watch_id == watch.id)
                             .values(last_snapshot_id=None))
    await db_session.commit()
    web.serve(_cards(4))
    await _sweep(db_session, client, web)
    latest = (await db_session.scalars(select(WebChange).where(WebChange.watch_id == watch.id)
                                       .order_by(WebChange.detected_at.desc()).limit(1))).one()
    assert (await reader.get(f"/api/web/changes/{latest.id}/html-diff")).json() == {
        "available": False, "reason": "sin_anterior"}
    await db_session.execute(update(WebSnapshot).where(WebSnapshot.id == latest.snapshot_id).values(html_gz=None))
    await db_session.commit()
    assert (await reader.get(f"/api/web/changes/{latest.id}/html-diff")).json()["reason"] == "sin_actual"
    diff = (await reader.get(f"/api/web/changes/{change.id}/diff")).json()
    assert set(diff) == {"before", "after"}
    for c in (reader, nobody):
        await c.aclose()


# ── Lista de cambios (de Vigil: test_lista_cambios.py) ───────────────


async def _change(db, client, watch, severity, *, detected=None) -> WebChange:
    change = WebChange(client_id=client.id, watch_id=watch.id, max_severity=severity,
                       detected_at=detected or datetime.now(UTC))
    db.add(change)
    await db.flush()
    db.add(WebChangeItem(change_id=change.id, client_id=client.id, kind="seo", field="title", severity=severity,
                         rule_code="TITLE_CHANGED", before_val="a", after_val="b"))
    await db.commit()
    return change


async def test_los_contadores_ignoran_el_filtro_y_la_lista_recortada_lo_dice(db_session, make_member_client):
    client = await _client(db_session)
    other = await _client(db_session)
    watch = await _watch(db_session, client)
    other_watch = await _watch(db_session, other)
    for severity in ("critical", "warning", "info", "info"):
        await _change(db_session, client, watch, severity)
    await _change(db_session, other, other_watch, "critical")
    reader = await make_member_client([("web", True, False)])
    writer = await make_member_client([("web", True, True)])
    base = f"/api/web/changes?client_id={client.id}"

    todos = (await reader.get(base)).json()
    assert todos["counts"] == {"critical": 1, "warning": 1, "info": 2, "all": 4} and len(todos["changes"]) == 4
    assert todos["changes"][0]["items"][0]["rule_label"] == "title cambiado"
    filtrado = (await reader.get(f"{base}&severity=critical")).json()
    assert len(filtrado["changes"]) == 1 and filtrado["counts"] == todos["counts"]
    # Global: todos los clientes, con el nombre del cliente en cada fila.
    global_list = (await reader.get("/api/web/changes?severity=critical")).json()
    assert {c["client_id"] for c in global_list["changes"]} >= {client.id, other.id}
    assert all(c["client_name"] for c in global_list["changes"])

    recortada = (await reader.get(f"{base}&limit=2")).json()
    assert len(recortada["changes"]) == 2 and recortada["total"] == 4 and recortada["truncated"] is True

    # Revisar: escritura. Lo leído no puede marcar. (El más antiguo: el crítico.)
    target = todos["changes"][-1]["id"]
    assert todos["changes"][-1]["max_severity"] == "critical"
    assert (await reader.post(f"/api/web/changes/{target}/ack", json={})).status_code == 403
    acked = await writer.post(f"/api/web/changes/{target}/ack", json={"note": "visto con el cliente"})
    assert acked.status_code == 200 and acked.json()["acknowledged_by_label"] and acked.json()["note"]
    pend = (await reader.get(f"{base}&acknowledged=false")).json()
    assert len(pend["changes"]) == 3 and pend["counts"]["all"] == 4 and pend["counts_pending"]["all"] == 3
    assert pend["total"] == 3 and pend["truncated"] is False

    # ack-all respeta el filtro y no reescribe lo ya revisado.
    first_ack = (await _rows(db_session, WebChange, WebChange.id == target))[0].acknowledged_at
    done = (await writer.post("/api/web/changes/ack-all", json={"client_id": client.id, "severity": "info"})).json()
    assert done["acknowledged"] == 2
    assert (await _rows(db_session, WebChange, WebChange.id == target))[0].acknowledged_at == first_ack
    assert (await writer.post("/api/web/changes/ack-all", json={"client_id": client.id, "severity": "urgente"})
            ).status_code == 422
    assert (await writer.post("/api/web/changes/ack-all", json={"client_id": client.id})).json()["acknowledged"] == 1
    assert (await writer.post("/api/web/changes/ack-all", json={"client_id": client.id})).json()["acknowledged"] == 0
    # El otro cliente sigue pendiente.
    assert (await _rows(db_session, WebChange, WebChange.client_id == other.id))[0].acknowledged_at is None
    for c in (reader, writer):
        await c.aclose()


# ── El job: lo manual primero, un programado por ciclo, calendario ───


async def test_run_cycle_hace_lo_pedido_a_mano_y_luego_un_cliente_programado(db_session, make_member_client,
                                                                              monkeypatch):
    monkeypatch.setattr(settings, "WEB_SWEEP_LOCAL_TIME", "06:30")
    a = await _client(db_session, name="A")
    b = await _client(db_session, name="B")
    paused = await _client(db_session, name="Pausado", status=ClientStatus.paused)
    wa = [await _watch(db_session, a, url=f"https://a.com/p{i}") for i in range(2)]
    await _watch(db_session, b, url="https://b.com/")
    await _watch(db_session, paused, url="https://p.com/")
    writer = await make_member_client([("web", True, True)])
    accepted = await writer.post(f"/api/web/watches/{wa[0].id}/check")
    assert accepted.status_code == 202 and accepted.json()["enabled"] is False
    assert (await writer.post(f"/api/clients/{paused.id}/web/watches/check-all")).status_code == 409
    progress = (await writer.get(f"/api/clients/{a.id}/web/watches/progress")).json()
    assert progress["queued"] == [str(wa[0].id)] and progress["is_running"] is False

    web, slack = Web(pagina()), Slack()
    factory = _Factory(db_session)
    # 05:00 en Madrid: sólo lo pedido a mano (una URL suelta: sin Slack).
    early = datetime(2026, 10, 21, 3, 0, tzinfo=UTC)
    result = await sweep.run_cycle(factory, now=early, fetcher=web.fetch, post=slack.post, sleep=_no_sleep)
    assert [m["watches"] for m in result.manual] == [1] and result.scheduled is None and slack.n == 0
    assert (await _rows(db_session, WebWatch, WebWatch.id == wa[0].id))[0].check_requested_at is None

    # "Comprobar todas" = todas sus URLs: resumen a su Slack.
    assert (await writer.post(f"/api/clients/{a.id}/web/watches/check-all")).status_code == 202
    result = await sweep.run_cycle(factory, now=early, fetcher=web.fetch, post=slack.post, sleep=_no_sleep)
    assert result.manual[0]["watches"] == 2 and slack.n == 1 and "barrido manual" in slack.messages[0]["text"]

    # 07:00 en Madrid (miércoles): un cliente programado por ciclo, nunca el pausado.
    later = datetime(2026, 10, 21, 5, 0, tzinfo=UTC)
    cycles = [await sweep.run_cycle(factory, now=later, fetcher=web.fetch, post=slack.post, sleep=_no_sleep)
              for _ in range(3)]
    assert [c.scheduled and c.scheduled["client_id"] for c in cycles] == [a.id, b.id, None]
    runs = await _rows(db_session, WebSweepRun, WebSweepRun.trigger == "scheduler",
                       WebSweepRun.client_id.in_([a.id, b.id, paused.id]))
    assert sorted(r.client_id for r in runs) == sorted([a.id, b.id])
    assert all(r.run_date == date(2026, 10, 21) for r in runs)
    await writer.aclose()


async def test_el_calendario_salta_el_fin_de_semana_y_los_festivos(db_session):
    client = await _client(db_session)
    await _watch(db_session, client)
    web = Web(pagina())
    saturday = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)
    result = await sweep.run_cycle(_Factory(db_session), now=saturday, fetcher=web.fetch, sleep=_no_sleep)
    assert (client.id, "hoy es sábado y no está en los días configurados") in result.calendar_skipped
    row = await _settings(db_session, client)
    row.sweep_weekdays, row.sweep_skip_dates = [6], ["2026-10-31"]
    await db_session.commit()
    result = await sweep.run_cycle(_Factory(db_session), now=saturday, fetcher=web.fetch, sleep=_no_sleep)
    assert result.scheduled and result.scheduled["client_id"] == client.id
    holiday = datetime(2026, 10, 31, 8, 0, tzinfo=UTC)
    result = await sweep.run_cycle(_Factory(db_session), now=holiday, fetcher=web.fetch, sleep=_no_sleep)
    assert (client.id, "es un día marcado como festivo") in result.calendar_skipped


async def test_al_empezar_el_ciclo_se_recoge_lo_que_quedo_en_curso(db_session):
    """Lección 0ter de Vigil: un deploy a mitad de barrido dejaba la interfaz girando."""
    client = await _client(db_session)
    watch = await _watch(db_session, client)
    now = datetime.now(UTC)
    db_session.add(WebWatchState(watch_id=watch.id, client_id=client.id, checking_since=now))
    db_session.add(WebSweepRun(client_id=client.id, run_date=now.date(), trigger="manual", status="running",
                               started_at=now))
    await db_session.commit()
    result = await sweep.run_cycle(_Factory(db_session), now=datetime(2026, 10, 21, 3, tzinfo=UTC),
                                   fetcher=Web(pagina()).fetch, sleep=_no_sleep)
    assert result.reaped_runs >= 1 and result.reaped_marks >= 1
    assert (await _state(db_session, watch)).checking_since is None
    assert not await _rows(db_session, WebSweepRun, WebSweepRun.client_id == client.id,
                           WebSweepRun.status == "running")


async def test_el_trabajo_de_cpu_va_en_un_hilo(db_session, monkeypatch):
    """lxml, hashes y difflib fuera del bucle de eventos: este proceso es también la API."""
    client = await _client(db_session)
    await _watch(db_session, client)
    offloaded: list[str] = []
    real = asyncio.to_thread

    async def spy(func, /, *args, **kwargs):
        offloaded.append(getattr(func, "__name__", repr(func)))
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(sweep.asyncio, "to_thread", spy)
    web = Web(pagina())
    await _sweep(db_session, client, web)
    web.serve(pagina(cuerpo="Otro texto completamente distinto del de antes, reescrito entero."))
    assert (await _sweep(db_session, client, web))["changes"] == 1
    assert offloaded.count("extract") == 2 and offloaded.count("compare") == 2


# ── Incidencia ───────────────────────────────────────────────────────


async def _user(db, role=UserRole.member, modules=("web",)) -> User:
    user = User(email=f"web-{uuid4().hex}@test.local", full_name="Web", hashed_password="x", role=role,
                is_active=True)
    db.add(user)
    await db.flush()
    db.add_all([UserPermission(user_id=user.id, module=m, can_read=True, can_write=False) for m in modules])
    await db.commit()
    return user


async def _incidents(db, user):
    return (await db.execute(select(Notification).where(
        Notification.type == CLIENT_WEB_CRITICAL_CHANGE, visible_incident_clause(user.id, current_only=True),
    ).execution_options(populate_existing=True))).scalars().all()


async def test_cambio_critico_sin_revisar_abre_incidencia_y_revisarlo_la_resuelve(db_session, make_member_client):
    admin = await _user(db_session, role=UserRole.admin, modules=())
    owner = await _user(db_session)
    owner_without_web = await _user(db_session, modules=("clients",))
    client = await _client(db_session, name="Tienda Sol")
    for person in (owner, owner_without_web):
        db_session.add(Project(name="SEO", client_id=client.id, owner_id=person.id, status=ProjectStatus.active))
    await db_session.commit()
    watch = await _watch(db_session, client)
    await _change(db_session, client, watch, "warning")
    critical = await _change(db_session, client, watch, "critical")
    await db_session.execute(update(WebChangeItem).where(WebChangeItem.change_id == critical.id)
                             .values(rule_code="NOINDEX_ADDED", field="robots"))
    await db_session.commit()
    now = datetime(2026, 10, 21, 9)  # noqa: DTZ001 - las incidencias guardan UTC naive

    for person in (admin, owner, owner_without_web):
        await reconcile_recipient(db_session, person.id, now=now)
    (row,) = await _incidents(db_session, admin)
    assert row.incident_severity == "critical" and row.title == "Cambio crítico en la web sin revisar: Tienda Sol"
    assert row.dedupe_key == f"{CLIENT_WEB_CRITICAL_CHANGE}:client:{client.id}:open"
    assert "noindex añadido" in row.message and "/master-nutricion" in row.message
    assert row.link_url == f"/web/cambios?cliente={client.id}"
    assert len(await _incidents(db_session, owner)) == 1
    assert await _incidents(db_session, owner_without_web) == []

    # Revisarlo (API) resuelve la incidencia en la siguiente pasada.
    admin_client = await make_member_client([("web", True, True)])
    assert (await admin_client.post(f"/api/web/changes/{critical.id}/ack", json={})).status_code == 200
    await reconcile_recipient(db_session, admin.id, now=now)
    row = (await _rows(db_session, Notification, Notification.id == row.id))[0]
    assert row.incident_state == "resolved" and row.incident_resolution_reason == "condition_cleared"

    # Una URL silenciada o archivada no avisa.
    await _change(db_session, client, watch, "critical")
    watch.muted = True
    await db_session.commit()
    await reconcile_recipient(db_session, admin.id, now=now)
    assert await _incidents(db_session, admin) == []
    await admin_client.aclose()


# ── Estado del cliente ───────────────────────────────────────────────


async def test_estado_del_cliente_solo_cuenta_las_urls_propias(db_session):
    own = await _client(db_session, name="Propia")
    without = await _client(db_session, name="Sin URLs")
    now = datetime.now(UTC)
    watch = await _watch(db_session, own)
    db_session.add(WebWatchState(watch_id=watch.id, client_id=own.id, last_checked_at=now))
    await db_session.commit()
    viewer = Viewer(is_admin=False, tasks=False, digests=False, timesheet=False, web=True)

    rows = {r["client_id"]: r for r in await portfolio(db_session, [own, without], viewer)}
    assert rows[own.id]["status"] == "ok" and rows[own.id]["web_changes"]["critical"] == 0
    # Sin URLs propias no hay señal de cambios (Vigil retirado en la fase 3b).
    assert rows[without.id]["web_changes"] is None and rows[without.id]["status"] == "no_data"
    assert "vigil" not in rows[without.id]

    await _change(db_session, own, watch, "critical")
    rows = {r["client_id"]: r for r in await portfolio(db_session, [own], viewer)}
    assert rows[own.id]["status"] == "watch" and rows[own.id]["reasons"] == ["1 cambio crítico en la web sin revisar"]

    blind = Viewer(is_admin=False, tasks=False, digests=False, timesheet=False)
    row = (await portfolio(db_session, [own], blind))[0]
    assert row["web_changes"] is None and row["status"] == "no_data"


# ── Retención ────────────────────────────────────────────────────────


async def test_retencion_borra_barridos_de_mas_de_180_dias_y_conserva_los_cambios(db_session, monkeypatch):
    from backend.db import database
    from backend.startup import background_tasks

    client = await _client(db_session)
    watch = await _watch(db_session, client)
    now = datetime.now(UTC)
    old = WebSweepRun(client_id=client.id, run_date=(now - timedelta(days=200)).date(), trigger="scheduler",
                      status="done", started_at=now - timedelta(days=200))
    recent = WebSweepRun(client_id=client.id, run_date=(now - timedelta(days=10)).date(), trigger="scheduler",
                         status="done", started_at=now - timedelta(days=10))
    db_session.add_all([old, recent])
    await db_session.flush()
    db_session.add(WebRunError(run_id=old.id, client_id=client.id, kind="timeout"))
    db_session.add(WebChange(client_id=client.id, watch_id=watch.id, run_id=old.id, max_severity="info",
                             detected_at=now - timedelta(days=200)))
    await db_session.commit()
    monkeypatch.setattr(database, "async_session", _Factory(db_session))
    await background_tasks._retention_cleanup_once()
    left = await _rows(db_session, WebSweepRun, WebSweepRun.client_id == client.id)
    assert [r.id for r in left] == [recent.id]
    assert await _rows(db_session, WebRunError, WebRunError.client_id == client.id) == []
    (change,) = await _rows(db_session, WebChange, WebChange.client_id == client.id)
    assert change.run_id is None


# ── API de URLs y ajustes ────────────────────────────────────────────


async def test_api_urls_permisos_validacion_y_archivo(db_session, make_member_client, monkeypatch):
    client = await _client(db_session, slack=False)
    reader = await make_member_client([("web", True, False)])
    writer = await make_member_client([("web", True, True)])
    nobody = await make_member_client([("clients", True, True)])
    base = f"/api/clients/{client.id}/web/watches"

    assert (await nobody.get(base)).status_code == 403
    assert (await reader.post(base, json={"url": "https://fit.es/"})).status_code == 403
    created = await writer.post(base, json={"url": "Fit.es/curso#temario", "label": " Curso ", "watch_html": True})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["url"] == "https://fit.es/curso" and body["label"] == "Curso" and body["state"] is None
    assert (await writer.post(base, json={"url": "https://fit.es/curso"})).status_code == 409
    for bad in ("http://10.0.0.1/", "https://fit.es:8080/", "http://db.railway.internal/", "http://169.254.169.254/"):
        assert (await writer.post(base, json={"url": bad})).status_code == 422, bad
    assert (await writer.patch(f"/api/web/watches/{body['id']}", json={"ignore_selectors": ["<<<"]})
            ).status_code == 422

    bulk = (await writer.post(f"{base}/bulk", json={"urls": ["fit.es/curso", "fit.es/a", "fit.es/a", "ftp://x"]})
            ).json()
    assert (bulk["created"], bulk["skipped_duplicates"], len(bulk["invalid"])) == (1, 2, 1)

    # Archivar: fuera de la lista y del barrido, con su historial; volver a darla de alta la recupera.
    watch_id = body["id"]
    db_session.add(WebWatchState(watch_id=watch_id, client_id=client.id, scope_missed=True))
    await db_session.commit()
    patched = (await writer.patch(f"/api/web/watches/{watch_id}", json={"content_selector": ".x", "muted": True})
               ).json()
    assert patched["content_selector"] == ".x" and patched["muted"] and patched["state"]["scope_missed"] is False
    assert (await writer.post(f"/api/web/watches/{watch_id}/archive")).json()["archived_at"]
    listed = (await reader.get(base)).json()
    assert [w["url"] for w in listed["watches"]] == ["https://fit.es/a"] and listed["enabled"] is False
    assert len((await reader.get(f"{base}?include_archived=true")).json()["watches"]) == 2
    assert (await writer.post(f"/api/web/watches/{watch_id}/check")).status_code == 409
    again = await writer.post(base, json={"url": "https://fit.es/curso"})
    assert again.status_code == 201 and again.json()["id"] == watch_id and again.json()["archived_at"] is None
    detail = (await reader.get(f"/api/web/watches/{watch_id}")).json()
    assert detail["watch"]["id"] == watch_id and detail["changes"] == []
    assert (await reader.get(f"/api/web/watches/{watch_id}/history")).json() == {"snapshots": []}
    assert (await reader.get("/api/web/watches/no-es-un-uuid")).status_code == 404

    # Sitemap (sin red) y previsualización (una petición, con lo que se vigilaría).
    from backend.api.routes import web_watches as routes

    async def fake_sitemap(url, *, limit, user_agent):
        assert url == "https://fit.es/sitemap.xml"
        return ["https://fit.es/blog/1", "https://fit.es/blog/2", "https://fit.es/tienda"], True

    monkeypatch.setattr(routes, "fetch_sitemap_urls", fake_sitemap)
    imported = (await writer.post(f"{base}/import-sitemap", json={
        "sitemap_url": "fit.es/sitemap.xml", "include": "/blog/", "limit": 10})).json()
    assert imported["created"] == 2 and imported["sitemap_has_more"] is True and imported["found_in_sitemap"] == 2

    async def fake_fetch(url, **kw):
        assert kw["timeout"] <= 20
        return FetchResult(200, 10, url, body=_cafyd().encode())

    monkeypatch.setattr(routes, "fetch", fake_fetch)
    preview = (await writer.post(f"/api/web/watches/{watch_id}/preview",
                                 json={"content_selector": ".claustro", "ignore_selectors": ["[aria-live]"]})).json()
    assert preview["selector_matches"] is True and preview["watched_words"] == 0
    (pruned,) = preview["ignored"]
    # Lo que se lleva cada selector de poda, medido: así se ve que ``[aria-live]`` ciega la card.
    assert pruned["selector"] == "[aria-live]" and pruned["nodes"] == 2 and pruned["words"] > 10
    assert (await reader.post(f"/api/web/watches/{watch_id}/preview", json={})).status_code == 403
    for c in (reader, writer, nobody):
        await c.aclose()


async def test_api_ajustes_de_captura_y_calendario(db_session, make_member_client):
    client = await _client(db_session, slack=False)
    reader = await make_member_client([("web", True, False)])
    writer = await make_member_client([("web", True, True)])
    url = f"/api/clients/{client.id}/web/settings"

    empty = (await reader.get(f"{url}/changes")).json()
    assert empty["stored"]["default_ignore_selectors"] is None and empty["slack"] == "disabled"
    assert empty["effective"]["default_ignore_selectors"] == ["nav", "footer", "header", ".cookie-banner",
                                                               "#onetrust-consent-sdk"]
    assert (await reader.put(f"{url}/capture", json={"max_concurrency": 2})).status_code == 403
    saved = (await writer.put(f"{url}/capture", json={"default_ignore_selectors": ["nav"], "max_concurrency": 2,
                                                       "digest_min_severity": "warning"})).json()
    assert saved["stored"]["default_ignore_selectors"] == ["nav"] and saved["effective"]["max_concurrency"] == 2
    assert (await writer.put(f"{url}/capture", json={"max_concurrency": 99})).status_code == 422
    # null = vuelve al default del código; lo que no viene no se toca.
    reset = (await writer.put(f"{url}/capture", json={"default_ignore_selectors": None})).json()
    assert reset["stored"]["default_ignore_selectors"] is None and reset["stored"]["max_concurrency"] == 2
    cal = (await writer.put(f"{url}/calendar", json={"sweep_weekdays": [5, 1, 1], "sweep_skip_dates": ["2026-12-24"],
                                                      "sweep_summary_to_slack": False})).json()
    assert cal["effective"]["sweep_weekdays"] == [1, 5] and cal["effective"]["sweep_summary_to_slack"] is False
    assert (await writer.put(f"{url}/calendar", json={"sweep_weekdays": [8]})).status_code == 422
    assert (await writer.put(f"{url}/calendar", json={"sweep_weekdays": [1], "sweep_skip_dates": ["mañana"]})
            ).status_code == 422
    holidays = (await reader.get("/api/web/settings/holidays?anio=2026")).json()
    assert "2026-04-03" in holidays["holidays"]
    row = await _settings(db_session, client)
    assert row.slack_webhook_url is None and row.slack_enabled is False
    for c in (reader, writer):
        await c.aclose()


async def test_nada_de_la_vigilancia_de_cambios_entra_en_el_deshacer(db_session, make_member_client):
    client = await _client(db_session, slack=False)
    writer = await make_member_client([("web", True, True)])
    watch = await _watch(db_session, client)
    change = await _change(db_session, client, watch, "critical")
    before = await db_session.scalar(select(func.count()).select_from(ChangeLog))
    base = f"/api/clients/{client.id}/web/watches"
    assert (await writer.post(base, json={"url": "https://fit.es/otra"})).status_code == 201
    assert (await writer.patch(f"/api/web/watches/{watch.id}", json={"label": "Otra"})).status_code == 200
    assert (await writer.post(f"/api/web/changes/{change.id}/ack", json={})).status_code == 200
    assert (await writer.put(f"/api/clients/{client.id}/web/settings/calendar",
                             json={"sweep_weekdays": [1]})).status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(ChangeLog)) == before
    # Y el panel de Deshacer de quien lo hizo sigue vacío.
    assert (await writer.get("/api/changes/recent")).json() == []
    await writer.aclose()


# ── Interruptor por cliente ──────────────────────────────────────────


async def test_con_la_vigilancia_apagada_ni_se_barre_ni_avisa_ni_cuenta(db_session, make_member_client, monkeypatch):
    monkeypatch.setattr(settings, "WEB_SWEEP_LOCAL_TIME", "06:30")
    off = await _client(db_session, name="Apagado", changes=False)
    watch = await _watch(db_session, off)
    writer = await make_member_client([("web", True, True)])
    check = await writer.post(f"/api/web/watches/{watch.id}/check")
    assert check.status_code == 409 and "apagada" in check.json()["detail"]
    assert (await writer.post(f"/api/clients/{off.id}/web/watches/check-all")).status_code == 409
    # Un "Comprobar" que quedó pedido antes de apagarla tampoco se recoge.
    await db_session.execute(update(WebWatch).where(WebWatch.id == watch.id).values(check_requested_at=datetime.now(UTC)))
    await db_session.commit()
    web = Web(pagina())
    later = datetime(2026, 10, 21, 5, 0, tzinfo=UTC)
    result = await sweep.run_cycle(_Factory(db_session), now=later, fetcher=web.fetch, sleep=_no_sleep)
    assert result.manual == [] and result.scheduled is None and web.calls == []
    # Lo detectado antes (con la vigilancia encendida) ni abre incidencia ni cuenta en su estado.
    await _change(db_session, off, watch, "critical")
    admin = await _user(db_session, role=UserRole.admin, modules=())
    await reconcile_recipient(db_session, admin.id, now=datetime(2026, 10, 21, 9))  # noqa: DTZ001
    assert await _incidents(db_session, admin) == []
    assert await change_blocks(db_session, [off.id]) == {}
    await writer.aclose()


async def test_el_interruptor_se_enciende_con_escritura_y_no_borra_nada(db_session, make_member_client):
    client = await _client(db_session, changes=False, slack=False)
    watch = await _watch(db_session, client)
    reader = await make_member_client([("web", True, False)])
    writer = await make_member_client([("web", True, True)])
    url = f"/api/clients/{client.id}/web/settings/changes-enabled"
    assert (await reader.get(f"/api/clients/{client.id}/web/settings/changes")).json()["changes_enabled"] is False
    assert (await reader.put(url, json={"enabled": True})).status_code == 403
    on = await writer.put(url, json={"enabled": True})
    assert on.status_code == 200 and on.json()["changes_enabled"] is True
    assert (await writer.post(f"/api/web/watches/{watch.id}/check")).status_code == 202
    off = await writer.put(url, json={"enabled": False})
    assert off.json()["changes_enabled"] is False
    assert len(await _rows(db_session, WebWatch, WebWatch.client_id == client.id)) == 1
    await reader.aclose()
    await writer.aclose()
