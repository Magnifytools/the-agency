import type { TaskStatus } from "@/lib/types"

export type TaskStatusGroup = "pending" | "in_progress" | "waiting" | "in_review" | "completed"

export interface TaskStatusPresentation {
  group: TaskStatusGroup
  label: string
  detail: string | null
}

export const taskStatusGroups: Array<{ status: TaskStatusGroup; label: string; rawStatuses: TaskStatus[] }> = [
  { status: "pending", label: "Pendiente", rawStatuses: ["pending", "backlog"] },
  { status: "in_progress", label: "En curso", rawStatuses: ["in_progress", "advanced"] },
  { status: "waiting", label: "En espera", rawStatuses: ["waiting"] },
  { status: "in_review", label: "En revisión", rawStatuses: ["in_review"] },
  { status: "completed", label: "Hecho", rawStatuses: ["completed"] },
]

const statusSelectClasses: Record<TaskStatusGroup, string> = {
  pending: "task-status-select border-amber-500/60 bg-amber-500/10",
  in_progress: "task-status-select border-sky-500/60 bg-sky-500/10",
  waiting: "task-status-select border-orange-500/60 bg-orange-500/10",
  in_review: "task-status-select border-violet-500/60 bg-violet-500/10",
  completed: "task-status-select border-emerald-500/60 bg-emerald-500/10",
}

export function taskStatusSelectClass(status: TaskStatus, scheduledDate?: string | null) {
  return statusSelectClasses[taskStatusPresentation(status, scheduledDate).group]
}

export function taskStatusPresentation(
  status: TaskStatus,
  scheduledDate?: string | null,
): TaskStatusPresentation {
  switch (status) {
    case "backlog":
      return {
        group: "pending",
        label: "Pendiente",
        detail: scheduledDate ? "Backlog con fecha (revisar)" : "Sin planificar",
      }
    case "advanced":
      return { group: "in_progress", label: "En curso", detail: "Avance registrado" }
    case "in_progress":
      return { group: "in_progress", label: "En curso", detail: null }
    case "waiting":
      return { group: "waiting", label: "En espera", detail: null }
    case "in_review":
      return { group: "in_review", label: "En revisión", detail: null }
    case "completed":
      return { group: "completed", label: "Hecho", detail: null }
    case "pending":
      return { group: "pending", label: "Pendiente", detail: null }
  }
}

export function taskStatusFilterValue(group: TaskStatusGroup) {
  return taskStatusGroups.find((item) => item.status === group)?.rawStatuses.join(",") ?? group
}

interface PlannedStartFields {
  status: TaskStatus
  scheduled_date?: string | null
  is_recurring?: boolean | null
}

/**
 * Gemelo de `task_lifecycle.apply_planned_start` (backend): Pendiente es el
 * backlog sin fecha, así que una tarea pendiente con la Planificada de hoy o
 * pasada pasa a En curso al guardar; y si lo que se elige es Pendiente, se le
 * quita la fecha. Avisa ANTES de guardar de lo que hará el servidor.
 */
export function plannedStartNotice(
  draft: PlannedStartFields,
  saved: PlannedStartFields | null | undefined,
  today: string,
): string | null {
  const notStarted = draft.status === "pending" || draft.status === "backlog"
  if (!notStarted || !draft.scheduled_date || draft.scheduled_date > today || draft.is_recurring) return null
  const startsNow = "Al guardar pasa a En curso: su fecha planificada ya ha llegado."
  if (!saved) return startsNow
  if (draft.scheduled_date !== (saved.scheduled_date ?? null)) return startsNow
  if (draft.status !== saved.status) return "Al guardar se quita la fecha planificada: Pendiente es sin fecha."
  return null
}
