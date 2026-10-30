"""Clasificación de cambios: qué es crítico, qué es aviso y qué es informativo.

Portado de Vigil casi tal cual: las reglas son las mismas para que los cambios
importados de Vigil y los nuevos se lean igual.

Las reglas viven en CÓDIGO, no en una tabla de la DB. Una tabla de reglas que
nadie edita sería Datos Decorativos; en código son testables y revisables en un
diff.

El criterio de severidad es "¿qué haría un SEO al leerlo?":
  critical  algo que puede costar tráfico HOY y hay que mirar ya
  warning   algo que hay que saber y probablemente preguntar al cliente
  info      contexto: se ha tocado la página, sin daño aparente
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

CRITICAL = "critical"
WARNING = "warning"
INFO = "info"

_ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2}

# Recorte de valores para listados y para Slack. El valor completo vive en el
# snapshot; esto es lo que se enseña.
_MAX_VAL = 2000


@dataclass
class ChangeItem:
    kind: str          # seo | content | links | html | availability
    field: str
    severity: str
    rule_code: str
    before_val: str | None = None
    after_val: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def _trunc(value: Any) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return text[:_MAX_VAL]


def _norm_url(url: str | None) -> str | None:
    """Normaliza para comparar canonicals: sin barra final, sin www, sin esquema.

    Que un canonical pase de http a https, o gane una barra, no es un cambio
    de destino y no debe despertar a nadie.
    """
    if not url:
        return None
    u = url.strip().lower()
    for prefix in ("https://", "http://"):
        u = u.removeprefix(prefix)
    u = u.removeprefix("www.")
    return u.rstrip("/") or "/"


def max_severity(items: list[ChangeItem]) -> str:
    return min((i.severity for i in items), key=lambda s: _ORDER[s], default=INFO)


# ---------------------------------------------------------------------------
# Disponibilidad
# ---------------------------------------------------------------------------


def _classify_availability(prev: dict, curr: dict) -> list[ChangeItem]:
    items: list[ChangeItem] = []
    before, after = prev.get("status_code"), curr.get("status_code")

    if before == after:
        return items

    def ok(code) -> bool:
        return code is not None and 200 <= code < 300

    if ok(before) and after is not None and after >= 400:
        items.append(ChangeItem(
            kind="availability", field="status_code", severity=CRITICAL,
            rule_code="STATUS_ERROR", before_val=_trunc(before), after_val=_trunc(after),
        ))
    elif ok(before) and after is not None and 300 <= after < 400:
        items.append(ChangeItem(
            kind="availability", field="status_code", severity=CRITICAL,
            rule_code="STATUS_REDIRECT_NEW", before_val=_trunc(before), after_val=_trunc(after),
        ))
    elif not ok(before) and ok(after):
        # Buena noticia, pero se quiere saber: cierra el incidente anterior.
        items.append(ChangeItem(
            kind="availability", field="status_code", severity=WARNING,
            rule_code="STATUS_RECOVERED", before_val=_trunc(before), after_val=_trunc(after),
        ))
    else:
        items.append(ChangeItem(
            kind="availability", field="status_code", severity=WARNING,
            rule_code="STATUS_CHANGED", before_val=_trunc(before), after_val=_trunc(after),
        ))

    return items


# ---------------------------------------------------------------------------
# SEO
# ---------------------------------------------------------------------------


def _classify_robots(prev: dict, curr: dict) -> list[ChangeItem]:
    items: list[ChangeItem] = []
    before = set(prev.get("robots_directives") or [])
    after = set(curr.get("robots_directives") or [])

    for directive, code in (("noindex", "NOINDEX_ADDED"), ("nofollow", "NOFOLLOW_ADDED")):
        if directive in after and directive not in before:
            items.append(ChangeItem(
                kind="seo", field="robots", severity=CRITICAL, rule_code=code,
                before_val=_trunc(", ".join(sorted(before))),
                after_val=_trunc(", ".join(sorted(after))),
            ))

    for directive, code in (("noindex", "NOINDEX_REMOVED"), ("nofollow", "NOFOLLOW_REMOVED")):
        if directive in before and directive not in after:
            items.append(ChangeItem(
                kind="seo", field="robots", severity=WARNING, rule_code=code,
                before_val=_trunc(", ".join(sorted(before))),
                after_val=_trunc(", ".join(sorted(after))),
            ))

    return items


def _classify_canonical(prev: dict, curr: dict) -> list[ChangeItem]:
    before, after = prev.get("canonical"), curr.get("canonical")
    nb, na = _norm_url(before), _norm_url(after)

    if nb == na:
        return []

    if before and not after:
        return [ChangeItem(
            kind="seo", field="canonical", severity=CRITICAL,
            rule_code="CANONICAL_REMOVED", before_val=_trunc(before), after_val=None,
        )]

    if not before and after:
        return [ChangeItem(
            kind="seo", field="canonical", severity=WARNING,
            rule_code="CANONICAL_ADDED", before_val=None, after_val=_trunc(after),
        )]

    # Perder la autorreferencia es peor que un cambio cualquiera: la página
    # deja de pedir ser indexada a sí misma.
    self_before = nb == _norm_url(prev.get("final_url"))
    self_after = na == _norm_url(curr.get("final_url"))
    code = "CANONICAL_SELF_LOST" if (self_before and not self_after) else "CANONICAL_CHANGED"

    return [ChangeItem(
        kind="seo", field="canonical", severity=CRITICAL, rule_code=code,
        before_val=_trunc(before), after_val=_trunc(after),
    )]


def _classify_seo_fields(prev: dict, curr: dict) -> list[ChangeItem]:
    items: list[ChangeItem] = []

    # --- title ---
    tb, ta = prev.get("title") or "", curr.get("title") or ""
    if tb != ta:
        # Quedarse sin title es peor que cambiarlo.
        sev = CRITICAL if (tb and not ta) else WARNING
        code = "TITLE_REMOVED" if (tb and not ta) else "TITLE_CHANGED"
        items.append(ChangeItem(
            kind="seo", field="title", severity=sev, rule_code=code,
            before_val=_trunc(tb), after_val=_trunc(ta),
        ))

    # --- H1 ---
    hb = prev.get("h1") or []
    ha = curr.get("h1") or []
    if hb != ha:
        if hb and not ha:
            items.append(ChangeItem(
                kind="seo", field="h1", severity=CRITICAL, rule_code="H1_REMOVED",
                before_val=_trunc(" | ".join(hb)), after_val=None,
            ))
        else:
            items.append(ChangeItem(
                kind="seo", field="h1", severity=WARNING, rule_code="H1_CHANGED",
                before_val=_trunc(" | ".join(hb)), after_val=_trunc(" | ".join(ha)),
                detail={"before": hb, "after": ha},
            ))

    # --- meta description ---
    mb, ma = prev.get("meta_description") or "", curr.get("meta_description") or ""
    if mb != ma:
        items.append(ChangeItem(
            kind="seo", field="meta_description", severity=WARNING,
            rule_code="META_DESCRIPTION_REMOVED" if (mb and not ma) else "META_DESCRIPTION_CHANGED",
            before_val=_trunc(mb), after_val=_trunc(ma),
        ))

    # --- H2 ---
    h2b, h2a = prev.get("h2") or [], curr.get("h2") or []
    if h2b != h2a:
        items.append(ChangeItem(
            kind="seo", field="h2", severity=INFO, rule_code="H2_CHANGED",
            before_val=_trunc(f"{len(h2b)} H2"), after_val=_trunc(f"{len(h2a)} H2"),
            detail={"added": sorted(set(h2a) - set(h2b)), "removed": sorted(set(h2b) - set(h2a))},
        ))

    # --- schema.org ---
    sb, sa = set(prev.get("schema_types") or []), set(curr.get("schema_types") or [])
    if removed := sorted(sb - sa):
        items.append(ChangeItem(
            kind="seo", field="schema_types", severity=WARNING,
            rule_code="SCHEMA_TYPE_REMOVED",
            before_val=_trunc(", ".join(sorted(sb))), after_val=_trunc(", ".join(sorted(sa))),
            detail={"removed": removed},
        ))
    if added := sorted(sa - sb):
        items.append(ChangeItem(
            kind="seo", field="schema_types", severity=INFO,
            rule_code="SCHEMA_TYPE_ADDED",
            before_val=_trunc(", ".join(sorted(sb))), after_val=_trunc(", ".join(sorted(sa))),
            detail={"added": added},
        ))

    # --- hreflang ---
    hlb = {(h["lang"], h["href"]) for h in (prev.get("hreflang") or [])}
    hla = {(h["lang"], h["href"]) for h in (curr.get("hreflang") or [])}
    if lost := sorted(hlb - hla):
        items.append(ChangeItem(
            kind="seo", field="hreflang", severity=CRITICAL, rule_code="HREFLANG_REMOVED",
            before_val=_trunc(f"{len(hlb)} hreflang"), after_val=_trunc(f"{len(hla)} hreflang"),
            detail={"removed": [{"lang": lg, "href": hr} for lg, hr in lost]},
        ))
    if gained := sorted(hla - hlb):
        items.append(ChangeItem(
            kind="seo", field="hreflang", severity=INFO, rule_code="HREFLANG_ADDED",
            before_val=_trunc(f"{len(hlb)} hreflang"), after_val=_trunc(f"{len(hla)} hreflang"),
            detail={"added": [{"lang": lg, "href": hr} for lg, hr in gained]},
        ))

    return items


# ---------------------------------------------------------------------------
# Contenido y enlaces
# ---------------------------------------------------------------------------

# Umbral para separar reescritura de retoque.
_MAJOR_RATIO = 0.20
_MAJOR_WORDS = 0.15


def _classify_content(prev_text: str, curr_text: str,
                      prev_words: int, curr_words: int) -> list[ChangeItem]:
    if prev_text == curr_text:
        return []

    ratio = difflib.SequenceMatcher(None, prev_text, curr_text).quick_ratio()
    changed = 1 - ratio
    word_delta = abs(curr_words - prev_words) / max(prev_words, 1)

    major = changed > _MAJOR_RATIO or word_delta > _MAJOR_WORDS

    return [ChangeItem(
        kind="content", field="text",
        severity=WARNING if major else INFO,
        rule_code="CONTENT_CHANGED_MAJOR" if major else "CONTENT_CHANGED_MINOR",
        before_val=_trunc(f"{prev_words} palabras"),
        after_val=_trunc(f"{curr_words} palabras"),
        detail={
            "diff": _text_diff(prev_text, curr_text),
            "changed_ratio": round(changed, 3),
            "word_delta": curr_words - prev_words,
        },
    )]


def _text_diff(before: str, after: str, max_hunks: int = 200) -> dict:
    """Diff por frases, no por caracteres.

    Un diff de caracteres sobre 5.000 palabras es ilegible y pesa una barbaridad
    en la DB y en Slack.
    """
    a = [s.strip() for s in before.replace(". ", ".\n").split("\n") if s.strip()]
    b = [s.strip() for s in after.replace(". ", ".\n").split("\n") if s.strip()]

    hunks = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if op == "equal":
            continue
        hunks.append({"op": op, "before": a[i1:i2][:20], "after": b[j1:j2][:20]})
        if len(hunks) >= max_hunks:
            return {"hunks": hunks, "truncated": True}
    return {"hunks": hunks, "truncated": False}


# Por debajo de esto, perder enlaces internos es ruido de un widget.
_LINKS_LOST_THRESHOLD = 5


def _classify_links(prev: dict, curr: dict) -> list[ChangeItem]:
    items: list[ChangeItem] = []

    for scope, sev_lost in (("internal", WARNING), ("external", INFO)):
        before = set(prev.get(scope) or [])
        after = set(curr.get(scope) or [])
        lost, gained = sorted(before - after), sorted(after - before)

        if lost:
            severe = scope == "internal" and len(lost) >= _LINKS_LOST_THRESHOLD
            items.append(ChangeItem(
                kind="links", field=f"{scope}_links",
                severity=WARNING if severe else sev_lost,
                rule_code=f"{scope.upper()}_LINKS_REMOVED",
                before_val=_trunc(f"{len(before)} enlaces"),
                after_val=_trunc(f"{len(after)} enlaces"),
                detail={"removed": lost[:50], "removed_count": len(lost)},
            ))
        if gained:
            items.append(ChangeItem(
                kind="links", field=f"{scope}_links", severity=INFO,
                rule_code=f"{scope.upper()}_LINKS_ADDED",
                before_val=_trunc(f"{len(before)} enlaces"),
                after_val=_trunc(f"{len(after)} enlaces"),
                detail={"added": gained[:50], "added_count": len(gained)},
            ))

    return items


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------


def classify(*, prev_seo: dict | None, curr_seo: dict,
             prev_text: str | None = None, curr_text: str | None = None,
             prev_links: dict | None = None, curr_links: dict | None = None,
             html_changed: bool = False,
             html_delta: dict[str, int] | None = None,
             watch_flags: dict[str, bool] | None = None) -> list[ChangeItem]:
    """Compara estado anterior con el actual y devuelve los cambios.

    `prev_seo is None` = primera captura del watch: no hay con qué comparar,
    así que NO se emite ningún cambio. Si no, dar de alta 100 URLs generaría
    100 avisos la primera noche.
    """
    if prev_seo is None:
        return []

    flags = watch_flags or {}
    items: list[ChangeItem] = []

    items += _classify_availability(prev_seo, curr_seo)

    # Si la página ha dejado de responder bien, comparar su SEO no aporta: el
    # HTML es el de una página de error y generaría una cascada de falsos
    # "title cambiado", "H1 desaparecido", "canonical borrado"…
    status = curr_seo.get("status_code")
    if status is not None and status >= 400:
        return items

    if flags.get("watch_seo", True):
        items += _classify_robots(prev_seo, curr_seo)
        items += _classify_canonical(prev_seo, curr_seo)
        items += _classify_seo_fields(prev_seo, curr_seo)

    if flags.get("watch_content", True) and prev_text is not None and curr_text is not None:
        items += _classify_content(
            prev_text, curr_text,
            prev_seo.get("word_count", 0), curr_seo.get("word_count", 0),
        )

    if flags.get("watch_links", False) and prev_links is not None and curr_links is not None:
        items += _classify_links(prev_links, curr_links)

    # El HTML solo se reporta si NADA más se movió: si cambió el title, decir
    # además "cambió el HTML" es ruido redundante.
    #
    # `before_val`/`after_val` siguen a None: no hay un "antes" y un "después"
    # que quepan en una línea, y el trozo concreto lo sirve /html-diff. Lo que sí
    # va aquí es el TAMAÑO, en `detail`. Sin él, cinco URLs que cambian la misma
    # noche por un plugin actualizado enseñan cinco filas idénticas que dicen
    # "cambió el HTML" y nada más, y eso es indistinguible de un falso positivo
    # (27-jul-2026). `html_delta` puede llegar a None —primera captura con HTML
    # guardado, página fuera del tope de líneas—: entonces no se inventa un cero,
    # se deja sin detail y la interfaz dice que no se pudo medir.
    if flags.get("watch_html", False) and html_changed and not items:
        items.append(ChangeItem(
            kind="html", field="raw_html", severity=INFO, rule_code="HTML_CHANGED",
            before_val=None, after_val=None,
            detail=dict(html_delta) if html_delta else {},
        ))

    return items
