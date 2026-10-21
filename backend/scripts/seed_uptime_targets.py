"""Da de alta en el monitor de caídas la home de cada cliente (``Client.website``).

Sólo clientes activos y externos con web y sin ninguna URL vigilada todavía:
lo que ya tiene URLs (aunque estén pausadas) no se toca. Una web que no supera
la validación (puerto raro, host interno…) se lista y se salta.

Uso:
  python -m backend.scripts.seed_uptime_targets --dry-run   # por defecto: sólo enseña el plan
  python -m backend.scripts.seed_uptime_targets --apply     # crea las URLs

Idempotente. Las URLs nuevas entran en el siguiente ciclo del job ``uptime``.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import exists, select

from backend.db.database import async_session
from backend.db.models import Client, ClientStatus, WebUptimeState, WebUptimeTarget
from backend.schemas.web import normalize_target_url


async def build_plan(db) -> tuple[list[tuple[int, str, str]], list[tuple[int, str, str]]]:
    """Devuelve (a crear, saltados): tuplas (client_id, nombre, url o motivo)."""
    rows = (await db.execute(
        select(Client.id, Client.name, Client.website).where(
            Client.status == ClientStatus.active,
            Client.is_internal.is_(False),
            Client.website.isnot(None),
            ~exists().where(WebUptimeTarget.client_id == Client.id),
        ).order_by(Client.name)
    )).all()
    plan, skipped = [], []
    for client_id, name, website in rows:
        if not (website or "").strip():
            continue
        try:
            plan.append((client_id, name, normalize_target_url(website)))
        except ValueError as exc:
            skipped.append((client_id, name, f"{website!r}: {exc}"))
    return plan, skipped


async def main(apply: bool) -> None:
    async with async_session() as db:
        plan, skipped = await build_plan(db)
        for client_id, name, url in plan:
            print(f"+ {name} (#{client_id}): {url}")
        for client_id, name, reason in skipped:
            print(f"- {name} (#{client_id}) saltado: {reason}")
        print(f"{len(plan)} URL(s) a crear, {len(skipped)} saltada(s).")
        if not apply:
            print("Dry-run: no se ha escrito nada. Repite con --apply.")
            return
        now = datetime.now(UTC)
        for client_id, _name, url in plan:
            target = WebUptimeTarget(client_id=client_id, url=url, label="Home", is_active=True,
                                     created_at=now, updated_at=now)
            db.add(target)
            await db.flush()
            db.add(WebUptimeState(target_id=target.id, status="unknown", status_since=now, next_check_at=now))
        await db.commit()
        print(f"Creadas {len(plan)} URL(s).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Sólo enseña el plan (por defecto)")
    mode.add_argument("--apply", action="store_true", help="Crea las URLs")
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply))
