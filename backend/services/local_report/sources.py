"""Lo que sube el equipo: CSV de la ficha de Google y CSV de Screaming Frog.

Ficha (business.google.com → Estadísticas → exportar): una fila de cabecera,
otra con la descripción de cada columna y una fila por ficha. Personas que
vieron la ficha = las cuatro columnas de Búsqueda y Maps; interacciones =
llamadas + mensajes + reservas + cómo llegar + clics web + pedidos + clics en
el menú. Las fechas van en el nombre del archivo y se comprueban.

Rastreo (Screaming Frog, "Redirection (3xx) Inlinks"): una fila por enlace a
una página que redirige; los de cabecera, menú y pie se separan por
`Link Position`.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date

from backend.services.local_report.periods import range_label

GBP_VIEWS = ("Búsqueda de Google (móvil)", "Búsqueda de Google (ordenador)",
             "Google Maps (móvil)", "Google Maps (ordenador)")
GBP_INTERACTIONS = ("Llamadas", "Mensajes", "Reservas", "Cómo llegar", "Clics al sitio web",
                    "Pedidos de comida", "Clics en el menú de comida")
_SURFACES = {"busqueda_movil": GBP_VIEWS[0], "busqueda_ordenador": GBP_VIEWS[1],
             "maps_movil": GBP_VIEWS[2], "maps_ordenador": GBP_VIEWS[3]}
_DATES = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})")
MAX_CSV_BYTES = 2 * 1024 * 1024
RECURRING_POSITIONS = {"navigation", "header", "footer"}


class SourceError(ValueError):
    """El archivo no es lo que se espera: el mensaje se enseña tal cual."""


def _text(content: bytes) -> str:
    if len(content) > MAX_CSV_BYTES:
        raise SourceError("El archivo pesa demasiado para ser una exportación (máximo 2 MB).")
    for encoding in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SourceError("No se puede leer el archivo como texto.")


def _int(value: str | None) -> int:
    value = (value or "").strip().replace(".", "").replace(",", "")
    return int(value) if value.isdigit() else 0


def dates_in_name(filename: str) -> tuple[date, date] | None:
    match = _DATES.search(filename or "")
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1)), date.fromisoformat(match.group(2))
    except ValueError:
        return None


def parse_gbp(content: bytes, filename: str, *, business: str | None = None) -> dict:
    """Cifras de una exportación de la ficha. Si trae varias fichas, la del negocio."""
    rows = list(csv.reader(io.StringIO(_text(content))))
    if not rows or "Nombre de la empresa" not in rows[0]:
        raise SourceError("No parece una exportación de la ficha de Google: falta la columna "
                          "\"Nombre de la empresa\".")
    header = rows[0]
    missing = [c for c in (*GBP_VIEWS, "Llamadas", "Cómo llegar") if c not in header]
    if missing:
        raise SourceError("Faltan columnas en la exportación de la ficha: " + ", ".join(missing))
    data = [dict(zip(header, r)) for r in rows[1:] if r and any(c.strip() for c in r)]
    # La segunda fila describe las columnas: no tiene nombre de empresa.
    data = [r for r in data if (r.get("Nombre de la empresa") or "").strip()]
    if not data:
        raise SourceError("La exportación de la ficha no trae ninguna fila de datos.")
    row = data[0]
    if len(data) > 1 and business:
        row = next((r for r in data if business.lower() in r["Nombre de la empresa"].lower()), data[0])

    get = lambda name: _int(row.get(name))  # noqa: E731
    dates = dates_in_name(filename)
    return {
        "empresa": row["Nombre de la empresa"].strip(),
        "inicio": dates[0].isoformat() if dates else None,
        "fin": dates[1].isoformat() if dates else None,
        "periodo": range_label(*dates) if dates else None,
        "vistas_perfil": sum(get(c) for c in GBP_VIEWS),
        "interacciones": sum(get(c) for c in GBP_INTERACTIONS),
        "clics_llamada": get("Llamadas"),
        "indicaciones": get("Cómo llegar"),
        "clics_web": get("Clics al sitio web"),
        "acciones_reserva": get("Reservas"),
        "clics_carta": get("Clics en el menú de comida"),
        "vistas_por_superficie": {key: get(col) for key, col in _SURFACES.items()},
        "fichas_en_archivo": len(data),
    }


def check_gbp_dates(parsed: dict, expected_start: date, expected_end: date) -> str | None:
    """Aviso si las fechas del archivo no son las pedidas (la ficha va un día por detrás:
    se admite que acabe antes, nunca que empiece en otro día o se pase)."""
    if not parsed.get("inicio"):
        return ("El nombre del archivo no trae las fechas (AAAA-MM-DD_AAAA-MM-DD): "
                "no se puede comprobar que sea el periodo pedido.")
    start, end = date.fromisoformat(parsed["inicio"]), date.fromisoformat(parsed["fin"])
    if start != expected_start or end > expected_end or (expected_end - end).days > 3:
        return (f"El archivo es del {range_label(start, end)} y se esperaba el "
                f"{range_label(expected_start, expected_end)}.")
    return None


def parse_crawl(content: bytes) -> dict:
    """Recuento de enlaces internos a páginas que redirigen."""
    reader = csv.DictReader(io.StringIO(_text(content)))
    fields = reader.fieldnames or []
    if "Source" not in fields or "Destination" not in fields:
        raise SourceError("No parece la exportación \"Redirection (3xx) Inlinks\" de Screaming Frog: "
                          "faltan las columnas Source y Destination.")
    rows = [r for r in reader if (r.get("Source") or "").strip()]
    recurring = [r for r in rows if (r.get("Link Position") or "").strip().lower() in RECURRING_POSITIONS]
    by_position: dict[str, int] = {}
    for r in rows:
        position = (r.get("Link Position") or "Sin dato").strip() or "Sin dato"
        by_position[position] = by_position.get(position, 0) + 1
    return {
        "enlaces_redirigen": len(rows),
        "origenes": len({r["Source"].strip() for r in rows}),
        "destinos": len({r["Destination"].strip() for r in rows}),
        "recurrentes": len(recurring),
        "por_posicion": by_position,
        "ejemplos": [{"origen": r["Source"].strip(), "destino": r["Destination"].strip(),
                      "posicion": (r.get("Link Position") or "").strip()} for r in rows[:10]],
    }
