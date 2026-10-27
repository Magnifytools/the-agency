// Cuentas de la vista con horas de Mi agenda. Todo en hora civil de la agencia
// sin zona ("2026-10-28T10:30"), como guarda el servidor bloques y reuniones.
import { addCivilDays } from "@/lib/dates"

export const GRID_START_HOUR = 8
export const GRID_END_HOUR = 20
export const GRID_START = GRID_START_HOUR * 60
export const GRID_END = GRID_END_HOUR * 60
/** Píxeles por minuto: una hora mide 48 px. */
export const PX_PER_MINUTE = 0.8
export const SNAP_MINUTES = 15
export const MIN_BLOCK = 15
export const DEFAULT_BLOCK = 60
export const MAX_NEW_BLOCK = 240

export const dayOf = (stamp: string) => stamp.slice(0, 10)

export function minutesOf(stamp: string) {
  const [hours, minutes] = stamp.slice(11, 16).split(":").map(Number)
  return hours * 60 + minutes
}

/** "10:30" → 630. */
export const clockMinutes = (clock: string) => minutesOf(`0000-00-00T${clock}`)

/** "2026-10-28" + 630 → "2026-10-28T10:30"; 1440 es la medianoche del día siguiente. */
export function stampAt(day: string, minutes: number) {
  if (minutes >= 1440) return `${addCivilDays(day, 1)}T00:00`
  return `${day}T${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`
}

export const snap = (minutes: number) => Math.round(minutes / SNAP_MINUTES) * SNAP_MINUTES

/** Un bloque de `duration` minutos que empieza cerca de `start`, dentro de la cuadrícula. */
export function placeBlock(start: number, duration: number) {
  const length = Math.max(MIN_BLOCK, Math.min(duration, GRID_END - GRID_START))
  const from = Math.min(Math.max(snap(start), GRID_START), GRID_END - length)
  return { start: from, end: from + length }
}

/** Duración de un bloque nuevo a partir de la estimación de la tarea. */
export function newBlockMinutes(estimated: number | null | undefined) {
  if (!estimated) return DEFAULT_BLOCK
  return Math.max(MIN_BLOCK, Math.min(MAX_NEW_BLOCK, snap(estimated) || MIN_BLOCK))
}

/** Lunes a viernes de la semana del día dado. */
export function workWeek(day: string) {
  const [year, month, date] = day.split("-").map(Number)
  const weekday = new Date(Date.UTC(year, month - 1, date)).getUTCDay()
  const monday = addCivilDays(day, weekday === 0 ? -6 : 1 - weekday)
  return [0, 1, 2, 3, 4].map((offset) => addCivilDays(monday, offset))
}

export interface Placed<T> {
  item: T
  top: number
  height: number
  lane: number
  lanes: number
}

/**
 * Posición de cada cosa de un día en la cuadrícula. Las que se solapan se
 * reparten en carriles, uno al lado de otro; lo que se sale de 8-20 se recorta.
 */
export function layoutDay<T>(items: T[], range: (item: T) => { start: number; end: number }): Placed<T>[] {
  const visible = items
    .map((item) => ({ item, ...range(item) }))
    .filter(({ start, end }) => end > GRID_START && start < GRID_END)
    .sort((a, b) => a.start - b.start || b.end - a.end)
  const placed: Placed<T>[] = []
  let cluster: Array<Placed<T> & { end: number }> = []
  let clusterEnd = -1
  const close = () => {
    const lanes = Math.max(1, ...cluster.map((entry) => entry.lane + 1))
    cluster.forEach(({ item, top, height, lane }) => placed.push({ item, top, height, lane, lanes }))
    cluster = []
  }
  for (const { item, start, end } of visible) {
    if (start >= clusterEnd && cluster.length) close()
    const used = new Set(cluster.filter((entry) => entry.end > start).map((entry) => entry.lane))
    let lane = 0
    while (used.has(lane)) lane += 1
    const top = (Math.max(start, GRID_START) - GRID_START) * PX_PER_MINUTE
    const height = Math.max(MIN_BLOCK, Math.min(end, GRID_END) - Math.max(start, GRID_START)) * PX_PER_MINUTE
    cluster.push({ item, top, height, lane, lanes: 1, end })
    clusterEnd = Math.max(clusterEnd, end)
  }
  if (cluster.length) close()
  return placed
}

export function formatClock(minutes: number) {
  return `${String(Math.floor(minutes / 60) % 24).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`
}
