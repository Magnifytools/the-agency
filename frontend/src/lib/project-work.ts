import type { PhaseStatus, TaskPriority, TaskStatus } from "@/lib/types"

export interface ProjectTaskItem {
  id: number
  title: string
  status: TaskStatus
  priority: TaskPriority
  assigned_to: number | null
  assigned_user_name: string | null
  scheduled_date: string | null
  start_date: string | null
  due_date: string | null
  estimated_minutes: number | null
  waiting_for: string | null
  follow_up_date: string | null
  is_recurring?: boolean
}

export interface ProjectTaskGroup {
  phase: {
    id: number
    name: string
    order_index: number
    status: PhaseStatus
    phase_type: string
    start_date: string | null
    due_date: string | null
  }
  tasks: ProjectTaskItem[]
}

export interface ProjectTasksResponse {
  project_id: number
  project_name: string
  phases: ProjectTaskGroup[]
  unassigned_tasks: ProjectTaskItem[]
}

const priorityOrder: Record<TaskPriority, number> = { urgent: 0, high: 1, medium: 2, low: 3 }
export const plannedDate = (task: ProjectTaskItem) => [task.scheduled_date, task.due_date?.slice(0, 10)]
  .filter((date): date is string => !!date).sort()[0] || null

/** Read existing commitments; never create dates or infer completion from edits. */
export function projectWork(tasks: ProjectTaskItem[]) {
  const active = tasks.filter(task => task.status !== "completed")
  const planned = active.filter(task => task.status !== "waiting" && task.status !== "backlog" && plannedDate(task))
    .sort((a, b) => plannedDate(a)!.localeCompare(plannedDate(b)!) || priorityOrder[a.priority] - priorityOrder[b.priority] || a.id - b.id)
  const waiting = active.filter(task => task.status === "waiting")
    .sort((a, b) => (a.follow_up_date || "9999").localeCompare(b.follow_up_date || "9999") || a.id - b.id)
  return { next: planned[0] ?? null, waiting, unplanned: active.filter(task => task.status !== "waiting" && !plannedDate(task)).length }
}
