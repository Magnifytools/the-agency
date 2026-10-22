"""Importa UNA vez los leads por landing de The Engine (``lead_attribution``) a
``ga4_lead_daily`` de The Agency.

The Engine se retira (decisión de David, 22 oct 2026). The Agency ya importa
los leads por su cuenta (``services/ga4_leads.py``); esto sólo trae los días
que The Agency no tiene. Exportación y uso: ``docs/engine-data-import.md``.

Entrada: CSV con cabecera ``date,landing_host,landing_page,event_name,channel,leads``
(``landing_host`` puede faltar o venir vacío en filas antiguas de Engine).

Qué hace
--------
- Landing y canal se normalizan EXACTAMENTE como en la importación de GA4
  (``ga4_leads.clean_landing`` / ``clean_channel``): host + ruta sin
  parámetros de seguimiento; el canal "unknown" de Engine pasa a "(not set)".
- Sólo cuenta los eventos que la propiedad cuenta hoy como lead
  (``clients.ga4_lead_events``; en Engine eran ``generate_lead_*``).
- Suma las filas que acaban en el mismo (día, landing, canal).
- Sólo días ANTERIORES al primero que importó The Agency
  (``ga4_property_sync.leads_covered_from``) y dentro de la retención de 16
  meses (lo anterior se borraría en la próxima pasada).
- Idempotente: repetirlo sustituye esos días y da lo mismo. Todo en UNA
  transacción; ``--dry-run`` hace lo mismo y deshace al final.

Uso (desde la raíz del repo, con ``DATABASE_URL`` de la base destino):

  python -m backend.scripts.import_engine_leads --csv fit_leads.csv --property-id 123456789 --dry-run
  python -m backend.scripts.import_engine_leads --csv fit_leads.csv --property-id 123456789
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from backend.config import settings
from backend.db.models import Ga4PropertySync
from backend.services import ga4_leads
from backend.services.ga4_leads import EventMatcher, LeadRow, clean_channel, clean_landing, merge_rows
from backend.services.ga4_service import normalize_property
from backend.services.temporal import business_today

REQUIRED_COLUMNS = ("date", "landing_page", "event_name", "channel", "leads")


class ImportAborted(Exception):
    pass


@dataclass
class LeadsReport:
    dry_run: bool
    property_id: str = ""
    events: tuple[str, ...] = ()
    rows_read: int = 0
    rows_skipped: int = 0
    rows_other_events: int = 0
    first_date: date | None = None
    last_date: date | None = None
    agency_from: date | None = None
    retention_floor: date | None = None
    days_owned_by_agency: int = 0
    days_beyond_retention: int = 0
    days_imported: int = 0
    rows_written: int = 0
    leads_written: int = 0


def read_csv(path: str | Path, matcher: EventMatcher, report: LeadsReport) -> list[LeadRow]:
    rows: list[LeadRow] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ImportAborted(f"Al CSV le faltan columnas: {', '.join(missing)}")
        for row in reader:
            report.rows_read += 1
            try:
                day = date.fromisoformat((row["date"] or "").strip()[:10])
                leads = int(float(row["leads"] or 0))
            except ValueError:
                report.rows_skipped += 1
                continue
            if leads <= 0:
                report.rows_skipped += 1
                continue
            if not matcher((row["event_name"] or "").strip()):
                report.rows_other_events += 1
                continue
            report.first_date = min(filter(None, [report.first_date, day]))
            report.last_date = max(filter(None, [report.last_date, day]))
            rows.append(LeadRow(day, clean_landing(row["landing_page"], row.get("landing_host")),
                                clean_channel(row["channel"]), leads))
    return merge_rows(rows)


async def run_import(db, csv_path: str | Path, *, property_id: str, dry_run: bool = False,
                     today: date | None = None) -> LeadsReport:
    report = LeadsReport(dry_run=dry_run)
    pid = normalize_property(property_id)
    if pid is None:
        raise ImportAborted(f"«{property_id}» no es un ID de propiedad de GA4 (sólo dígitos)")
    events = (await ga4_leads.property_lead_events(db)).get(pid)
    if events is None:
        raise ImportAborted(f"La propiedad {pid} no es de ningún cliente activo: la retención la borraría")
    report.property_id, report.events = pid, tuple(events)

    rows = read_csv(csv_path, EventMatcher(events), report)
    state = await db.get(Ga4PropertySync, pid)
    report.agency_from = state.leads_covered_from if state else None
    report.retention_floor = ga4_leads.retention_floor(today or business_today())
    by_day: dict[date, list[LeadRow]] = {}
    for r in rows:
        by_day.setdefault(r.date, []).append(r)
    wanted: list[LeadRow] = []
    for day, items in sorted(by_day.items()):
        if report.agency_from is not None and day >= report.agency_from:
            report.days_owned_by_agency += 1
        elif day < report.retention_floor:
            report.days_beyond_retention += 1
        else:
            report.days_imported += 1
            wanted.extend(items)

    try:
        if wanted:
            start, end = wanted[0].date, wanted[-1].date
            # Todo el tramo es anterior a lo de The Agency: sólo puede haber lo importado antes.
            report.rows_written = await ga4_leads.replace_range(db, pid, start, end, wanted)
            report.leads_written = sum(r.leads for r in wanted)
        if dry_run:
            await db.rollback()
        else:
            await db.commit()
    except Exception:
        await db.rollback()
        raise
    return report


def format_report(report: LeadsReport) -> str:
    head = "SIMULACRO (--dry-run): nada se ha guardado" if report.dry_run else "Importación confirmada"
    lines = [
        head,
        f"Propiedad GA4: {report.property_id}; eventos que cuentan como lead: {', '.join(report.events)}.",
        f"Filas del CSV: {report.rows_read} leídas, {report.rows_skipped} descartadas (ilegibles o sin leads), "
        f"{report.rows_other_events} de otros eventos; del {report.first_date} al {report.last_date}.",
        f"The Agency importa desde: {report.agency_from or 'todavía nada'}. "
        f"Retención: desde el {report.retention_floor}.",
        f"Días que ya tiene The Agency (no se tocan): {report.days_owned_by_agency}. "
        f"Días anteriores a la retención (se borrarían): {report.days_beyond_retention}.",
        f"Días importados: {report.days_imported}; filas (día × landing × canal): {report.rows_written}; "
        f"leads: {report.leads_written}.",
    ]
    if report.agency_from is None and report.days_imported:
        lines.append("AVISO: The Agency aún no ha importado leads de esta propiedad. Su primera importación "
                     "(16 meses) sustituirá los días que coincidan (Google manda).")
    return "\n".join(lines)


def _db_label() -> str:
    parts = urlsplit(settings.DATABASE_URL)
    return f"{parts.hostname}:{parts.port or 5432}/{parts.path.lstrip('/')}"


async def main(args: argparse.Namespace) -> int:
    from backend.db.database import async_session, engine

    try:
        print(f"Engine: {args.csv}. Destino: {_db_label()}.", flush=True)
        async with async_session() as db:
            report = await run_import(db, args.csv, property_id=args.property_id, dry_run=args.dry_run)
        print(format_report(report))
        return 0
    except ImportAborted as exc:
        print(f"ABORTADO: {exc}", file=sys.stderr)
        return 2
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", required=True, help="CSV exportado de lead_attribution de Engine")
    parser.add_argument("--property-id", required=True, help="Propiedad de GA4 de The Agency (sólo dígitos)")
    parser.add_argument("--dry-run", action="store_true", help="Hace todo y deshace al final")
    sys.exit(asyncio.run(main(parser.parse_args())))
