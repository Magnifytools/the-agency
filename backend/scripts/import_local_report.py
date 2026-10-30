"""Importar un informe SEO local hecho fuera de The Agency (p. ej. el de octubre de 2026).

Guarda el `datos.json` y el `roadmap.json` como una versión del cliente, con el
HTML y el PDF entregados y las fuentes tal cual. Sirve para que el informe del
mes siguiente parta de él: consultas de la tabla de grupos, filas técnicas,
nombres de páginas y tono de los textos. Si el cliente no tiene configuración,
se crea desde la plantilla.

    python -m backend.scripts.import_local_report --client-id 28 \\
        --start 2026-10-01 --end 2026-10-26 --dir referencia_octubre_2026 \\
        --delivered-on 2026-10-30 --dry-run

`--dir` contiene `datos.json`, `roadmap.json`, `informe.html`, `informe.pdf` y,
opcional, `fuentes/` (CSV de la ficha con las fechas en el nombre, CSV del
rastreo y notas). Idempotente: si ya hay una versión de ese periodo, no hace nada.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
from datetime import UTC, date, datetime, time
from pathlib import Path

from sqlalchemy import select

from backend.db import database
from backend.db.models import Client, ClientLocalReport, ClientLocalReportConfig, ClientLocalReportSource
from backend.services.local_report import periods, render, sources


def _source_kind(path: Path, per: periods.ReportPeriods) -> str:
    if path.suffix.lower() == ".csv":
        dates = sources.dates_in_name(path.name)
        if dates:
            for kind, window in (("gbp_actual", per.current), ("gbp_anterior", per.previous),
                                 ("gbp_ano_anterior", per.year_ago)):
                if dates[0] == window.start:
                    return kind
        if "redirect" in path.name.lower() or "3xx" in path.name.lower():
            return "rastreo"
    if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        return "captura"
    return "otro"


async def run(args) -> str:
    folder = Path(args.dir)
    datos = json.loads((folder / "datos.json").read_text(encoding="utf-8"))
    roadmap = json.loads((folder / "roadmap.json").read_text(encoding="utf-8"))
    html, pdf = (folder / "informe.html").read_bytes(), (folder / "informe.pdf").read_bytes()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    per = periods.compute(start, end)
    stem = f"{args.prefix}_Seguimiento_Mensual_{start.year}-{periods.MONTHS[start.month - 1].capitalize()}"
    datos.setdefault("contexto", {})["clics_total_search_console"] = datos["gsc"]["clics_mes"]
    checks = render.check(html, pdf, datos, roadmap)

    async with database.async_session() as db:
        client = await db.get(Client, args.client_id)
        if client is None:
            return f"No existe el cliente #{args.client_id}."
        existing = (await db.scalars(select(ClientLocalReport).where(
            ClientLocalReport.client_id == client.id, ClientLocalReport.period_start == start,
            ClientLocalReport.period_end == end))).first()
        if existing:
            return f"Ya hay una versión de ese periodo (#{existing.id}): no se importa nada."
        config = await db.get(ClientLocalReportConfig, client.id)
        if config is None:
            defaults = render.template_defaults(args.template)
            config = ClientLocalReportConfig(client_id=client.id, template=args.template,
                                             landing_url=defaults.pop("landing_url"), settings=defaults,
                                             roadmap=render.template_roadmap(args.template),
                                             project_id=args.project_id)
            db.add(config)
        delivered = (datetime.combine(date.fromisoformat(args.delivered_on), time(12), tzinfo=UTC)
                     if args.delivered_on else None)
        report = ClientLocalReport(
            client_id=client.id, period_start=start, period_end=end, datos=datos, roadmap=roadmap,
            inputs={}, warnings=[], checks=checks, computed_at=datetime.now(UTC), file_stem=stem,
            html=html, pdf=pdf, generated_at=delivered or datetime.now(UTC), delivered_at=delivered)
        db.add(report)
        await db.flush()
        found = []
        for path in sorted((folder / "fuentes").glob("*")) if (folder / "fuentes").is_dir() else []:
            if not path.is_file():
                continue
            kind = _source_kind(path, per)
            found.append(f"{path.name} → {kind}")
            db.add(ClientLocalReportSource(
                report_id=report.id, kind=kind, filename=path.name[:255],
                content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                content=path.read_bytes(), size=path.stat().st_size))
        summary = (f"Cliente #{client.id} {client.name}: versión {per.current.label}, "
                   f"{'entregada el ' + args.delivered_on if delivered else 'sin entregar'}, "
                   f"comprobaciones {'OK' if checks['ok'] else 'con fallos'}; fuentes: {', '.join(found) or 'ninguna'}.")
        if args.dry_run:
            await db.rollback()
            return "[simulación] " + summary
        await db.commit()
        return summary + f" Versión #{report.id}."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client-id", type=int, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--template", default="cigarral")
    parser.add_argument("--prefix", default="Cigarral")
    parser.add_argument("--project-id", type=int, default=None, help="Proyecto del plan, si se crea la configuración")
    parser.add_argument("--delivered-on", default=None, help="AAAA-MM-DD si ya se entregó al cliente")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
