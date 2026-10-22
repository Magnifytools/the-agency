"""Importación de Vigil (``scripts/import_vigil.py``) contra Postgres real.

El SQLite de Vigil se construye en cada test con SUS migraciones, copiadas en
``tests/fixtures/vigil/`` (001-004, sin tocar) para que CI no dependa del repo
de Vigil. Encima, un cliente con webhook cifrado como lo cifra Vigil (Fernet
sobre SHA-256 de ``VIGIL_SECRET_KEY``), revisiones de un usuario que existe en
The Agency y de otro que no, y un ``watch_state`` sacado del extractor real.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from backend.config import settings
from backend.core.security import decrypt_vault_secret
from backend.db.models import (
    Client, ClientStatus, ClientWebSettings, User, UserRole, WebChange, WebChangeItem, WebRunError, WebSnapshot,
    WebSweepRun, WebWatch, WebWatchState,
)
from backend.scripts import import_vigil, web_calibrate
from backend.scripts.import_vigil import ImportAborted, load_vigil, run_import
from backend.services.web import capture_defaults as defaults
from backend.services.web.extractor import CaptureConfig, extract
from backend.services.web.safe_http import FetchResult
from backend.services.web.slack import DeliveryResult
from backend.services.web.sweep import compare

pytestmark = pytest.mark.integration

MIGRATIONS = Path(__file__).resolve().parents[1] / "fixtures" / "vigil"
VIGIL_KEY = "clave-de-vigil-solo-para-tests"
HOOK = "https://hooks.slack.com/services/T000/B000/abcdEFGHijkl"
URL1 = "https://fitgeneration.es/master-nutricion"
URL2 = "https://fitgeneration.es/contacto"
URL3 = "https://demo.example.com/"
T0 = "2026-10-01T04:30:00Z"

PAGINA = """<html lang="es"><head><title>Máster en Nutrición | Fit Generation</title>
<meta name="description" content="Fórmate con los mejores."><link rel="canonical" href="{url}">
</head><body><main><h1>Máster en Nutrición</h1>
<p>El temario cubre anatomía y fisiología aplicadas al deporte.</p><a href="/contacto">Contacto</a>
</main></body></html>""".format(url=URL1)


def _ids() -> dict[str, str]:
    return {k: str(uuid.uuid4()) for k in (
        "fit", "demo", "u_match", "u_gone", "w1", "w2", "w3", "r1", "r2", "s1", "e1", "c1", "c2", "c3",
        "i1", "i2", "i3", "shot")}


def vigil_encrypt(plain: str, key: str = VIGIL_KEY) -> str:
    """Como ``Vigil/backend/app/services/crypto.encrypt_secret``."""
    fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))
    return "v1:" + fernet.encrypt(plain.encode()).decode()


def real_capture():
    """Lo que Vigil guardó la última vez que miró URL1 (mismo extractor)."""
    cap = extract(PAGINA, base_url=URL1, final_url=URL1, status_code=200, headers={}, cfg=CaptureConfig(
        ignore_selectors=defaults.DEFAULT_IGNORE_SELECTORS, ignore_regexes=defaults.DEFAULT_IGNORE_REGEXES))
    cmp = compare(capture=cap, flags={"watch_seo": True, "watch_content": True, "watch_links": False,
                                      "watch_html": False},
                  prev_hashes=None, prev_seo=None, prev_links=None, prev_text_inline=None, prev_text_gz=None,
                  prev_html_gz=None, store_html=False)
    return cap, cmp


def build_vigil_db(path: Path, ids: dict[str, str], *, slugs=("fit-vigil", "demo-vigil"), extra_client=None) -> Path:
    conn = sqlite3.connect(path)
    for sql in sorted(MIGRATIONS.glob("*.sql")):
        conn.executescript(sql.read_text())
    cap, cmp = real_capture()
    x = conn.execute
    for key, slug, name in ((ids["fit"], slugs[0], "Fit Generation"), (ids["demo"], slugs[1], "Demo")):
        x("insert into clients (id, slug, name, created_at, updated_at) values (?,?,?,?,?)", (key, slug, name, T0, T0))
    if extra_client:
        x("insert into clients (id, slug, name, created_at, updated_at) values (?,?,?,?,?)",
          (str(uuid.uuid4()), extra_client, "Sin pareja", T0, T0))
    x("insert into users (id, email, display_name, password_hash, created_at, updated_at) values (?,?,?,?,?,?)",
      (ids["u_match"], "Revisora.Vigil@Test.com", "Revisora", "x", T0, T0))
    x("insert into users (id, email, display_name, password_hash, created_at, updated_at) values (?,?,?,?,?,?)",
      (ids["u_gone"], "ex@otra.com", "Ex Empleado", "x", T0, T0))
    # Fit: webhook cifrado por Vigil, concurrencia personalizada, un festivo; el resto, defaults.
    x("""insert into client_settings (client_id, slack_webhook_url, slack_channel_hint, slack_enabled,
         max_concurrency, user_agent, sweep_skip_dates, updated_at) values (?,?,?,?,?,?,?,?)""",
      (ids["fit"], vigil_encrypt(HOOK), "#fit-avisos", 1, 3, "Mozilla/5.0 Chrome/126", '["2026-12-24"]', T0))
    x("insert into client_settings (client_id, updated_at) values (?,?)", (ids["demo"], T0))
    for wid, cid, url, label in ((ids["w1"], ids["fit"], URL1, "Máster"), (ids["w2"], ids["fit"], URL2, None),
                                 (ids["w3"], ids["demo"], URL3, "Home")):
        x("""insert into watches (id, client_id, url, label, created_by, created_at, updated_at)
             values (?,?,?,?,?,?,?)""", (wid, cid, url, label, ids["u_match"], T0, T0))
    x("""insert into sweep_runs (id, client_id, run_date, trigger, status, started_at, finished_at, watches_total,
         watches_done, watches_error, changes_found, notify_status) values (?,?,?,?,?,?,?,?,?,?,?,?)""",
      (ids["r1"], ids["fit"], "2026-10-01", "scheduler", "partial", T0, T0, 2, 1, 1, 2, "sent"))
    x("""insert into sweep_runs (id, client_id, run_date, trigger, status, started_at) values (?,?,?,?,?,?)""",
      (ids["r2"], ids["demo"], "2026-10-01", "manual", "done", T0))
    x("""insert into snapshots (id, watch_id, client_id, run_id, captured_at, content_hash, html_hash, status_code,
         byte_size, text_gz, html_gz, text_inline) values (?,?,?,?,?,?,?,?,?,?,?,?)""",
      (ids["s1"], ids["w1"], ids["fit"], ids["r1"], T0, cap.hashes["content"], cap.hashes["html"], 200,
       len(PAGINA), cmp.text_gz, gzip.compress(b"<html>vigil</html>"), cmp.text_inline))
    x("""insert into watch_state (watch_id, client_id, last_checked_at, last_status_code, hash_seo, hash_content,
         hash_links, hash_html, seo_json, links_json, last_snapshot_id, checking_since, scope_missed, updated_at)
         values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (ids["w1"], ids["fit"], T0, 200, cap.hashes["seo"], cap.hashes["content"], cap.hashes["links"],
       cap.hashes["html"], json.dumps(cap.seo), json.dumps(cap.links), ids["s1"], T0, 0, T0))
    x("""insert into watch_state (watch_id, client_id, hash_seo, seo_json, updated_at) values (?,?,?,?,?)""",
      (ids["w2"], ids["fit"], "f" * 64, json.dumps({"title": "Otra página"}), T0))
    x("""insert into run_errors (id, run_id, client_id, watch_id, kind, message, status_code, created_at)
         values (?,?,?,?,?,?,?,?)""", (ids["e1"], ids["r1"], ids["fit"], ids["w2"], "http_error", "503", 503, T0))
    x("""insert into changes (id, client_id, watch_id, run_id, snapshot_id, max_severity, detected_at,
         acknowledged_by, acknowledged_at, note) values (?,?,?,?,?,?,?,?,?,?)""",
      (ids["c1"], ids["fit"], ids["w1"], ids["r1"], ids["s1"], "warning", T0, ids["u_match"], T0, "visto"))
    x("""insert into changes (id, client_id, watch_id, run_id, max_severity, detected_at, acknowledged_by,
         acknowledged_at) values (?,?,?,?,?,?,?,?)""",
      (ids["c2"], ids["fit"], ids["w2"], ids["r1"], "critical", T0, ids["u_gone"], T0))
    x("""insert into changes (id, client_id, watch_id, run_id, max_severity, detected_at) values (?,?,?,?,?,?)""",
      (ids["c3"], ids["demo"], ids["w3"], ids["r2"], "info", T0))
    for iid, chid, cid, kind, sev, rule, detail in (
        (ids["i1"], ids["c1"], ids["fit"], "seo", "warning", "TITLE_CHANGED", None),
        (ids["i2"], ids["c2"], ids["fit"], "availability", "critical", "STATUS_ERROR", '{"status": 503}'),
        (ids["i3"], ids["c3"], ids["demo"], "links", "info", "LINKS_CHANGED", '{"added": ["/a"], "removed": []}'),
    ):
        x("""insert into change_items (id, change_id, client_id, kind, field, severity, rule_code, before_val,
             after_val, detail, created_at) values (?,?,?,?,?,?,?,?,?,?,?)""",
          (iid, chid, cid, kind, "title", sev, rule, "antes", "después", detail, T0))
    x("""insert into page_shots (id, watch_id, client_id, taken_at, width, height, byte_size, png)
         values (?,?,?,?,?,?,?,?)""", (ids["shot"], ids["w1"], ids["fit"], T0, 1, 1, 4, b"\x89PNG"))
    conn.commit()
    conn.close()
    return path


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    # Con la clave de desarrollo el script se niega a guardar webhooks.
    monkeypatch.setattr(settings, "VAULT_KEY", "clave-de-vault-de-agency-para-tests")


async def _agency(db, slugs=("fit-vigil", "demo-vigil")):
    """Dos clientes enlazados por ``vigil_slug`` y la revisora (email en otra caja)."""
    fit = Client(name=f"Fit {uuid.uuid4().hex[:6]}", status=ClientStatus.active, vigil_slug=slugs[0])
    demo = Client(name=f"Demo {uuid.uuid4().hex[:6]}", status=ClientStatus.active, vigil_slug=slugs[1])
    user = User(email="revisora.vigil@test.com", full_name="Revisora Agency", hashed_password="x",
                role=UserRole.member, is_active=True)
    db.add_all([fit, demo, user])
    await db.flush()
    # Lo de antes de importar queda fuera del SAVEPOINT que deshace el --dry-run.
    await db.commit()
    return fit, demo, user


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _all_counts(db) -> dict[str, int]:
    return {m.__tablename__: await _count(db, m) for m in (
        WebWatch, WebSweepRun, WebSnapshot, WebWatchState, WebRunError, WebChange, WebChangeItem, ClientWebSettings)}


def _key():
    return VIGIL_KEY


# ── Simulacro, importación, repetición ────────────────────────────────


async def test_dry_run_no_escribe_nada_pero_cuenta_lo_que_haria(db_session, tmp_path):
    ids = _ids()
    data = load_vigil(str(build_vigil_db(tmp_path / "vigil.db", ids)))
    await _agency(db_session)
    before = await _all_counts(db_session)

    report = await run_import(db_session, data, get_vigil_key=_key, dry_run=True)

    assert await _all_counts(db_session) == before
    assert report.dry_run
    assert {n: c.inserted for n, c in report.tables.items()} == {
        "web_watches": 3, "web_sweep_runs": 2, "web_snapshots": 1, "web_watch_state": 2, "web_run_errors": 1,
        "web_changes": 3, "web_change_items": 3, "client_web_settings": 2}
    # El "después" es el simulado: lo que habría.
    assert report.tables["web_watches"].after == before["web_watches"] + 3
    assert "SIMULACRO" in import_vigil.format_report(report)


async def test_importa_todo_y_repetir_no_duplica(db_session, tmp_path):
    ids = _ids()
    data = load_vigil(str(build_vigil_db(tmp_path / "vigil.db", ids)))
    fit, demo, user = await _agency(db_session)
    before = await _all_counts(db_session)

    report = await run_import(db_session, data, get_vigil_key=_key)
    after = await _all_counts(db_session)
    assert {k: after[k] - before[k] for k in after} == {
        "web_watches": 3, "web_sweep_runs": 2, "web_snapshots": 1, "web_watch_state": 2, "web_run_errors": 1,
        "web_changes": 3, "web_change_items": 3, "client_web_settings": 2}
    per_client = {c.slug: c for c in report.clients}
    assert per_client["fit-vigil"].agency_id == fit.id and per_client["fit-vigil"].inserted["web_changes"] == 2
    assert per_client["demo-vigil"].agency_id == demo.id and per_client["demo-vigil"].inserted["web_watches"] == 1

    # Los ids de Vigil se conservan (los enlaces ya enviados a Slack siguen valiendo).
    w1 = await db_session.get(WebWatch, uuid.UUID(ids["w1"]))
    assert w1.client_id == fit.id and w1.url == URL1 and w1.created_by == user.id and w1.is_active
    run = await db_session.get(WebSweepRun, uuid.UUID(ids["r1"]))
    assert run.run_date.isoformat() == "2026-10-01" and run.status == "partial" and run.notify_status == "sent"
    snap = await db_session.get(WebSnapshot, uuid.UUID(ids["s1"]))
    assert gzip.decompress(snap.html_gz) == b"<html>vigil</html>"  # byte a byte
    _cap, cmp = real_capture()
    assert snap.text_gz == cmp.text_gz and snap.text_inline == cmp.text_inline

    # El estado: hashes, JSON ya como JSONB, la última captura; sin "comprobando".
    state = await db_session.get(WebWatchState, uuid.UUID(ids["w1"]))
    cap, _ = real_capture()
    assert state.hash_seo == cap.hashes["seo"] and state.hash_content == cap.hashes["content"]
    assert state.seo_json == json.loads(json.dumps(cap.seo)) and state.links_json == json.loads(json.dumps(cap.links))
    assert state.last_snapshot_id == uuid.UUID(ids["s1"]) and state.checking_since is None
    assert state.scope_missed is False and state.client_id == fit.id

    # Revisiones: por email sin mayúsculas, o el nombre de Vigil si no hay usuario.
    c1 = await db_session.get(WebChange, uuid.UUID(ids["c1"]))
    c2 = await db_session.get(WebChange, uuid.UUID(ids["c2"]))
    c3 = await db_session.get(WebChange, uuid.UUID(ids["c3"]))
    assert c1.acknowledged_by == user.id and c1.acknowledged_by_label == "Revisora Agency" and c1.note == "visto"
    assert c1.snapshot_id == uuid.UUID(ids["s1"])
    assert c2.acknowledged_by is None and c2.acknowledged_by_label == "Ex Empleado" and c2.acknowledged_at
    assert c3.acknowledged_at is None and c3.acknowledged_by_label is None and c3.client_id == demo.id
    assert report.acks_matched == 1 and report.acks_by_label == 1
    i3 = await db_session.get(WebChangeItem, uuid.UUID(ids["i3"]))
    assert i3.detail == {"added": ["/a"], "removed": []}
    i1 = await db_session.get(WebChangeItem, uuid.UUID(ids["i1"]))
    assert i1.detail is None
    assert (await db_session.execute(select(WebChangeItem.id).where(
        WebChangeItem.id == uuid.UUID(ids["i1"]), WebChangeItem.detail.is_(None)))).scalar_one()  # NULL de SQL

    # Ajustes: lo personalizado se copia; lo que era el default de Vigil queda NULL.
    fit_cfg = await db_session.get(ClientWebSettings, fit.id)
    assert fit_cfg.max_concurrency == 3 and fit_cfg.user_agent == "Mozilla/5.0 Chrome/126"
    assert fit_cfg.sweep_skip_dates == ["2026-12-24"] and fit_cfg.slack_enabled is True
    assert fit_cfg.slack_channel_hint == "#fit-avisos"
    for column in ("digest_min_severity", "default_ignore_selectors", "default_ignore_regexes", "request_timeout_s",
                   "crawl_delay_ms", "sweep_weekdays", "sweep_summary_to_slack", "default_content_selector"):
        assert getattr(fit_cfg, column) is None, column
    demo_cfg = await db_session.get(ClientWebSettings, demo.id)
    assert demo_cfg.slack_webhook_url is None and demo_cfg.max_concurrency is None and not demo_cfg.slack_enabled

    # Segunda vez: nada nuevo, mismos totales.
    again = await run_import(db_session, data, get_vigil_key=_key)
    assert await _all_counts(db_session) == after
    assert all(c.inserted == 0 for c in again.tables.values())
    assert {c.slug: c.settings for c in again.clients} == {"demo-vigil": "sin cambios", "fit-vigil": "sin cambios"}


async def test_el_webhook_se_recifra_con_la_clave_de_agency(db_session, tmp_path):
    data = load_vigil(str(build_vigil_db(tmp_path / "vigil.db", _ids())))
    fit, _demo, _user = await _agency(db_session)
    await run_import(db_session, data, get_vigil_key=_key)

    stored = (await db_session.get(ClientWebSettings, fit.id)).slack_webhook_url
    raw_vigil = next(s["slack_webhook_url"] for s in data["client_settings"] if s["slack_webhook_url"])
    assert stored.startswith("v1:") and stored != raw_vigil and HOOK not in stored
    assert decrypt_vault_secret(stored) == HOOK


async def test_clave_de_vigil_equivocada_aborta_sin_escribir(db_session, tmp_path):
    data = load_vigil(str(build_vigil_db(tmp_path / "vigil.db", _ids())))
    await _agency(db_session)
    before = await _all_counts(db_session)
    with pytest.raises(ImportAborted, match="no descifra"):
        await run_import(db_session, data, get_vigil_key=lambda: "otra-clave")
    assert await _all_counts(db_session) == before


async def test_con_la_clave_de_desarrollo_no_guarda_webhooks(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "VAULT_KEY", None)
    monkeypatch.setattr(settings, "SECRET_KEY", import_vigil.DEFAULT_SECRET_KEY)
    data = load_vigil(str(build_vigil_db(tmp_path / "vigil.db", _ids())))
    await _agency(db_session)
    with pytest.raises(ImportAborted, match="desarrollo"):
        await run_import(db_session, data, get_vigil_key=_key)


async def test_ajustes_de_agency_mandan(db_session, tmp_path):
    """El monitor de caídas ya dejó Slack y User-Agent: no se pisan."""
    from backend.core.security import encrypt_vault_secret

    data = load_vigil(str(build_vigil_db(tmp_path / "vigil.db", _ids())))
    fit, _demo, _user = await _agency(db_session)
    own_hook = "https://hooks.slack.com/services/T1/B1/propio"
    db_session.add(ClientWebSettings(client_id=fit.id, slack_webhook_url=encrypt_vault_secret(own_hook),
                                     slack_enabled=False, user_agent="UA de Agency"))
    await db_session.commit()

    report = await run_import(db_session, data, get_vigil_key=_key)
    cfg = await db_session.get(ClientWebSettings, fit.id, populate_existing=True)
    assert decrypt_vault_secret(cfg.slack_webhook_url) == own_hook and cfg.slack_enabled is False
    assert cfg.user_agent == "UA de Agency"
    assert cfg.max_concurrency == 3 and cfg.sweep_skip_dates == ["2026-12-24"]  # lo vacío sí se completa
    fit_line = next(c.settings for c in report.clients if c.slug == "fit-vigil")
    assert "se conserva el de The Agency" in fit_line


# ── Clientes ──────────────────────────────────────────────────────────


async def test_slug_sin_cliente_aborta_y_map_o_skip_lo_resuelven(db_session, tmp_path):
    data = load_vigil(str(build_vigil_db(tmp_path / "vigil.db", _ids(), extra_client="huerfano")))
    _fit, demo, _user = await _agency(db_session)
    demo_id = demo.id  # un rollback caduca los objetos de la sesión
    before = await _all_counts(db_session)

    with pytest.raises(ImportAborted, match="huerfano"):
        await run_import(db_session, data, get_vigil_key=_key)
    assert await _all_counts(db_session) == before

    skipped = await run_import(db_session, data, get_vigil_key=_key, skip={"huerfano"}, dry_run=True)
    assert skipped.skipped_slugs == ["huerfano"]

    # --map gana a vigil_slug: el slug huérfano va a un cliente sin slug.
    other = Client(name=f"Otro {uuid.uuid4().hex[:6]}", status=ClientStatus.active)
    db_session.add(other)
    await db_session.commit()
    other_id = other.id
    mapped = await run_import(db_session, data, get_vigil_key=_key, mapping={"huerfano": other_id}, dry_run=True)
    assert {c.slug: c.agency_id for c in mapped.clients}["huerfano"] == other_id

    with pytest.raises(ImportAborted, match="mismo cliente"):
        await run_import(db_session, data, get_vigil_key=_key, mapping={"huerfano": demo_id})
    with pytest.raises(ImportAborted, match="no hay ningún cliente"):
        await run_import(db_session, data, get_vigil_key=_key, mapping={"huerfano": 987654321})
    with pytest.raises(ImportAborted, match="no existen en Vigil"):
        await run_import(db_session, data, get_vigil_key=_key, skip={"huerfano", "nada"})


async def test_skip_deja_fuera_todo_lo_del_cliente(db_session, tmp_path):
    ids = _ids()
    data = load_vigil(str(build_vigil_db(tmp_path / "vigil.db", ids)))
    _fit, demo, _user = await _agency(db_session)
    report = await run_import(db_session, data, get_vigil_key=_key, skip={"fit-vigil"})
    assert [c.slug for c in report.clients] == ["demo-vigil"]
    assert await db_session.get(WebWatch, uuid.UUID(ids["w1"])) is None
    assert (await db_session.get(WebWatch, uuid.UUID(ids["w3"]))).client_id == demo.id
    # Sin el cliente con webhook no hace falta la clave de Vigil.
    report2 = await run_import(db_session, data, skip={"fit-vigil"},
                               get_vigil_key=lambda: pytest.fail("no debía pedir la clave"))
    assert report2.tables["web_watches"].inserted == 0


async def test_url_que_ya_existe_con_otro_id_aborta(db_session, tmp_path):
    data = load_vigil(str(build_vigil_db(tmp_path / "vigil.db", _ids())))
    fit, _demo, _user = await _agency(db_session)
    db_session.add(WebWatch(client_id=fit.id, url=URL1))
    await db_session.commit()
    before = await _all_counts(db_session)
    with pytest.raises(ImportAborted, match="ya existe en The Agency"):
        await run_import(db_session, data, get_vigil_key=_key)
    assert await _all_counts(db_session) == before


def test_el_sqlite_se_abre_en_solo_lectura(tmp_path):
    path = build_vigil_db(tmp_path / "vigil.db", _ids())
    conn = import_vigil.open_vigil(str(path))
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("delete from clients")
    conn.close()
    with pytest.raises(ImportAborted):
        import_vigil.open_vigil(str(tmp_path / "no-existe.db"))


# ── Tras importar, el primer barrido no grita ─────────────────────────


class _Factory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


async def test_calibracion_tras_importar_no_avisa_ni_ve_cambios_falsos(db_session, tmp_path):
    ids = _ids()
    data = load_vigil(str(build_vigil_db(tmp_path / "vigil.db", ids)))
    fit, _demo, _user = await _agency(db_session)
    await run_import(db_session, data, get_vigil_key=_key)
    changes_before = await _count(db_session, WebChange)

    posted: list = []
    fetched: list[str] = []

    async def fetch(url, **_kw):
        fetched.append(url)
        return FetchResult(status_code=200, elapsed_ms=10, final_url=url, headers={}, body=PAGINA.encode())

    async def post(*args, **kwargs):
        posted.append(args)
        return DeliveryResult(ok=True, status=200)

    async def no_sleep(_s):
        return None

    results = await web_calibrate.calibrate(_Factory(db_session), [fit.id], fetcher=fetch, post=post,
                                            sleep=no_sleep, now=datetime(2026, 10, 22, 9, tzinfo=UTC))
    assert posted == [] and sorted(fetched) == sorted([URL1, URL2])
    (result,) = results
    # URL1 compara contra la captura importada de Vigil: misma página, cero cambios.
    # URL2 traía otro estado en Vigil: ése sí sale, y se revisa sin que el cliente se entere.
    assert result["client_id"] == fit.id and result["notify"] == "no_procede"
    new_changes = (await db_session.scalars(select(WebChange).where(WebChange.detected_at >= datetime(
        2026, 10, 22, tzinfo=UTC)))).all()
    assert {c.watch_id for c in new_changes} == {uuid.UUID(ids["w2"])}
    assert await _count(db_session, WebChange) == changes_before + 1
    run = await db_session.get(WebSweepRun, uuid.UUID(result["run_id"]))
    assert run.trigger == "manual" and run.notified_at is None
    assert "Nada se ha mandado a Slack" in web_calibrate.format_results(results)
