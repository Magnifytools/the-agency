import type { TaskCreate } from "@/lib/types"

export const RECURRENCE_PATTERNS = [
  { value: "daily", label: "Diaria (L-V)" },
  { value: "weekly", label: "Semanal" },
  { value: "weekdays", label: "Varios días" },
  { value: "biweekly", label: "Cada dos semanas" },
  { value: "monthly", label: "Mensual" },
  { value: "quarterly", label: "Trimestral" },
  { value: "last_business_day", label: "Último día hábil" },
] as const

export const WEEKDAY_LABELS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"] as const

type Rule = Pick<TaskCreate, "recurrence_pattern" | "recurrence_day" | "recurrence_weekdays">

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

/** Día y días de una regla al elegir su frecuencia: cada una guarda sólo lo suyo. */
export function ruleForPattern(current: Rule, pattern: string): Rule {
  if (pattern === "monthly" || pattern === "quarterly") {
    return { recurrence_pattern: pattern, recurrence_day: clamp(current.recurrence_day ?? 1, 1, 28), recurrence_weekdays: null }
  }
  if (pattern === "weekdays") {
    const days = current.recurrence_weekdays?.length
      ? current.recurrence_weekdays
      : [clamp(current.recurrence_day ?? 0, 0, 4)]
    return { recurrence_pattern: pattern, recurrence_day: null, recurrence_weekdays: days }
  }
  if (pattern === "last_business_day") {
    return { recurrence_pattern: pattern, recurrence_day: null, recurrence_weekdays: null }
  }
  return { recurrence_pattern: pattern, recurrence_day: clamp(current.recurrence_day ?? 0, 0, 4), recurrence_weekdays: null }
}

export function toggleWeekday(days: number[] | null | undefined, day: number): number[] {
  const current = days ?? []
  return current.includes(day) ? current.filter((value) => value !== day) : [...current, day].sort()
}
