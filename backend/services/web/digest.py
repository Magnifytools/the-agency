"""Construcción del digest diario para Slack (Block Kit). Portado de Vigil.

Va al canal de Slack de CADA cliente (`client_web_settings`, el mismo webhook
cifrado que los avisos de caída). Cada línea enlaza a su cambio en The Agency
(`/web/cambios/{id}`), y los hosts que no se han podido mirar (circuit breaker)
se dicen con su motivo: caída según el monitor de disponibilidad o probable
bloqueo.

Reglas de producto que viven aquí:

  * Sin cambios ⇒ NO se manda nada. `build_digest` devuelve None y el barrido
    anota `skipped_no_changes`. Así el silencio siempre es distinguible de una
    avería: se mira `sweep_runs` y consta que el barrido corrió y calló.
  * Los críticos van arriba y con su antes/después completo. El resto se
    resume. Un digest que hay que leer entero no se lee.
  * Un mensaje de Slack tiene límites duros (50 bloques, 3000 caracteres por
    sección). Pasarse devuelve 400 y el aviso se pierde entero, así que se
    recorta a conciencia y se enlaza al detalle.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.services.web.classifier import CRITICAL, INFO, WARNING

_SEV_LABEL = {
    CRITICAL: ("🔴", "Críticos"),
    WARNING: ("🟡", "Cambios"),
    INFO: ("⚪", "Menores"),
}

_KIND_LABEL = {
    "availability": "Disponibilidad",
    "seo": "SEO",
    "content": "Contenido",
    "links": "Enlaces",
    "html": "Maquetación",
}

# Textos legibles por regla. Sin esto, el mensaje sería un volcado de constantes
# en mayúsculas que solo entiende quien escribió el clasificador.
_RULE_LABEL = {
    "NOINDEX_ADDED": "noindex añadido",
    "NOINDEX_REMOVED": "noindex quitado",
    "NOFOLLOW_ADDED": "nofollow añadido",
    "NOFOLLOW_REMOVED": "nofollow quitado",
    "CANONICAL_REMOVED": "canonical eliminado",
    "CANONICAL_ADDED": "canonical añadido",
    "CANONICAL_CHANGED": "canonical cambiado",
    "CANONICAL_SELF_LOST": "canonical ya no es autorreferente",
    "STATUS_ERROR": "la página devuelve error",
    "STATUS_REDIRECT_NEW": "la página ahora redirige",
    "STATUS_RECOVERED": "la página vuelve a responder",
    "STATUS_CHANGED": "cambió el código de estado",
    "TITLE_CHANGED": "title cambiado",
    "TITLE_REMOVED": "title vacío",
    "H1_CHANGED": "H1 cambiado",
    "H1_REMOVED": "H1 desaparecido",
    "META_DESCRIPTION_CHANGED": "meta description cambiada",
    "META_DESCRIPTION_REMOVED": "meta description borrada",
    "H2_CHANGED": "H2 modificados",
    "SCHEMA_TYPE_REMOVED": "schema.org eliminado",
    "SCHEMA_TYPE_ADDED": "schema.org añadido",
    "HREFLANG_REMOVED": "hreflang eliminado",
    "HREFLANG_ADDED": "hreflang añadido",
    "CONTENT_CHANGED_MAJOR": "contenido reescrito",
    "CONTENT_CHANGED_MINOR": "contenido retocado",
    "INTERNAL_LINKS_REMOVED": "enlaces internos eliminados",
    "INTERNAL_LINKS_ADDED": "enlaces internos añadidos",
    "EXTERNAL_LINKS_REMOVED": "enlaces externos eliminados",
    "EXTERNAL_LINKS_ADDED": "enlaces externos añadidos",
    "HTML_CHANGED": "cambió el HTML",
}

AGENCY_URL = "https://agency.magnifytools.com"

_MAX_ITEMS_PER_SEVERITY = 10
_MAX_VAL_IN_SLACK = 140


@dataclass(frozen=True)
class DigestChange:
    """Un watch con cambios, tal y como lo necesita el mensaje."""

    url: str
    label: str | None
    max_severity: str
    items: list[dict[str, Any]]
    change_id: str | None = None


def change_url(change_id: str) -> str:
    return f"{AGENCY_URL}/web/cambios/{change_id}"


def changes_path(client_id: int) -> str:
    return f"/web/cambios?cliente={client_id}"


def changes_url(client_id: int) -> str:
    return f"{AGENCY_URL}{changes_path(client_id)}"


def _notes_block(notes: list[str] | None) -> list[dict]:
    """Lo que NO se ha podido mirar, con su porqué. Va siempre que exista."""
    if not notes:
        return []
    text = "\n".join(f"⚠️ {_esc(n)}" for n in notes)
    return [{"type": "context", "elements": [{"type": "mrkdwn", "text": text[:2900]}]}]


def _plural(n: int, singular: str, plural: str) -> str:
    """`1 URL revisada` en vez de `1 URLs revisadas`."""
    return f"{n} {singular if n == 1 else plural}"


def _esc(text: str | None) -> str:
    """Escapa mrkdwn de Slack. `&`, `<` y `>` rompen el render si van crudos."""
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _short(value: str | None) -> str:
    if not value:
        return "—"
    value = value.strip()
    return value if len(value) <= _MAX_VAL_IN_SLACK else value[: _MAX_VAL_IN_SLACK - 1] + "…"


def _path(url: str) -> str:
    """Solo la ruta: en un canal, el dominio se repite en cada línea y estorba."""
    from urllib.parse import urlparse

    p = urlparse(url)
    return (p.path or "/") + (f"?{p.query}" if p.query else "")


def _describe(item: dict) -> str:
    label = _RULE_LABEL.get(item["rule_code"], item["rule_code"])
    before, after = item.get("before_val"), item.get("after_val")

    # Para title/H1/canonical el antes→después ES la información. Para el resto
    # (contadores de enlaces, palabras) basta la etiqueta.
    if item["field"] in ("title", "h1", "canonical", "meta_description", "status_code"):
        if before and after:
            return f"*{label}*\n        {_esc(_short(before))}\n        → {_esc(_short(after))}"
        if after:
            return f"*{label}*: {_esc(_short(after))}"
        if before:
            return f"*{label}* (era: {_esc(_short(before))})"

    # "cambió el HTML" a secas no dice si han tocado una clase o han cambiado la
    # plantilla, y es lo único que se lee cuando ninguna otra dimensión se movió
    # (el clasificador solo emite esta regla en ese caso). El tamaño va aquí por
    # la misma razón que en la pantalla: sin él, cinco URLs tocadas por el mismo
    # plugin mandan cinco líneas idénticas que no dejan decidir nada.
    detail = item.get("detail") or {}
    if item["rule_code"] == "HTML_CHANGED" and isinstance(detail.get("added"), int):
        return (f"*{label}* (+{detail['added']} / −{detail['removed']} líneas"
                f" de {detail.get('after_lines', '?')})")

    return f"*{label}*"


def build_digest(client_name: str, date_label: str, changes: list[DigestChange],
                 *, urls_checked: int, errors: int = 0,
                 detail_url: str | None = None,
                 notes: list[str] | None = None) -> dict | None:
    """Devuelve {blocks, text} o **None si no hay cambios**."""
    if not changes:
        return None

    by_sev: dict[str, list[tuple[DigestChange, dict]]] = {CRITICAL: [], WARNING: [], INFO: []}
    for change in changes:
        for item in change.items:
            by_sev[item["severity"]].append((change, item))

    n_items = sum(len(v) for v in by_sev.values())
    n_critical = len(by_sev[CRITICAL])

    header = f"Cambios en la web · {client_name} · {date_label}"
    resumen = (
        f"{_plural(urls_checked, 'URL revisada', 'URLs revisadas')}"
        f" · {len(changes)} con cambios"
        f" · {_plural(n_items, 'cambio', 'cambios')}"
    )
    if n_critical:
        resumen += f" · *{_plural(n_critical, 'crítico', 'críticos')}*"
    if errors:
        resumen += f" · {errors} con error"

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header, "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": resumen}]},
        *_notes_block(notes),
    ]

    for severity in (CRITICAL, WARNING, INFO):
        entries = by_sev[severity]
        if not entries:
            continue

        emoji, titulo = _SEV_LABEL[severity]
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"{emoji} *{titulo}* ({len(entries)})"},
        })

        for change, item in entries[:_MAX_ITEMS_PER_SEVERITY]:
            kind = _KIND_LABEL.get(item["kind"], item["kind"])
            ruta = f"`{_esc(_path(change.url))}`"
            if change.change_id:
                ruta = f"<{change_url(change.change_id)}|{_esc(_path(change.url))}>"
            texto = (
                f"{ruta} · _{kind}_\n"
                f"        {_describe(item)}"
            )
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": texto[:2900]}})

        if len(entries) > _MAX_ITEMS_PER_SEVERITY:
            resto = len(entries) - _MAX_ITEMS_PER_SEVERITY
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_… y {resto} más_"}],
            })

    if detail_url:
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "Ver el detalle en The Agency"},
                "url": detail_url,
            }],
        })

    # Slack corta a 50 bloques: pasarse devuelve 400 y se pierde TODO el aviso.
    # Se recorta dejando el botón de detalle, que es la salida a la info completa.
    if len(blocks) > 48:
        tail = blocks[-1:] if detail_url else []
        blocks = blocks[: 48 - len(tail)] + [
            {"type": "context",
             "elements": [{"type": "mrkdwn", "text": "_Mensaje recortado. Ver el detalle en The Agency._"}]},
        ] + tail

    # `text` es lo que Slack enseña en la notificación del móvil. Sin él, llega
    # un aviso en blanco.
    fallback = (
        f"{header} — {_plural(n_items, 'cambio', 'cambios')}"
        f" en {_plural(len(changes), 'URL', 'URLs')}"
    )
    if n_critical:
        fallback += f" ({_plural(n_critical, 'crítico', 'críticos')})"

    return {"blocks": blocks, "text": fallback}


# ---------------------------------------------------------------------------
# Resumen de barrido completo
# ---------------------------------------------------------------------------


def build_summary(client_name: str, date_label: str, *, urls_checked: int,
                  urls_changed: int, n_critical: int, errors: int,
                  trigger: str, detail_url: str | None = None,
                  notes: list[str] | None = None) -> dict:
    """Resumen de un barrido completo. Se manda AUNQUE no haya cambios.

    Es distinto del digest de cambios y complementario: el digest solo aparece
    cuando algo se movió, así que su silencio es ambiguo —¿no cambió nada, o no
    corrió el barrido?—. Este mensaje resuelve esa ambigüedad diciendo "he
    mirado 6 páginas y ninguna cambió".

    Por eso solo se manda en barridos COMPLETOS (el nocturno o un "comprobar
    todas" a mano), no al comprobar una URL suelta: eso último es una acción
    puntual de alguien que ya está mirando la pantalla.
    """
    if urls_changed:
        emoji = "🔴" if n_critical else "🟡"
        titular = f"{urls_changed} de {urls_checked} páginas con cambios"
    else:
        emoji = "✅"
        titular = f"{_plural(urls_checked, 'página revisada', 'páginas revisadas')}, ninguna con cambios"

    origen = "Barrido automático" if trigger == "scheduler" else "Barrido manual"
    texto = f"{emoji} *{origen} terminado* — {titular}"

    detalles = []
    if n_critical:
        detalles.append(f"*{_plural(n_critical, 'cambio crítico', 'cambios críticos')}*")
    if errors:
        detalles.append(f"{_plural(errors, 'página con error', 'páginas con error')}")
    if detalles:
        texto += "\n" + " · ".join(detalles)

    blocks: list[dict] = [
        {"type": "section",
         "text": {"type": "mrkdwn", "text": f"*Webs · {client_name} · {date_label}*\n{texto}"}},
        *_notes_block(notes),
    ]
    if detail_url:
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "Ver en The Agency"},
                "url": detail_url,
            }],
        })

    return {
        "blocks": blocks,
        "text": f"Webs · {client_name} — {origen.lower()}: {titular}",
    }
