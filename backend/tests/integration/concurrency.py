"""Sincronización determinista para los tests de concurrencia contra Postgres.

Los tests de concurrencia demostraban que "B espera a A" durmiendo un rato
(``asyncio.sleep(0.1)``) y dando a cada paso 1-2 s de plazo. En una máquina
cargada (suite completa, vitest en paralelo) eso falla sin que haya ningún
fallo real. Aquí se pregunta a Postgres en vez de adivinar.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Plazo para detectar un cuelgue, NO para medir rendimiento: con la máquina
# cargada un paso legítimo puede tardar varios segundos.
HANG_TIMEOUT = 30.0


async def wait_until_blocked_by(
    observer: AsyncSession,
    waiter_pid: int,
    holder_pid: int,
    waiter_task: asyncio.Task | None = None,
    *,
    timeout: float = HANG_TIMEOUT,
) -> None:
    """Espera a que ``waiter_pid`` esté bloqueado por un lock de ``holder_pid``.

    Falla en cuanto ``waiter_task`` termina sin haberse bloqueado (no esperó
    el lock: eso es justo el bug que el test quiere detectar).
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        blockers = await observer.scalar(
            text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter_pid},
        )
        await observer.rollback()  # snapshot nuevo en cada vuelta
        if holder_pid in (blockers or []):
            return
        if waiter_task is not None and waiter_task.done():
            waiter_task.result()  # propaga la excepción si la hubo
            raise AssertionError(
                "la operación concurrente terminó sin esperar el bloqueo"
            )
        if loop.time() > deadline:
            raise AssertionError(
                f"pid {waiter_pid} no llegó a esperar el bloqueo de {holder_pid}"
            )
        await asyncio.sleep(0.01)
