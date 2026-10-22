"""Barrido de calibración de la vigilancia de cambios: compara, guarda y NO avisa.

Para el corte de Vigil (``docs/vigil-migration.md``, paso 5): tras importar sus
datos, la primera pasada desde The Agency sale por otra IP y con otro proceso.
Si el WAF de un cliente o su CDN sirven otra cosa a esa IP, todas sus URLs
"cambian" a la vez. Esta pasada lo saca a la luz SIN mandar nada al Slack del
cliente: los cambios quedan en ``/web/cambios`` para revisarlos y marcarlos.

Cada cliente es un barrido ``manual`` con ``notify=False`` (el mismo
``sweep_client`` del job): no gasta el barrido programado del día, no llama a
Slack y no depende de ``WEB_SWEEP_ENABLED``. La bandeja de incidencias sí se
entera de los críticos, como con cualquier barrido.

Tiene que correr DENTRO del servicio de The Agency en Railway
(``railway ssh``), no en un portátil: lo que se calibra es justo la IP y la red
desde las que va a mirar el job.

Uso:
  python -m backend.scripts.web_calibrate                  # todos los clientes con URLs
  python -m backend.scripts.web_calibrate --client-id 12   # uno (repetible)
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import exists, select

from backend.db.models import Client, WebWatch
from backend.services.web.sweep import monitored_clients_clause, sweep_client, watched_clause


async def calibration_clients(db, only: list[int] | None = None) -> list[tuple[int, str]]:
    """Clientes activos externos con alguna URL vigilada (activa, sin archivar)."""
    query = select(Client.id, Client.name).where(
        monitored_clients_clause(),
        exists().where(WebWatch.client_id == Client.id, watched_clause()),
    ).order_by(Client.name)
    if only:
        query = query.where(Client.id.in_(only))
    return [(r.id, r.name) for r in (await db.execute(query)).all()]


async def calibrate(session_factory, only: list[int] | None = None, **sweep_kwargs) -> list[dict]:
    """Un barrido sin avisos por cliente. Devuelve el resumen de cada uno."""
    async with session_factory() as db:
        targets = await calibration_clients(db, only)
        await db.commit()
    results = []
    for client_id, name in targets:
        summary = await sweep_client(session_factory, client_id, trigger="manual", notify=False, **sweep_kwargs)
        summary["name"] = name
        results.append(summary)
    return results


def format_results(results: list[dict]) -> str:
    if not results:
        return "Ningún cliente activo con URLs vigiladas."
    lines = []
    for r in results:
        cut = f", hosts cortados: {', '.join(r['hosts_cut'])}" if r.get("hosts_cut") else ""
        lines.append(f"#{r['client_id']} {r['name']}: {r.get('watches', 0)} URL(s), {r.get('ok', 0)} bien, "
                     f"{r.get('errors', 0)} con error, {r.get('changes', 0)} cambio(s){cut}")
    total = sum(r.get("changes", 0) for r in results)
    lines.append(f"Total: {total} cambio(s). Nada se ha mandado a Slack; revísalos en /web/cambios.")
    return "\n".join(lines)


async def main(only: list[int] | None) -> int:
    from backend.db.database import async_session, engine

    try:
        print(format_results(await calibrate(async_session, only)))
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client-id", type=int, action="append", help="Sólo este cliente (repetible)")
    sys.exit(asyncio.run(main(parser.parse_args().client_id)))
