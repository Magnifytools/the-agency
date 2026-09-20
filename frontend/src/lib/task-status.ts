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
