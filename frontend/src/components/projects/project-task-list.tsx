import { CheckCircle2, Circle } from "lucide-react"
import type { TaskStatus } from "@/lib/types"
import { Button } from "@/components/ui/button"

import type { ProjectTaskItem } from "@/lib/project-work"
export type { ProjectTaskItem } from "@/lib/project-work"

interface Props {
  tasks: ProjectTaskItem[]
  showCompleted?: boolean
  canWrite: boolean
  requiresReview?: boolean
  canCompleteReviewedTask?: boolean
  pendingTaskId?: number
  onStatusChange: (id: number, status: TaskStatus) => void
  onOpen: (id: number) => void
}

/** Keep the working list short without removing history or search matches. */
export function ProjectTaskList({ tasks, showCompleted, canWrite, requiresReview = false, canCompleteReviewedTask = false, pendingTaskId, onStatusChange, onOpen }: Props) {
  const active = tasks.filter(task => task.status !== "completed")
  const completed = tasks.filter(task => task.status === "completed")
  const row = (task: ProjectTaskItem) => {
    const done = task.status === "completed"
    const sendsForReview = !done && requiresReview && !canCompleteReviewedTask && !task.is_recurring
    return <div key={task.id} className="flex items-center gap-2 rounded-lg hover:bg-card/50">
      {canWrite && <Button
        variant="ghost" size="icon" className="shrink-0"
        aria-label={`${done ? "Reabrir" : sendsForReview ? "Enviar a revisión" : "Completar"}: ${task.title}`}
        disabled={pendingTaskId === task.id}
        onClick={() => onStatusChange(task.id, done ? "pending" : sendsForReview ? "in_review" : "completed")}
      >
        {done ? <CheckCircle2 className="h-5 w-5 text-success" /> : <Circle className="h-5 w-5 text-muted-foreground" />}
      </Button>}
      <button type="button" aria-label={`Abrir tarea: ${task.title}`} onClick={() => onOpen(task.id)}
        className="min-w-0 flex-1 py-3 px-1 text-left rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
        <span className={`block text-sm break-words ${done ? "line-through text-muted-foreground" : ""}`}>{task.title}</span>
        <span className="block text-xs text-muted-foreground mt-0.5">{task.assigned_user_name || "Sin responsable"}</span>
        {sendsForReview && <span className="block text-xs text-muted-foreground">Se enviará a revisión antes de cerrarla.</span>}
      </button>
    </div>
  }
  return <div className="space-y-1">
    {active.map(row)}
    {showCompleted ? completed.map(row) : completed.length > 0 && <details className="pt-2">
      <summary className="min-h-10 py-2 cursor-pointer text-sm text-muted-foreground rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
        Completadas ({completed.length})
      </summary>
      <div className="mt-1">{completed.map(row)}</div>
    </details>}
  </div>
}
