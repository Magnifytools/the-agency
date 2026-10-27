import type { TaskCreate } from "@/lib/types"

export type TasksInitialView = "my_day" | "sprint" | "all" | "calendar" | "weekly" | "recurring"
export type TasksWorkView = Exclude<TasksInitialView, "my_day">

const WORK_VIEWS: TasksWorkView[] = ["all", "sprint", "calendar", "weekly", "recurring"]
const LAST_VIEW_KEY = "agency.tasks.lastView"
/** `view=tareas` es el enlace del menú: abre la última vista de Tareas que usaste. */
export const LAST_TASKS_VIEW = "tareas"

export function initialTasksView(search: URLSearchParams): TasksInitialView {
  if (search.get("qaFilter")) return "all"
  const view = search.get("view")
  if (view === LAST_TASKS_VIEW) return lastTasksView()
  return ["my_day", ...WORK_VIEWS].includes(view ?? "") ? view as TasksInitialView : "my_day"
}

// Sólo comodidad: sin almacenamiento (privado, bloqueado) se abre la lista.
export function lastTasksView(): TasksWorkView {
  try {
    const stored = window.localStorage.getItem(LAST_VIEW_KEY)
    return WORK_VIEWS.includes(stored as TasksWorkView) ? stored as TasksWorkView : "all"
  } catch {
    return "all"
  }
}

export function rememberTasksView(view: TasksInitialView) {
  if (view === "my_day") return
  try { window.localStorage.setItem(LAST_VIEW_KEY, view) } catch { /* sin almacenamiento */ }
}

/** `mes=AAAA-MM` → { year, month (0-11) }; si no vale, el mes de `today`. */
export function calendarMonthFrom(value: string | null, today: string): { year: number; month: number } {
  const match = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(value ?? "")
  const [year, month] = match ? [Number(match[1]), Number(match[2])] : today.split("-").map(Number)
  return { year, month: month - 1 }
}

export function calendarMonthParam({ year, month }: { year: number; month: number }) {
  return `${year}-${String(month + 1).padStart(2, "0")}`
}

export function shiftCalendarMonth({ year, month }: { year: number; month: number }, delta: number) {
  const index = year * 12 + month + delta
  return { year: Math.floor(index / 12), month: ((index % 12) + 12) % 12 }
}

/** Lunes (AAAA-MM-DD) de la semana de `day`. */
export function mondayOf(day: string) {
  const [year, month, date] = day.split("-").map(Number)
  const weekday = new Date(Date.UTC(year, month - 1, date)).getUTCDay()
  const shifted = new Date(Date.UTC(year, month - 1, date + (weekday === 0 ? -6 : 1 - weekday)))
  return shifted.toISOString().slice(0, 10)
}

/** `semana=AAAA-MM-DD` (cualquier día de esa semana) → semanas desde la actual. */
export function weekOffsetFrom(value: string | null, today: string) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(`${value}T00:00:00Z`))) return 0
  const diff = Date.parse(`${mondayOf(value)}T00:00:00Z`) - Date.parse(`${mondayOf(today)}T00:00:00Z`)
  return Math.round(diff / (7 * 86_400_000))
}

export function weekParam(offset: number, today: string) {
  const monday = Date.parse(`${mondayOf(today)}T00:00:00Z`) + offset * 7 * 86_400_000
  return new Date(monday).toISOString().slice(0, 10)
}

/**
 * Qué estados pide el tablero: las columnas activas salen del filtro y "Hecho"
 * va aparte (sólo lo cerrado hace poco), si el filtro la incluye o es el de
 * por defecto.
 */
export function boardStatusQuery(filterStatus: string, activeFilter: string): { active: string | null; completed: boolean } {
  if (!filterStatus) return { active: activeFilter, completed: true }
  const parts = filterStatus.split(",").filter(Boolean)
  const active = parts.filter((status) => status !== "completed")
  return {
    active: active.length ? active.join(",") : null,
    completed: filterStatus === activeFilter || parts.includes("completed"),
  }
}

export function taskQueryKeyWithWeek(base: readonly unknown[], week: { from: string; to: string }) {
  return [...base, week.from, week.to]
}

export function selectedTaskAssignee(search: URLSearchParams, userId: number | undefined, isAdmin: boolean): string {
  const value = search.get("assigned")
  if (value === "all") return ""
  if (value && /^[1-9]\d*$/.test(value)) return value
  return !isAdmin && userId ? String(userId) : ""
}

export function withTaskAssignee(search: URLSearchParams, value: string, isAdmin: boolean): URLSearchParams {
  const next = new URLSearchParams(search)
  if (value) next.set("assigned", value)
  else if (isAdmin) next.delete("assigned")
  else next.set("assigned", "all")
  return next
}

export function withExplicitActualMinutes(data: TaskCreate, rawValue: FormDataEntryValue | null, wasEdited: boolean): TaskCreate {
  if (!wasEdited) return data
  return { ...data, actual_minutes: rawValue ? Number(rawValue) : null }
}

export function shouldPreserveCurrentProject(currentProjectId: number | null | undefined, selectedProjectId: string, activeProjectIds: number[]) {
  return !!currentProjectId && selectedProjectId === String(currentProjectId) && !activeProjectIds.includes(currentProjectId)
}
