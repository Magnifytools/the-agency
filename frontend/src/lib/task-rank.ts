// Gemelo de backend/services/task_rank.py: predice los rangos que pondrá el
// servidor al mover una tarea, para pintar el nuevo orden al momento. Si cambias
// algo aquí, cámbialo allí (mismos casos en task-rank.test.ts y test_task_rank.py).

const ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
const BASE = ALPHABET.length
const SPREAD_WIDTH = 3

const digit = (value: string, index: number) => (index < value.length ? ALPHABET.indexOf(value[index]) : 0)

export function rankBetween(low: string | null, high: string | null): string {
  const from = low ?? ""
  let to = high
  if (to !== null && !(from < to)) throw new Error("low must sort before high")
  let result = ""
  for (let index = 0; ; index += 1) {
    const lowDigit = digit(from, index)
    const highDigit = to === null ? BASE : digit(to, index)
    if (lowDigit === highDigit) {
      result += ALPHABET[lowDigit]
      continue
    }
    const middle = Math.floor((lowDigit + highDigit) / 2)
    if (middle > lowDigit) return result + ALPHABET[middle]
    result += ALPHABET[lowDigit]
    to = null
  }
}

export function spreadRanks(count: number): string[] {
  const step = Math.floor(BASE ** SPREAD_WIDTH / (count + 1))
  return Array.from({ length: count }, (_, index) => {
    let value = (index + 1) * step
    let text = ""
    for (let place = 0; place < SPREAD_WIDTH; place += 1) {
      text = ALPHABET[value % BASE] + text
      value = Math.floor(value / BASE)
    }
    return text.replace(/0+$/, "")
  })
}

// Posiciones de la subsecuencia creciente más larga: las que no se tocan.
// Empates como en el servidor: primer predecesor y primer final.
function kept(ranks: Array<string | null>) {
  const best = ranks.map(() => 0)
  const previous = ranks.map(() => -1)
  ranks.forEach((rank, index) => {
    if (rank === null) return
    best[index] = 1
    for (let earlier = 0; earlier < index; earlier += 1) {
      const before = ranks[earlier]
      if (before !== null && before < rank && best[earlier] + 1 > best[index]) {
        best[index] = best[earlier] + 1
        previous[index] = earlier
      }
    }
  })
  const result = new Set<number>()
  const top = Math.max(0, ...best)
  if (top === 0) return result
  for (let index = best.indexOf(top); index !== -1; index = previous[index]) result.add(index)
  return result
}

function fill(ids: number[], low: string, high: string | null, out: Map<number, string>) {
  if (!ids.length) return
  const middle = Math.floor((ids.length - 1) / 2)
  const rank = rankBetween(low, high)
  out.set(ids[middle], rank)
  fill(ids.slice(0, middle), low, rank, out)
  fill(ids.slice(middle + 1), rank, high, out)
}

/** Rangos que cambian para que `orderedIds` quede en ese orden (como el servidor):
 * se conservan los que ya están en orden y sólo cambian la movida y las que lo rompen. */
export function ranksForMove(orderedIds: number[], movedId: number, current: Map<number, string | null>) {
  const ranks = orderedIds.map((id) => (id === movedId ? null : current.get(id) ?? null))
  const keep = kept(ranks)
  let fresh = new Map<number, string>()
  let run: number[] = []
  let low = ""
  orderedIds.forEach((id, index) => {
    if (keep.has(index)) {
      fill(run, low, ranks[index], fresh)
      run = []
      low = ranks[index]!
    } else run.push(id)
  })
  fill(run, low, null, fresh)
  if ([...fresh.values()].some((rank) => rank.length > 64)) {
    const spread = spreadRanks(orderedIds.length)
    fresh = new Map(orderedIds.map((id, index) => [id, spread[index]]))
  }
  return new Map([...fresh].filter(([id, rank]) => current.get(id) !== rank))
}

/** Con orden manual primero (por rango) y el resto como venían. Estable. */
export function byManualRank<T extends { sort_rank?: string | null }>(items: T[], fallback: (a: T, b: T) => number = () => 0) {
  return [...items].sort((a, b) => {
    if (a.sort_rank && b.sort_rank) return a.sort_rank < b.sort_rank ? -1 : a.sort_rank > b.sort_rank ? 1 : 0
    if (a.sort_rank) return -1
    if (b.sort_rank) return 1
    return fallback(a, b)
  })
}

/**
 * Ids de la lista destino tal como quedan al soltar `activeId` sobre `overId`
 * (null = en la lista pero no sobre una tarea: al final). En la misma lista se
 * comporta como el reordenado de @dnd-kit (ocupa el sitio de `overId`).
 */
export function orderAfterDrop(ids: number[], activeId: number, overId: number | null) {
  const from = ids.indexOf(activeId)
  const without = ids.filter((id) => id !== activeId)
  if (overId === null || overId === activeId) return from >= 0 ? ids : [...without, activeId]
  const to = ids.indexOf(overId)
  if (from >= 0) {
    without.splice(to, 0, activeId)
    return without
  }
  const at = without.indexOf(overId)
  return [...without.slice(0, at), activeId, ...without.slice(at)]
}
