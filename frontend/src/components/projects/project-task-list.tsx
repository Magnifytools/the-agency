import { CheckCircle2, Circle } from "lucide-react"
import type { TaskStatus } from "@/lib/types"
import { Button } from "@/components/ui/button"

export interface ProjectTaskItem {
  id: number
  title: string
  status: TaskStatus
  assigned_to: number | string | null
}

interface Props {
  tasks: ProjectTaskItem[]
  showCompleted?: boolean
  canWrite: boolean
  pendingTaskId?: number
  onStatusChange: (id: number, status: TaskStatus) => void
  onOpen: (id: number) => void
}

/** Keep the working list short without removing history or search matches. */
export function ProjectTaskList({ tasks, showCompleted, canWrite, pendingTaskId, onStatusChange, onOpen }: Props) {
  const active = tasks.filter(task => task.status !== "completed")
  const completed = tasks.filter(task => task.status === "completed")
  const row = (task: ProjectTaskItem) => {
    const done = task.status === "completed"
    return <div key={task.id} className="flex items-center gap-2 rounded-lg hover:bg-card/50">
      {canWrite && <Button
        variant="ghost" size="icon" className="shrink-0"
        aria-label={`${done ? "Reabrir" : "Completar"}: ${task.title}`}
        disabled={pendingTaskId === task.id}
        onClick={() => onStatusChange(task.id, done ? "pending" : "completed")}
      >
        {done ? <CheckCircle2 className="h-5 w-5 text-success" /> : <Circle className="h-5 w-5 text-muted-foreground" />}
      </Button>}
      <button type="button" aria-label={`Abrir tarea: ${task.title}`} onClick={() => onOpen(task.id)}
        className="min-w-0 flex-1 py-3 px-1 text-left rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
        <span className={`block text-sm break-words ${done ? "line-through text-muted-foreground" : ""}`}>{task.title}</span>
        <span className="block text-xs text-muted-foreground mt-0.5">{task.assigned_to || "Sin responsable"}</span>
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
