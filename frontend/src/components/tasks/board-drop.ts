import type { Task, TaskStatus } from "@/lib/types"
import { taskStatusPresentation, type TaskStatusGroup } from "@/lib/task-status"

export type BoardDrop = { kind: "none" } | { kind: "waiting" } | { kind: "status"; status: TaskStatus }

/** Qué hace soltar una tarjeta en una columna. "En espera" pide datos: abre el panel. */
export function boardDrop(task: Task, target: TaskStatusGroup): BoardDrop {
  if (taskStatusPresentation(task.status, task.scheduled_date).group === target) return { kind: "none" }
  if (target === "waiting") return { kind: "waiting" }
  return { kind: "status", status: target }
}
