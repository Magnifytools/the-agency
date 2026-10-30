"""Importa a The Agency los datos de Vigil (fase 3a de Webs).

Lee el fichero SQLite de Vigil (``vigil.db``) en SÓLO LECTURA y copia, cliente
a cliente, lo que hace falta para que The Agency siga vigilando donde Vigil lo
dejó:

  watches        → web_watches
  sweep_runs     → web_sweep_runs
  snapshots      → web_snapshots      (cuerpos gzip tal cual, byte a byte)
  watch_state    → web_watch_state    (hashes, seo/links JSON, última captura)
  run_errors     → web_run_errors
  changes        → web_changes        (revisiones con su autor)
  change_items   → web_change_items
  client_settings→ client_web_settings (webhook de Slack RE-CIFRADO)

No se copian ``users``, ``client_members``, sesiones ni ``page_shots`` (The
Agency no hace capturas de pantalla).

Por qué ``watch_state`` es lo importante
----------------------------------------
Es la "versión anterior" con la que compara el barrido. Sin ella, la primera
pasada de The Agency vería cada URL por primera vez: no avisaría de nada esa
noche, y la siguiente compararía contra una captura hecha desde otra IP. Con
ella, el primer barrido compara contra la última captura de Vigil y sólo avisa
de lo que de verdad cambió.

Clientes
--------
``clients.slug`` de Vigil → columna ``clients.vigil_slug`` de The Agency (leída
con SQL: desde la fase 3b ya no está en el ORM; tras la 3c la columna no existe
y sólo vale ``--map``). Un slug sin
cliente aborta la importación ENTERA (nada escrito) salvo que se diga qué hacer
con él: ``--map slug=client_id`` o ``--skip slug``. Dos slugs al mismo cliente
también abortan: mezclarían URLs y barridos programados del mismo día.

Usuarios
--------
Por email (sin distinguir mayúsculas). Una revisión de alguien que no existe en
The Agency queda con ``acknowledged_by`` NULL y ``acknowledged_by_label`` = su
nombre (o email) en Vigil: se sigue viendo quién la revisó. El autor de una URL
sin usuario equivalente queda NULL.

Webhooks de Slack
-----------------
Vigil los guarda con Fernet (clave = SHA-256 de ``VIGIL_SECRET_KEY``, prefijo
``v1:``). Se descifran con esa clave y se vuelven a cifrar con
``encrypt_vault_secret`` (``VAULT_KEY`` o ``SECRET_KEY`` de The Agency). La
clave de Vigil se lee de la variable de entorno ``VIGIL_SECRET_KEY`` o se pide
por teclado sin eco; NUNCA como argumento (quedaría en el historial y en ``ps``)
y nunca se imprime. Una clave que no descifra aborta todo.

Si el cliente YA tiene ajustes web en The Agency (el monitor de caídas de la
fase 1), manda lo de The Agency: sólo se rellenan las columnas vacías y el Slack
sólo se importa si allí no hay webhook.

Valores por defecto
-------------------
En The Agency, NULL en ``client_web_settings`` = "lo que diga
``capture_defaults.py`` hoy". Un valor de Vigil igual a su default se importa
como NULL; así corregir un default en código sigue alcanzando a ese cliente.
El default viejo de selectores (con ``[aria-live]`` y ``.carousel``, que Vigil
retiró en su migración 003) también cuenta como default.

Ids
---
Vigil usa uuid4 en texto (``001_init.sql``: "PK = TEXT con uuid4") y The Agency
UUID en estas tablas, así que los ids se conservan: los enlaces a cambios ya
enviados a Slack siguen apuntando al mismo id. Si alguna fila no trajera un UUID
válido, su id se deriva con ``uuid5(VIGIL_NAMESPACE, "<tabla>:<id>")``:
determinista, así que repetir la importación da el mismo id y las referencias
entre tablas casan.

Idempotente y atómica
---------------------
Todo va en UNA transacción con ``ON CONFLICT (id) DO NOTHING``: repetirla no
duplica nada y un fallo no deja media importación. ``--dry-run`` hace
exactamente lo mismo y al final deshace la transacción: los recuentos que
enseña son los reales.

Uso (desde la raíz del repo, con ``DATABASE_URL`` y ``VAULT_KEY``/``SECRET_KEY``
de la base de datos destino; ver ``docs/vigil-migration.md``):

  python -m backend.scripts.import_vigil --sqlite vigil.db --dry-run
  python -m backend.scripts.import_vigil --sqlite vigil.db --map fit=12 --skip demo
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Callable
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, null, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.config import DEFAULT_SECRET_KEY, settings
from backend.core.security import decrypt_vault_secret, encrypt_vault_secret
from backend.db.models import (
    Client, ClientWebSettings, User, WebChange, WebChangeItem, WebRunError, WebSnapshot, WebSweepRun, WebWatch,
    WebWatchState,
)
from backend.services.web import capture_defaults as defaults

# Fijo para siempre: cambiarlo cambiaría los ids derivados y una segunda
# importación duplicaría lo que no traía UUID.
VIGIL_NAMESPACE = uuid.UUID("5f0c3a0e-7d1b-4c56-9a3e-1c2b7e9d4a10")

# El default de selectores que Vigil tenía antes de su migración 003.
_OLD_DEFAULT_SELECTORS = ["nav", "footer", "header", ".cookie-banner", "#onetrust-consent-sdk",
                          "[aria-live]", ".carousel"]

# Orden de inserción: cada tabla después de aquellas a las que apunta.
TABLES: tuple[tuple[str, Any], ...] = (
    ("web_watches", WebWatch),
    ("web_sweep_runs", WebSweepRun),
    ("web_snapshots", WebSnapshot),
    ("web_watch_state", WebWatchState),
    ("web_run_errors", WebRunError),
    ("web_changes", WebChange),
    ("web_change_items", WebChangeItem),
)


class ImportAborted(Exception):
    """La importación no puede seguir: no se ha escrito nada."""


# ---------------------------------------------------------------------------
# Conversión de valores de SQLite
# ---------------------------------------------------------------------------


def as_uuid(table: str, raw: Any) -> uuid.UUID | None:
    """El id de Vigil como UUID; si no lo es, uno derivado y estable."""
    if raw is None or raw == "":
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return uuid.uuid5(VIGIL_NAMESPACE, f"{table}:{raw}")


def as_dt(raw: Any) -> datetime | None:
    """ISO-8601 de Vigil ('2026-07-22T04:30:00Z') → datetime con zona (UTC)."""
    if raw is None or raw == "":
        return None
    value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def as_date(raw: Any) -> date | None:
    if raw is None or raw == "":
        return None
    return date.fromisoformat(str(raw)[:10])


def as_bool(raw: Any, default: bool = False) -> bool:
    return default if raw is None else bool(int(raw))


def cut(raw: Any, size: int) -> str | None:
    if raw is None:
        return None
    text = str(raw)
    return text[:size]


def as_json(raw: Any, warnings: list[str], where: str) -> Any:
    """Texto JSON de Vigil → valor Python (para JSONB). Roto = None y aviso."""
    if raw is None or raw == "":
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        warnings.append(f"JSON ilegible en {where}: se importa vacío")
        return None


def jsonb(value: Any):
    """None → NULL de SQL (no el ``null`` de JSON, que no es "sin valor")."""
    return null() if value is None else value


# ---------------------------------------------------------------------------
# Lectura de Vigil
# ---------------------------------------------------------------------------

VIGIL_TABLES = ("clients", "users", "client_settings", "watches", "watch_state", "sweep_runs", "run_errors",
                "snapshots", "changes", "change_items")


def open_vigil(path: str) -> sqlite3.Connection:
    """Sólo lectura de verdad (``mode=ro``): ni el WAL de Vigil se toca."""
    if not os.path.isfile(path):
        raise ImportAborted(f"No existe el fichero {path!r}.")
    uri = "file:" + os.path.abspath(path) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_vigil(path: str) -> dict[str, list[dict]]:
    conn = open_vigil(path)
    try:
        present = {r["name"] for r in conn.execute("select name from sqlite_master where type = 'table'")}
        missing = [t for t in VIGIL_TABLES if t not in present]
        if missing:
            raise ImportAborted(f"Esto no parece una base de datos de Vigil: faltan {', '.join(missing)}.")
        return {t: [dict(r) for r in conn.execute(f"select * from {t}")] for t in VIGIL_TABLES}  # noqa: S608
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


def vigil_fernet(secret_key: str) -> Fernet:
    """El mismo esquema que ``Vigil/backend/app/services/crypto.py``."""
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest()))


def decrypt_vigil_webhook(ciphertext: str, fernet: Fernet) -> str:
    """Descifra un webhook de Vigil. Lanza ``InvalidToken`` con la clave mala."""
    if not ciphertext.startswith("v1:"):
        raise ValueError("sin prefijo v1:")
    return fernet.decrypt(ciphertext[3:].encode()).decode()


def prompt_vigil_key() -> str:
    """``VIGIL_SECRET_KEY`` del entorno o pedida sin eco. Nunca se imprime."""
    key = os.environ.get("VIGIL_SECRET_KEY", "")
    if not key:
        key = getpass.getpass("VIGIL_SECRET_KEY de Vigil (no se muestra): ")
    if not key:
        raise ImportAborted("Hace falta VIGIL_SECRET_KEY para descifrar los webhooks de Slack.")
    return key


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------


@dataclass
class TableCount:
    selected: int = 0       # filas de Vigil de los clientes importados
    inserted: int = 0       # escritas ahora
    skipped_orphans: int = 0
    before: int = 0
    after: int = 0

    @property
    def existing(self) -> int:
        return self.selected - self.inserted - self.skipped_orphans


@dataclass
class ClientReport:
    slug: str
    vigil_name: str
    agency_id: int
    agency_name: str
    selected: Counter = field(default_factory=Counter)
    inserted: Counter = field(default_factory=Counter)
    settings: str = ""


@dataclass
class ImportReport:
    dry_run: bool
    tables: dict[str, TableCount] = field(default_factory=dict)
    clients: list[ClientReport] = field(default_factory=list)
    skipped_slugs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    acks_matched: int = 0
    acks_by_label: int = 0


# ---------------------------------------------------------------------------
# Clientes y usuarios
# ---------------------------------------------------------------------------


def parse_map(items: list[str] | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items or []:
        slug, sep, raw_id = item.partition("=")
        if not sep or not slug.strip() or not raw_id.strip().isdigit():
            raise ImportAborted(f"--map {item!r}: el formato es slug=client_id (p. ej. fit=12).")
        out[slug.strip()] = int(raw_id)
    return out


async def _slug_links(db) -> dict[str, tuple[int, str]]:
    """{vigil_slug: (client_id, nombre)} desde ``clients.vigil_slug`` con SQL.

    La fase 3b quitó la columna del ORM (sigue en la BD hasta la 3c); tras la 3c
    no existe y no hay enlaces por slug: sólo ``--map``.
    """
    exists = await db.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema()"
        " AND table_name = 'clients' AND column_name = 'vigil_slug')"
    ))
    if not exists:
        return {}
    rows = await db.execute(text("SELECT id, name, vigil_slug FROM clients WHERE vigil_slug IS NOT NULL"))
    return {r.vigil_slug: (r.id, r.name) for r in rows.all()}


async def resolve_clients(db, vigil_clients: list[dict], *, mapping: dict[str, int],
                          skip: set[str]) -> tuple[dict[str, tuple[int, str]], list[str]]:
    """{id de cliente en Vigil: (client_id en Agency, nombre)} y los slugs saltados."""
    by_slug = await _slug_links(db)
    wanted_ids = set(mapping.values())
    names = {r.id: r.name for r in (await db.execute(
        select(Client.id, Client.name).where(Client.id.in_(wanted_ids))
    )).all()} if wanted_ids else {}

    known_slugs = {c["slug"] for c in vigil_clients}
    unknown = sorted((set(mapping) | skip) - known_slugs)
    if unknown:
        raise ImportAborted(f"Slugs que no existen en Vigil: {', '.join(unknown)}.")
    both = sorted(set(mapping) & skip)
    if both:
        raise ImportAborted(f"Slugs con --map y --skip a la vez: {', '.join(both)}.")

    resolved: dict[str, tuple[int, str]] = {}
    skipped: list[str] = []
    unmapped: list[str] = []
    for client in sorted(vigil_clients, key=lambda c: c["slug"]):
        slug = client["slug"]
        if slug in skip:
            skipped.append(slug)
        elif slug in mapping:
            agency_id = mapping[slug]
            if agency_id not in names:
                raise ImportAborted(f"--map {slug}={agency_id}: no hay ningún cliente #{agency_id} en The Agency.")
            resolved[client["id"]] = (agency_id, names[agency_id])
        elif slug in by_slug:
            resolved[client["id"]] = by_slug[slug]
        else:
            unmapped.append(f"{slug} ({client['name']})")
    if unmapped:
        raise ImportAborted(
            "Clientes de Vigil sin cliente en The Agency (nada escrito): " + ", ".join(unmapped)
            + ". Usa --map slug=client_id / --skip slug."
        )
    targets = Counter(agency_id for agency_id, _ in resolved.values())
    dup = sorted(agency_id for agency_id, n in targets.items() if n > 1)
    if dup:
        raise ImportAborted(f"Varios clientes de Vigil irían al mismo cliente de The Agency: {dup}.")
    return resolved, skipped


# ---------------------------------------------------------------------------
# Filas de destino
# ---------------------------------------------------------------------------


def _default_or(value: Any, *default_values: Any) -> Any:
    """NULL si el valor de Vigil es (alguno de) su default."""
    return None if value is None or value in default_values else value


def settings_values(row: dict, warnings: list[str], where: str) -> dict[str, Any]:
    """``client_settings`` de Vigil → columnas de captura y calendario (NULL = default)."""
    sel = as_json(row.get("default_ignore_selectors"), warnings, where)
    rex = as_json(row.get("default_ignore_regexes"), warnings, where)
    weekdays = as_json(row.get("sweep_weekdays"), warnings, where)
    skip_dates = as_json(row.get("sweep_skip_dates"), warnings, where)
    summary = row.get("sweep_summary_to_slack")
    return {
        "digest_min_severity": _default_or(row.get("digest_min_severity"), defaults.DEFAULT_DIGEST_MIN_SEVERITY),
        "default_content_selector": cut(row.get("default_content_selector") or None, 500),
        "default_ignore_selectors": _default_or(sel, list(defaults.DEFAULT_IGNORE_SELECTORS), _OLD_DEFAULT_SELECTORS),
        "default_ignore_regexes": _default_or(rex, list(defaults.DEFAULT_IGNORE_REGEXES)),
        "max_concurrency": _default_or(row.get("max_concurrency"), defaults.DEFAULT_MAX_CONCURRENCY),
        "request_timeout_s": _default_or(row.get("request_timeout_s"), defaults.DEFAULT_REQUEST_TIMEOUT_S),
        "crawl_delay_ms": _default_or(row.get("crawl_delay_ms"), defaults.DEFAULT_CRAWL_DELAY_MS),
        "sweep_weekdays": _default_or(weekdays, list(defaults.DEFAULT_SWEEP_WEEKDAYS)),
        "sweep_skip_dates": _default_or(skip_dates, []),
        "sweep_summary_to_slack": (None if summary is None or as_bool(summary) == defaults.DEFAULT_SWEEP_SUMMARY_TO_SLACK
                                   else as_bool(summary)),
        "user_agent": cut((row.get("user_agent") or "").strip() or None, 300),
    }


def build_rows(data: dict[str, list[dict]], clients: dict[str, tuple[int, str]],
               users: dict[str, tuple[int, str]], report: ImportReport) -> tuple[dict[str, list[dict]], Counter]:
    """Filas listas para insertar, por tabla, sólo de los clientes importados.

    Una referencia a algo que no viene (SQLite no siempre aplica sus FK) se
    suelta si la columna admite NULL; si no, la fila se salta y se cuenta.
    """
    warnings = report.warnings
    cid = {vid: agency_id for vid, (agency_id, _) in clients.items()}
    vigil_users = {u["id"]: u for u in data["users"]}
    orphans: Counter = Counter()
    rows: dict[str, list[dict]] = {name: [] for name, _ in TABLES}

    def user_of(vigil_user_id) -> tuple[int | None, str | None]:
        vu = vigil_users.get(vigil_user_id)
        if vu is None:
            return None, None
        hit = users.get((vu["email"] or "").strip().lower())
        label = (vu.get("display_name") or vu["email"] or "")[:120] or None
        return (hit[0], hit[1][:120] or label) if hit else (None, label)

    watches = [w for w in data["watches"] if w["client_id"] in cid]
    watch_ids = {as_uuid("watches", w["id"]) for w in watches}
    too_long = [w["url"] for w in watches if len(w["url"]) > 500]
    if too_long:
        raise ImportAborted(f"URLs de más de 500 caracteres (no caben en web_watches.url): {too_long[:5]}")
    for w in watches:
        created_by, _ = user_of(w.get("created_by"))
        rows["web_watches"].append({
            "id": as_uuid("watches", w["id"]), "client_id": cid[w["client_id"]], "url": w["url"],
            "label": cut(w.get("label"), 200), "is_active": as_bool(w.get("is_active"), True),
            "watch_seo": as_bool(w.get("watch_seo"), True), "watch_content": as_bool(w.get("watch_content"), True),
            "watch_links": as_bool(w.get("watch_links")), "watch_html": as_bool(w.get("watch_html")),
            "content_selector": cut(w.get("content_selector") or None, 500),
            "ignore_selectors": jsonb(as_json(w.get("ignore_selectors"), warnings, f"watches {w['id']}")),
            "ignore_regexes": jsonb(as_json(w.get("ignore_regexes"), warnings, f"watches {w['id']}")),
            "muted": as_bool(w.get("muted")), "source": w.get("source") or "manual", "created_by": created_by,
            "created_at": as_dt(w["created_at"]), "updated_at": as_dt(w["updated_at"]),
        })

    runs = [r for r in data["sweep_runs"] if r["client_id"] in cid]
    run_ids = {as_uuid("sweep_runs", r["id"]) for r in runs}
    for r in runs:
        rows["web_sweep_runs"].append({
            "id": as_uuid("sweep_runs", r["id"]), "client_id": cid[r["client_id"]], "run_date": as_date(r["run_date"]),
            "trigger": r.get("trigger") or "scheduler", "status": r.get("status") or "done",
            "started_at": as_dt(r["started_at"]), "finished_at": as_dt(r.get("finished_at")),
            "watches_total": r.get("watches_total") or 0, "watches_done": r.get("watches_done") or 0,
            "watches_error": r.get("watches_error") or 0, "changes_found": r.get("changes_found") or 0,
            "notified_at": as_dt(r.get("notified_at")), "notify_status": cut(r.get("notify_status"), 32),
            "notify_error": cut(r.get("notify_error"), 500),
        })

    def ref(table: str, raw, known: set, *, label: str):
        """Referencia opcional: si no viene, NULL (y se cuenta)."""
        value = as_uuid(table, raw)
        if value is not None and value not in known:
            orphans[label] += 1
            return None
        return value

    snapshot_ids: set[uuid.UUID] = set()
    for s in data["snapshots"]:
        if s["client_id"] not in cid:
            continue
        if as_uuid("watches", s["watch_id"]) not in watch_ids:
            orphans["web_snapshots"] += 1
            continue
        sid = as_uuid("snapshots", s["id"])
        snapshot_ids.add(sid)
        rows["web_snapshots"].append({
            "id": sid, "watch_id": as_uuid("watches", s["watch_id"]), "client_id": cid[s["client_id"]],
            "run_id": ref("sweep_runs", s.get("run_id"), run_ids, label="web_snapshots.run_id"),
            "captured_at": as_dt(s["captured_at"]), "content_hash": cut(s.get("content_hash"), 64),
            "html_hash": cut(s.get("html_hash"), 64), "status_code": s.get("status_code"),
            "byte_size": s.get("byte_size"),
            # Los cuerpos ya vienen en gzip: se copian tal cual, sin recomprimir.
            "text_gz": bytes(s["text_gz"]) if s.get("text_gz") is not None else None,
            "html_gz": bytes(s["html_gz"]) if s.get("html_gz") is not None else None,
            "text_inline": s.get("text_inline"), "is_pinned": as_bool(s.get("is_pinned")),
        })

    for st in data["watch_state"]:
        if st["client_id"] not in cid:
            continue
        wid = as_uuid("watches", st["watch_id"])
        if wid not in watch_ids:
            orphans["web_watch_state"] += 1
            continue
        where = f"watch_state {st['watch_id']}"
        rows["web_watch_state"].append({
            "watch_id": wid, "client_id": cid[st["client_id"]],
            "last_checked_at": as_dt(st.get("last_checked_at")), "last_changed_at": as_dt(st.get("last_changed_at")),
            "last_status_code": st.get("last_status_code"), "last_final_url": st.get("last_final_url"),
            "last_error": cut(st.get("last_error"), 500), "consecutive_errors": st.get("consecutive_errors") or 0,
            "hash_seo": cut(st.get("hash_seo"), 64), "hash_content": cut(st.get("hash_content"), 64),
            "hash_links": cut(st.get("hash_links"), 64), "hash_html": cut(st.get("hash_html"), 64),
            "seo_json": jsonb(as_json(st.get("seo_json"), warnings, where)),
            "links_json": jsonb(as_json(st.get("links_json"), warnings, where)),
            "needs_js_render": as_bool(st.get("needs_js_render")), "scope_missed": as_bool(st.get("scope_missed")),
            # "Comprobando" es de un barrido de Vigil que aquí no existe.
            "checking_since": None,
            "last_snapshot_id": ref("snapshots", st.get("last_snapshot_id"), snapshot_ids,
                                    label="web_watch_state.last_snapshot_id"),
            "updated_at": as_dt(st.get("updated_at")) or datetime.now(UTC),
        })

    for e in data["run_errors"]:
        if e["client_id"] not in cid:
            continue
        if as_uuid("sweep_runs", e["run_id"]) not in run_ids:
            orphans["web_run_errors"] += 1
            continue
        rows["web_run_errors"].append({
            "id": as_uuid("run_errors", e["id"]), "run_id": as_uuid("sweep_runs", e["run_id"]),
            "client_id": cid[e["client_id"]],
            "watch_id": ref("watches", e.get("watch_id"), watch_ids, label="web_run_errors.watch_id"),
            "kind": cut(e.get("kind") or "error", 32), "message": cut(e.get("message"), 500),
            "status_code": e.get("status_code"), "created_at": as_dt(e["created_at"]),
        })

    change_ids: set[uuid.UUID] = set()
    for c in data["changes"]:
        if c["client_id"] not in cid:
            continue
        if as_uuid("watches", c["watch_id"]) not in watch_ids:
            orphans["web_changes"] += 1
            continue
        ack_by, ack_label = (None, None)
        if c.get("acknowledged_at") or c.get("acknowledged_by"):
            ack_by, ack_label = user_of(c.get("acknowledged_by"))
            if ack_by is not None:
                report.acks_matched += 1
            elif c.get("acknowledged_by"):
                report.acks_by_label += 1
        ch_id = as_uuid("changes", c["id"])
        change_ids.add(ch_id)
        rows["web_changes"].append({
            "id": ch_id, "client_id": cid[c["client_id"]], "watch_id": as_uuid("watches", c["watch_id"]),
            "run_id": ref("sweep_runs", c.get("run_id"), run_ids, label="web_changes.run_id"),
            "snapshot_id": ref("snapshots", c.get("snapshot_id"), snapshot_ids, label="web_changes.snapshot_id"),
            "prev_snapshot_id": ref("snapshots", c.get("prev_snapshot_id"), snapshot_ids,
                                    label="web_changes.prev_snapshot_id"),
            "max_severity": c["max_severity"], "detected_at": as_dt(c["detected_at"]),
            "acknowledged_by": ack_by, "acknowledged_by_label": ack_label,
            "acknowledged_at": as_dt(c.get("acknowledged_at")), "note": c.get("note"),
        })

    for i in data["change_items"]:
        if i["client_id"] not in cid:
            continue
        if as_uuid("changes", i["change_id"]) not in change_ids:
            orphans["web_change_items"] += 1
            continue
        detail = None
        if i.get("detail") not in (None, ""):
            try:
                detail = json.loads(i["detail"])
            except (TypeError, ValueError):
                detail = i["detail"]  # se conserva como cadena JSON: no se pierde nada
        rows["web_change_items"].append({
            "id": as_uuid("change_items", i["id"]), "change_id": as_uuid("changes", i["change_id"]),
            "client_id": cid[i["client_id"]], "kind": i["kind"], "field": cut(i["field"], 64),
            "severity": i["severity"], "rule_code": cut(i["rule_code"], 64),
            "before_val": i.get("before_val"), "after_val": i.get("after_val"), "detail": jsonb(detail),
            "created_at": as_dt(i["created_at"]),
        })
    return rows, orphans


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------


async def _counts(db) -> dict[str, int]:
    out = {}
    for name, model in TABLES:
        out[name] = (await db.execute(select(func.count()).select_from(model))).scalar_one()
    out["client_web_settings"] = (await db.execute(select(func.count()).select_from(ClientWebSettings))).scalar_one()
    return out


async def _check_conflicts(db, rows: dict[str, list[dict]]) -> None:
    """Choques que ``ON CONFLICT (id)`` no cubre: otra fila con la misma clave
    natural y OTRO id. Se dicen todos y no se escribe nada."""
    problems: list[str] = []
    watches = rows["web_watches"]
    if watches:
        mine = {(w["client_id"], w["url"]): w["id"] for w in watches}
        existing = (await db.execute(select(WebWatch.id, WebWatch.client_id, WebWatch.url).where(
            WebWatch.client_id.in_({w["client_id"] for w in watches}),
        ))).all()
        for row in existing:
            vid = mine.get((row.client_id, row.url))
            if vid is not None and vid != row.id:
                problems.append(f"la URL {row.url} del cliente #{row.client_id} ya existe en The Agency con otro id")
    scheduled = {(r["client_id"], r["run_date"]): r["id"] for r in rows["web_sweep_runs"] if r["trigger"] == "scheduler"}
    if scheduled:
        existing = (await db.execute(select(WebSweepRun.id, WebSweepRun.client_id, WebSweepRun.run_date).where(
            WebSweepRun.trigger == "scheduler",
            WebSweepRun.client_id.in_({k[0] for k in scheduled}),
        ))).all()
        for row in existing:
            vid = scheduled.get((row.client_id, row.run_date))
            if vid is not None and vid != row.id:
                problems.append(f"el cliente #{row.client_id} ya tiene un barrido programado el {row.run_date}")
    if problems:
        raise ImportAborted("Choques con datos que ya están en The Agency (nada escrito):\n  - "
                            + "\n  - ".join(problems[:20])
                            + ("\n  …" if len(problems) > 20 else ""))


async def _insert(db, model, rows: list[dict]) -> list[tuple[Any, int]]:
    """INSERT … ON CONFLICT (pk) DO NOTHING por tandas. Devuelve lo escrito."""
    if not rows:
        return []
    table = model.__table__
    pk = [c.name for c in table.primary_key.columns]
    per_batch = max(1, 30000 // len(rows[0]))  # asyncpg admite 32 767 parámetros
    written: list[tuple[Any, int]] = []
    for start in range(0, len(rows), per_batch):
        stmt = (pg_insert(table).values(rows[start:start + per_batch])
                .on_conflict_do_nothing(index_elements=pk)
                .returning(table.c[pk[0]], table.c.client_id))
        written.extend((r[0], r[1]) for r in (await db.execute(stmt)).all())
    return written


def _same_webhook(stored: str, plain: str | None) -> bool:
    """¿El webhook que ya hay en The Agency es el mismo de Vigil? (repetir la importación)"""
    try:
        return decrypt_vault_secret(stored) == plain
    except ValueError:
        return False


async def _import_settings(db, *, data, clients, fernet_factory: Callable[[], Fernet],
                           report: ImportReport, now: datetime) -> dict[int, str]:
    """``client_settings`` → ``client_web_settings``. Lo de The Agency manda."""
    by_vigil = {s["client_id"]: s for s in data["client_settings"]}
    slugs = {c["id"]: c["slug"] for c in data["clients"]}
    outcome: dict[int, str] = {}
    for vigil_id, (agency_id, _name) in clients.items():
        src = by_vigil.get(vigil_id)
        if src is None:
            outcome[agency_id] = "sin ajustes en Vigil"
            continue
        values = settings_values(src, report.warnings, f"client_settings {slugs[vigil_id]}")
        slack: dict[str, Any] = {}
        webhook_enc = src.get("slack_webhook_url")
        if webhook_enc:
            try:
                plain = decrypt_vigil_webhook(webhook_enc, fernet_factory())
            except ValueError:
                report.warnings.append(f"{slugs[vigil_id]}: el webhook de Vigil no tiene prefijo v1: (corrupto); "
                                       "no se importa")
                plain = None
            except InvalidToken:
                raise ImportAborted(f"VIGIL_SECRET_KEY no descifra el webhook de {slugs[vigil_id]}: "
                                    "¿es la clave de Vigil? (nada escrito)") from None
            if plain:
                if (settings.VAULT_KEY or settings.SECRET_KEY) == DEFAULT_SECRET_KEY:
                    raise ImportAborted("VAULT_KEY/SECRET_KEY de The Agency es el de desarrollo: el webhook quedaría "
                                        "cifrado con una clave que producción no tiene (nada escrito).")
                slack = {"slack_webhook_url": encrypt_vault_secret(plain),
                         "slack_channel_hint": cut(src.get("slack_channel_hint"), 100),
                         "slack_enabled": as_bool(src.get("slack_enabled"))}

        existing = await db.get(ClientWebSettings, agency_id, populate_existing=True)
        if existing is None:
            # Sólo lo que trae valor: lo demás queda NULL (= default del código).
            row = {k: v for k, v in {**values, **slack}.items() if v is not None}
            await db.execute(pg_insert(ClientWebSettings.__table__).values(
                client_id=agency_id, updated_at=now, **row,
            ).on_conflict_do_nothing(index_elements=["client_id"]))
            outcome[agency_id] = "creados" + (" con Slack" if slack else "")
            continue
        changed = [k for k, v in values.items() if v is not None and getattr(existing, k) is None]
        for k in changed:
            setattr(existing, k, values[k])
        slack_note = ""
        if slack:
            if existing.slack_webhook_url:
                if not _same_webhook(existing.slack_webhook_url, plain):
                    slack_note = ", Slack: se conserva el de The Agency"
            else:
                for k, v in slack.items():
                    setattr(existing, k, v)
                changed.append("slack")
        if changed:
            existing.updated_at = now
            await db.flush()
            outcome[agency_id] = "completados (" + ", ".join(changed) + ")" + slack_note
        else:
            outcome[agency_id] = "sin cambios" + slack_note
    return outcome


async def run_import(db, data: dict[str, list[dict]], *, mapping: dict[str, int] | None = None,
                     skip: set[str] | None = None, get_vigil_key: Callable[[], str] = prompt_vigil_key,
                     dry_run: bool = False, now: datetime | None = None) -> ImportReport:
    """Importa ``data`` (de ``load_vigil``) en ``db``. Confirma o deshace al final.

    Lanza ``ImportAborted`` (y deshace) si algo impide importarlo TODO.
    """
    now = now or datetime.now(UTC)
    report = ImportReport(dry_run=dry_run)
    try:
        clients, report.skipped_slugs = await resolve_clients(db, data["clients"], mapping=mapping or {},
                                                              skip=skip or set())
        users = {(u.email or "").strip().lower(): (u.id, u.full_name or u.email or "")
                 for u in (await db.execute(select(User.id, User.email, User.full_name))).all()}
        rows, orphans = build_rows(data, clients, users, report)
        await _check_conflicts(db, rows)

        before = await _counts(db)
        fernet: list[Fernet] = []

        def fernet_factory() -> Fernet:
            if not fernet:
                fernet.append(vigil_fernet(get_vigil_key()))
            return fernet[0]

        per_client_inserted: dict[str, Counter] = defaultdict(Counter)
        for name, model in TABLES:
            written = await _insert(db, model, rows[name])
            report.tables[name] = TableCount(selected=len(rows[name]) + orphans[name], inserted=len(written),
                                             skipped_orphans=orphans[name], before=before[name])
            for _id, client_id in written:
                per_client_inserted[name][client_id] += 1
        settings_outcome = await _import_settings(db, data=data, clients=clients, fernet_factory=fernet_factory,
                                                  report=report, now=now)
        after = await _counts(db)
        for name, count in report.tables.items():
            count.after = after[name]
        report.tables["client_web_settings"] = TableCount(
            selected=sum(1 for s in data["client_settings"] if s["client_id"] in clients),
            inserted=after["client_web_settings"] - before["client_web_settings"],
            before=before["client_web_settings"], after=after["client_web_settings"],
        )
        for label, n in sorted(orphans.items()):
            if "." in label:
                report.warnings.append(f"{n} referencia(s) {label} a filas que no existen en Vigil: quedan vacías")
            else:
                report.warnings.append(f"{n} fila(s) de {label} huérfanas en Vigil: no se importan")

        vigil_names = {c["id"]: (c["slug"], c["name"]) for c in data["clients"]}
        for vigil_id, (agency_id, agency_name) in sorted(clients.items(), key=lambda kv: vigil_names[kv[0]][0]):
            slug, vname = vigil_names[vigil_id]
            entry = ClientReport(slug=slug, vigil_name=vname, agency_id=agency_id, agency_name=agency_name,
                                 settings=settings_outcome.get(agency_id, ""))
            for name, _ in TABLES:
                entry.selected[name] = sum(1 for r in rows[name] if r["client_id"] == agency_id)
                entry.inserted[name] = per_client_inserted[name][agency_id]
            report.clients.append(entry)
    except BaseException:
        await db.rollback()
        raise
    if dry_run:
        await db.rollback()
    else:
        await db.commit()
    return report


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------

_SHORT = {"web_watches": "URLs", "web_sweep_runs": "barridos", "web_snapshots": "capturas",
          "web_watch_state": "estado", "web_run_errors": "errores", "web_changes": "cambios",
          "web_change_items": "detalle"}


def format_report(report: ImportReport) -> str:
    lines = []
    head = "SIMULACRO (--dry-run): nada se ha guardado" if report.dry_run else "Importación confirmada"
    lines.append(f"== {head} ==")
    lines.append("")
    lines.append(f"{'tabla':<22}{'en Vigil':>10}{'nuevas':>10}{'ya estaban':>12}{'huérfanas':>11}"
                 f"{'antes':>10}{'después':>10}")
    for name, c in report.tables.items():
        existing = c.existing if name != "client_web_settings" else "-"
        lines.append(f"{name:<22}{c.selected:>10}{c.inserted:>10}{existing!s:>12}{c.skipped_orphans:>11}"
                     f"{c.before:>10}{c.after:>10}")
    lines.append("")
    lines.append("Por cliente (nuevas/en Vigil):")
    for cl in report.clients:
        parts = ", ".join(f"{_SHORT[n]} {cl.inserted[n]}/{cl.selected[n]}" for n, _ in TABLES)
        lines.append(f"  {cl.slug} ({cl.vigil_name}) → #{cl.agency_id} {cl.agency_name}: {parts}")
        lines.append(f"      ajustes: {cl.settings}")
    if report.skipped_slugs:
        lines.append(f"Saltados (--skip): {', '.join(report.skipped_slugs)}")
    lines.append(f"Revisiones: {report.acks_matched} con usuario de The Agency, "
                 f"{report.acks_by_label} sólo con el nombre de Vigil.")
    for warning in report.warnings:
        lines.append(f"AVISO: {warning}")
    return "\n".join(lines)


def _db_label() -> str:
    """Dónde se va a escribir, sin contraseña."""
    parts = urlsplit(settings.DATABASE_URL)
    return f"{parts.hostname}:{parts.port or 5432}/{parts.path.lstrip('/')}"


async def main(args: argparse.Namespace) -> int:
    from backend.db.database import async_session, engine

    try:
        data = load_vigil(args.sqlite)
        print(f"Vigil: {args.sqlite} (sólo lectura). Destino: {_db_label()}.", flush=True)
        async with async_session() as db:
            report = await run_import(db, data, mapping=parse_map(args.map), skip=set(args.skip or []),
                                      dry_run=args.dry_run)
        print(format_report(report))
        return 0
    except ImportAborted as exc:
        print(f"ABORTADO: {exc}", file=sys.stderr)
        return 2
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sqlite", required=True, help="Ruta al vigil.db (se abre en sólo lectura)")
    parser.add_argument("--dry-run", action="store_true", help="Hace todo y deshace al final")
    parser.add_argument("--map", action="append", metavar="SLUG=CLIENT_ID",
                        help="Cliente de The Agency para un slug de Vigil (repetible)")
    parser.add_argument("--skip", action="append", metavar="SLUG", help="Slug de Vigil que no se importa (repetible)")
    sys.exit(asyncio.run(main(parser.parse_args())))
