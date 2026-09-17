import type { TaskCreate } from "@/lib/types"

export type TasksInitialView = "my_day" | "all"

export function initialTasksView(search: URLSearchParams): TasksInitialView {
  return search.get("qaFilter") ? "all" : "my_day"
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
