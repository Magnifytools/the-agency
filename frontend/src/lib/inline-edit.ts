import { addCivilDays } from "@/lib/dates"

export interface DateShortcut {
  label: string
  date: string
}

/** Hoy, mañana y el lunes que viene (si hoy es lunes, el de la semana próxima). */
export function dateShortcuts(today: string): DateShortcut[] {
  const [year, month, day] = today.split("-").map(Number)
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay()
  const daysToMonday = weekday === 0 ? 1 : 8 - weekday
  return [
    { label: "Hoy", date: today },
    { label: "Mañana", date: addCivilDays(today, 1) },
    { label: "El lunes", date: addCivilDays(today, daysToMonday) },
  ]
}

/**
 * Un día escrito en el selector nativo sólo cuenta cuando está completo: al
 * teclear el año, el navegador emite 0002, 0020, 0202… antes de 2026.
 */
export function completeCivilDate(value: string): string | null {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number(value.slice(0, 4)) >= 2000 ? value : null
}

/** "90", "1h", "1h 30m", "1,5h" o "45m" → minutos; null si no se entiende. */
export function parseMinutes(text: string): number | null {
  const value = text.trim().toLowerCase().replace(",", ".")
  if (!value) return null
  if (/^\d+$/.test(value)) return Number(value) || null
  const match = value.match(/^(?:(\d+(?:\.\d+)?)\s*h)?\s*(?:(\d+)\s*m(?:in)?)?$/)
  if (!match || (!match[1] && !match[2])) return null
  const minutes = Math.round(Number(match[1] ?? 0) * 60) + Number(match[2] ?? 0)
  return minutes > 0 ? minutes : null
}

export function formatMinutes(minutes: number) {
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest > 0 ? `${hours}h ${rest}m` : `${hours}h`
}
