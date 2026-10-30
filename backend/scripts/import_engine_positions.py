"""Importa UNA vez el historial de posiciones de The Engine (``keyword_positions``)
al historial mensual por consulta de The Agency (``gsc_query_monthly``).

The Engine se retira (decisión de David, 22 oct 2026) y es el único sitio con
posiciones de algunos clientes de antes de los 16 meses que guarda Google (Sage
desde el 4 dic 2024). Exportación y uso: ``docs/engine-data-import.md``.

Entrada: CSV con cabecera ``keyword,date,position,clicks,impressions`` y,
opcionales, ``url,device`` (los ignora: el historial es por consulta).

Qué hace
--------
- Normaliza la consulta como Search Console (minúsculas, espacios colapsados):
  en Engine había keywords metidas a mano en mayúsculas ("TSAF") que son la
  misma consulta que Google devuelve en minúsculas.
- Agrupa por mes: clics e impresiones se SUMAN; la posición se pondera por
  impresiones (``weighted_position_sum`` = Σ posición × impresiones).
  Filas sin posición o sin consulta se descartan (y se cuentan).
- Sólo meses COMPLETOS del CSV (el último se descarta si el CSV no llega a su
  último día) y sólo los ANTERIORES al primer mes que The Agency ya tiene de
  Google para esa web: nunca pisa un mes propio (además, ``ON CONFLICT DO
  NOTHING``).
- Se guardan con ``source='engine'``: no caducan a los 16 meses, pero se borran
  si la web deja de tener cliente activo o al purgar su cuenta de Google.
- Idempotente: repetirlo sustituye lo importado antes en esos meses y da lo
  mismo. Todo en UNA transacción; ``--dry-run`` hace lo mismo y deshace al final.

Uso (desde la raíz del repo, con ``DATABASE_URL`` de la base destino):

  python -m backend.scripts.import_engine_positions --csv sage.csv --client-id 12 --dry-run
  python -m backend.scripts.import_engine_positions --csv sage.csv --client-id 12
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.config import settings
from backend.db.bulk import insert_chunks
from backend.db.models import Client, ClientStatus, GscQueryMonthly
from backend.services.gsc_detail_service import month_end
from backend.services.gsc_service import normalize_site_url, tracked_sites

REQUIRED_COLUMNS = ("keyword", "date", "position", "clicks", "impressions")


class ImportAborted(Exception):
    pass


def normalize_query(text: str | None) -> str:
    """'  TSAF   a Distancia ' → 'tsaf a distancia' (como las devuelve Search Console)."""
    return " ".join((text or "").split()).lower()


@dataclass
class PositionsReport:
    dry_run: bool
    site_url: str = ""
    rows_read: int = 0
    rows_skipped: int = 0
    first_date: date | None = None
    last_date: date | None = None
    agency_first_month: date | None = None
    months_in_csv: list[date] = field(default_factory=list)
    months_incomplete: list[date] = field(default_factory=list)
    months_owned_by_agency: list[date] = field(default_factory=list)
    months_imported: list[date] = field(default_factory=list)
    rows_written: int = 0
    rows_conflicting: int = 0


def _int(value: str | None) -> int:
    return int(float(value)) if value not in (None, "") else 0


def read_csv(path: str | Path, report: PositionsReport) -> dict[tuple[str, date], list[float]]:
    """(consulta, mes) → [clics, impresiones, Σ posición × impresiones]."""
    acc: dict[tuple[str, date], list[float]] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ImportAborted(f"Al CSV le faltan columnas: {', '.join(missing)}")
        for row in reader:
            report.rows_read += 1
            try:
                query = normalize_query(row["keyword"])
                day = date.fromisoformat((row["date"] or "").strip()[:10])
                position = float(row["position"]) if row["position"] not in (None, "") else None
                clicks, impressions = _int(row["clicks"]), _int(row["impressions"])
            except ValueError:
                report.rows_skipped += 1
                continue
            if not query or position is None or position <= 0 or clicks < 0 or impressions < 0:
                report.rows_skipped += 1
                continue
            report.first_date = min(filter(None, [report.first_date, day]))
            report.last_date = max(filter(None, [report.last_date, day]))
            item = acc.setdefault((query, day.replace(day=1)), [0, 0, 0.0])
            item[0] += clicks
            item[1] += impressions
            item[2] += position * impressions
    return acc


async def run_import(db, csv_path: str | Path, *, client_id: int, site_url: str | None = None,
                     dry_run: bool = False) -> PositionsReport:
    report = PositionsReport(dry_run=dry_run)
    client = await db.get(Client, client_id)
    if client is None:
        raise ImportAborted(f"No existe el cliente {client_id}")
    if client.status != ClientStatus.active:
        raise ImportAborted(f"El cliente {client_id} no está activo: la retención borraría lo importado")
    site = normalize_site_url(client.gsc_url)
    if site is None:
        raise ImportAborted("El cliente no tiene propiedad de Search Console: ponla en sus Ajustes antes de importar")
    if site_url is not None and normalize_site_url(site_url) != site:
        raise ImportAborted(f"--site-url {normalize_site_url(site_url)} no es la propiedad del cliente ({site})")
    if site not in await tracked_sites(db):
        raise ImportAborted(f"{site} no está asociada a ningún cliente activo: la retención la borraría")
    report.site_url = site

    acc = read_csv(csv_path, report)
    months = sorted({m for _, m in acc})
    report.months_in_csv = months
    if months and report.last_date is not None and month_end(months[-1]) > report.last_date:
        report.months_incomplete = [months[-1]]
    agency_first = await db.scalar(select(func.min(GscQueryMonthly.month)).where(
        GscQueryMonthly.site_url == site, GscQueryMonthly.source == "google",
    ))
    report.agency_first_month = agency_first
    report.months_owned_by_agency = [m for m in months if agency_first is not None and m >= agency_first
                                     and m not in report.months_incomplete]
    wanted = [m for m in months if m not in report.months_incomplete and m not in report.months_owned_by_agency]
    report.months_imported = wanted

    try:
        if wanted:
            await db.execute(delete(GscQueryMonthly).where(
                GscQueryMonthly.site_url == site, GscQueryMonthly.source == "engine",
                GscQueryMonthly.month.in_(wanted),
            ))
            keep = set(wanted)
            values = [
                {"site_url": site, "month": month, "query": query, "clicks": int(clicks),
                 "impressions": int(impressions), "weighted_position_sum": float(weighted), "source": "engine"}
                for (query, month), (clicks, impressions, weighted) in sorted(acc.items()) if month in keep
            ]
            for batch in insert_chunks(GscQueryMonthly, values):
                stmt = pg_insert(GscQueryMonthly).values(batch).on_conflict_do_nothing()
                result = await db.execute(stmt.returning(GscQueryMonthly.month))
                written = len(result.all())
                report.rows_written += written
                report.rows_conflicting += len(batch) - written
        if dry_run:
            await db.rollback()
        else:
            await db.commit()
    except Exception:
        await db.rollback()
        raise
    return report


def _months(values: list[date]) -> str:
    if not values:
        return "ninguno"
    return f"{values[0]:%Y-%m} … {values[-1]:%Y-%m} ({len(values)})"


def format_report(report: PositionsReport) -> str:
    head = "SIMULACRO (--dry-run): nada se ha guardado" if report.dry_run else "Importación confirmada"
    lines = [
        head,
        f"Web: {report.site_url}",
        f"Filas del CSV: {report.rows_read} leídas, {report.rows_skipped} descartadas "
        f"(sin consulta, sin posición o ilegibles); del {report.first_date} al {report.last_date}.",
        f"Primer mes propio de The Agency (Google): {report.agency_first_month or 'ninguno todavía'}.",
        f"Meses en el CSV: {_months(report.months_in_csv)}.",
        f"Meses que ya tiene The Agency (no se tocan): {_months(report.months_owned_by_agency)}.",
        f"Mes incompleto descartado: {_months(report.months_incomplete)}.",
        f"Meses importados: {_months(report.months_imported)}.",
        f"Filas (consulta × mes) escritas: {report.rows_written}; en conflicto con The Agency: "
        f"{report.rows_conflicting}.",
    ]
    if report.agency_first_month is None and report.months_imported:
        lines.append("AVISO: The Agency aún no tiene meses de Google para esta web. Los meses de los últimos 16 "
                     "que importe después sustituirán a los de Engine (Google manda).")
    return "\n".join(lines)


def _db_label() -> str:
    parts = urlsplit(settings.DATABASE_URL)
    return f"{parts.hostname}:{parts.port or 5432}/{parts.path.lstrip('/')}"


async def main(args: argparse.Namespace) -> int:
    from backend.db.database import async_session, engine

    try:
        print(f"Engine: {args.csv}. Destino: {_db_label()}.", flush=True)
        async with async_session() as db:
            report = await run_import(db, args.csv, client_id=args.client_id, site_url=args.site_url,
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
    parser.add_argument("--csv", required=True, help="CSV exportado de keyword_positions de Engine")
    parser.add_argument("--client-id", required=True, type=int, help="Cliente de The Agency")
    parser.add_argument("--site-url", help="Comprobación: la propiedad de Search Console que se espera (la del cliente)")
    parser.add_argument("--dry-run", action="store_true", help="Hace todo y deshace al final")
    sys.exit(asyncio.run(main(parser.parse_args())))

