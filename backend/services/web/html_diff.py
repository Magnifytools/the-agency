"""Diff legible del HTML normalizado de dos capturas (portado de Vigil).

Se calcula en el SERVIDOR, al revés que el diff de texto —que viaja entero al
navegador y se compara allí—, y la razón es el tamaño: el HTML normalizado de
una landing de Elementor ronda los cientos de KB por lado. Mandar los dos
cuerpos completos para acabar enseñando seis líneas sería pagar el peaje entero
por el resumen. Aquí solo salen los trozos que cambian, con su contexto.

Lo que se compara es `Capture.html`, es decir el MISMO texto sobre el que se
calcula `hash_html`. Si se comparara el HTML crudo, el diff enseñaría
diferencias que no dispararon el aviso (comentarios, ids volátiles, espacios) y
la pantalla contradiría al detector.
"""
from __future__ import annotations

import difflib

# Por encima de esto no se intenta el diff: `SequenceMatcher` es cuadrático en
# el peor caso y una request que tarda un minuto es peor que un "no cabe".
_MAX_LINEAS = 30_000
# Cortes que se enseñan. Un cambio de plantilla puede tocar cientos de sitios;
# a partir de cierto punto ya no se lee, se mira. Lo que sobra se DICE.
_MAX_HUNKS = 40
_MAX_LINEAS_POR_HUNK = 80
# Una sola línea puede ser un <script> inline de 40 KB.
_MAX_ANCHO = 400


def lineas(html: str) -> list[str]:
    """Parte el HTML en una etiqueta por línea.

    `normalize_html` ya ha colapsado el blanco entre etiquetas a `><`, así que
    el HTML llega aquí como una única línea kilométrica. Sin este corte,
    cualquier diff por líneas diría "toda la página ha cambiado".
    """
    if not html:
        return []
    return [ln for ln in html.replace("><", ">\n<").split("\n") if ln.strip()]


def _corta(s: str) -> str:
    return s if len(s) <= _MAX_ANCHO else s[:_MAX_ANCHO] + " …"


def delta_stats(antes: str, despues: str) -> dict | None:
    """Cuántas líneas se fueron y cuántas llegaron. Sin construir los cortes.

    Existe aparte de `diff_html` porque el barrido solo necesita el TAMAÑO del
    cambio, y montar los hunks con su contexto para tirarlos después sería pagar
    la parte cara del diff a cambio de dos enteros. Esos dos enteros son lo que
    convierte "cambió el HTML" —una etiqueta que no dice nada— en "+12 / −9
    líneas de 3.837", que es lo que deja decidir si merece la pena entrar.

    Devuelve None cuando no se puede medir (falta un lado, o la página se sale
    del tope). None significa "no lo sé", y la interfaz lo dice; un 0 inventado
    se leería como "no cambió nada", que es justo lo contrario de lo que pasó.
    """
    if not antes or not despues:
        return None

    a, b = lineas(antes), lineas(despues)
    if len(a) > _MAX_LINEAS or len(b) > _MAX_LINEAS:
        return None

    anadidas = quitadas = 0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        quitadas += i2 - i1
        anadidas += j2 - j1

    return {
        "added": anadidas,
        "removed": quitadas,
        "before_lines": len(a),
        "after_lines": len(b),
    }


def diff_html(antes: str, despues: str, *, contexto: int = 3) -> dict:
    """Cortes con cambios entre dos HTML normalizados.

    Devuelve siempre las cuentas reales (`added`/`removed`), aunque la lista de
    cortes venga recortada: el número dice la verdad y la lista dice lo que cabe.
    """
    a, b = lineas(antes), lineas(despues)
    stats = {
        "before_lines": len(a),
        "after_lines": len(b),
        "added": 0,
        "removed": 0,
    }

    if len(a) > _MAX_LINEAS or len(b) > _MAX_LINEAS:
        return {"hunks": [], "stats": stats, "too_big": True,
                "hunks_total": 0, "truncated": False}

    # autojunk=False a propósito: el heurístico descarta las líneas que se
    # repiten mucho y en HTML eso es justo `</div>`. Con él puesto, el diff de
    # una página real sale desplazado y señala cambios donde no los hay.
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)

    cortes: list[dict] = []
    for grupo in sm.get_grouped_opcodes(contexto):
        filas: list[dict] = []
        for tag, i1, i2, j1, j2 in grupo:
            if tag == "equal":
                filas += [{"t": " ", "s": _corta(s)} for s in a[i1:i2]]
                continue
            for s in a[i1:i2]:
                filas.append({"t": "-", "s": _corta(s)})
                stats["removed"] += 1
            for s in b[j1:j2]:
                filas.append({"t": "+", "s": _corta(s)})
                stats["added"] += 1

        cortes.append({
            "before_start": grupo[0][1] + 1,
            "after_start": grupo[0][3] + 1,
            "lines": filas[:_MAX_LINEAS_POR_HUNK],
            "lines_total": len(filas),
        })

    return {
        "hunks": cortes[:_MAX_HUNKS],
        "hunks_total": len(cortes),
        "truncated": len(cortes) > _MAX_HUNKS,
        "stats": stats,
        "too_big": False,
    }
