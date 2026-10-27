"""Orden manual de tareas con índices fraccionales (``tasks.sort_rank``).

Un rango es texto en base 62 que se compara como cadena: para meter una tarea
entre otras dos basta con calcular un valor intermedio, sin tocar las demás.
Nunca acaba en "0" (así "a" y "a0" no valen lo mismo).

Al soltar una tarea, el cliente manda la lista tal como queda en pantalla
(``ordered_ids``). Se conservan los rangos que ya están en orden y sólo reciben
uno nuevo la tarea movida y las que no tenían o rompían el orden: entre
vecinas ordenadas cambia una sola fila, y ordenar una columna del tablero no
mueve lo que ya estaba ordenado en Mi agenda. El frontend predice lo mismo con
``lib/task-rank.ts``: si cambias algo aquí, cámbialo allí (mismos casos en
``test_task_rank.py`` y ``task-rank.test.ts``).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE = len(ALPHABET)
_INDEX = {char: index for index, char in enumerate(ALPHABET)}
_SPREAD_WIDTH = 3


def is_rank(value: object) -> bool:
    return (
        isinstance(value, str) and 0 < len(value) <= 64
        and all(char in _INDEX for char in value) and not value.endswith("0")
    )


def rank_between(low: str | None, high: str | None) -> str:
    """Un rango estrictamente entre ``low`` y ``high`` (None = sin límite)."""
    low = low or ""
    if high is not None and not low < high:
        raise ValueError("low must sort before high")
    result = []
    index = 0
    while True:
        low_digit = _INDEX[low[index]] if index < len(low) else 0
        high_digit = (_INDEX[high[index]] if index < len(high) else 0) if high is not None else BASE
        if low_digit == high_digit:
            result.append(ALPHABET[low_digit])
            index += 1
            continue
        middle = (low_digit + high_digit) // 2
        if middle > low_digit:
            result.append(ALPHABET[middle])
            return "".join(result)
        # Dígitos contiguos: se baja un nivel y desde aquí ya no hay techo.
        result.append(ALPHABET[low_digit])
        index += 1
        high = None


def spread_ranks(count: int) -> list[str]:
    """``count`` rangos repartidos a la misma distancia, de menor a mayor."""
    step = BASE ** _SPREAD_WIDTH // (count + 1)
    ranks = []
    for position in range(1, count + 1):
        value = position * step
        digits = []
        for _ in range(_SPREAD_WIDTH):
            value, digit = divmod(value, BASE)
            digits.append(ALPHABET[digit])
        ranks.append("".join(reversed(digits)).rstrip("0"))
    return ranks


def _kept(ranks: Sequence[str | None]) -> set[int]:
    """Posiciones de la subsecuencia creciente más larga (las que no se tocan).

    Empates: el primer predecesor y el primer final que dan la longitud máxima
    (igual que en el frontend, para que la predicción coincida).
    """
    best = [0] * len(ranks)
    previous = [-1] * len(ranks)
    for index, rank in enumerate(ranks):
        if rank is None:
            continue
        best[index] = 1
        for earlier in range(index):
            if ranks[earlier] is not None and ranks[earlier] < rank and best[earlier] + 1 > best[index]:
                best[index] = best[earlier] + 1
                previous[index] = earlier
    if not ranks or max(best) == 0:
        return set()
    index = best.index(max(best))
    kept = set()
    while index != -1:
        kept.add(index)
        index = previous[index]
    return kept


def _fill(ids: Sequence[int], low: str, high: str | None, out: dict[int, str]) -> None:
    """Rangos para ``ids`` entre ``low`` y ``high``, repartidos en árbol (no se alargan en cadena)."""
    if not ids:
        return
    middle = (len(ids) - 1) // 2
    rank = rank_between(low, high)
    out[ids[middle]] = rank
    _fill(ids[:middle], low, rank, out)
    _fill(ids[middle + 1:], rank, high, out)


def ranks_for_move(
    ordered_ids: Sequence[int], moved_id: int, current: Mapping[int, str | None],
) -> dict[int, str]:
    """Rangos que cambian para que ``ordered_ids`` quede en ese orden.

    Se conservan los rangos que ya están en orden (la mayor cantidad posible) y
    sólo reciben uno nuevo la tarea movida y las que rompen el orden o no tenían:
    así ordenar una columna no desordena Mi agenda. ``current`` tiene el rango
    actual de cada tarea de la lista (o None).
    """
    ranks = [None if task_id == moved_id else current.get(task_id) for task_id in ordered_ids]
    kept = _kept(ranks)
    fresh: dict[int, str] = {}
    run: list[int] = []
    low = ""
    for index, task_id in enumerate(ordered_ids):
        if index in kept:
            _fill(run, low, ranks[index], fresh)
            run, low = [], ranks[index]
        else:
            run.append(task_id)
    _fill(run, low, None, fresh)
    if any(len(rank) > 64 for rank in fresh.values()):
        # Tras muchísimos arrastres en el mismo hueco: se reparte de nuevo.
        fresh = dict(zip(ordered_ids, spread_ranks(len(ordered_ids))))
    return {task_id: rank for task_id, rank in fresh.items() if current.get(task_id) != rank}
