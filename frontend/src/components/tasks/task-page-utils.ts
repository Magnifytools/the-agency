import type { TaskCreate } from "@/lib/types"

export type TasksInitialView = "my_day" | "sprint" | "all" | "calendar" | "weekly" | "recurring"

export function initialTasksView(search: URLSearchParams): TasksInitialView {
  if (search.get("qaFilter")) return "all"
  const view = search.get("view")
  return ["my_day", "sprint", "all", "calendar", "weekly", "recurring"].includes(view ?? "") ? view as TasksInitialView : "my_day"
}

export function taskQueryKeyWithWeek(base: readonly unknown[], week: { from: string; to: string }) {
  return [...base, week.from, week.to]
}

export function withExplicitActualMinutes(data: TaskCreate, rawValue: FormDataEntryValue | null, wasEdited: boolean): TaskCreate {
  if (!wasEdited) return data
  return { ...data, actual_minutes: rawValue ? Number(rawValue) : null }
}

export function shouldPreserveCurrentProject(currentProjectId: number | null | undefined, selectedProjectId: string, activeProjectIds: number[]) {
  return !!currentProjectId && selectedProjectId === String(currentProjectId) && !activeProjectIds.includes(currentProjectId)
}
