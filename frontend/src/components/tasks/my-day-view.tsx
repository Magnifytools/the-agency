import type { Task, TaskStatus } from "@/lib/types"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Pencil, CheckCircle2, Clock, AlertTriangle, CalendarX, RotateCcw, Repeat } from "lucide-react"
import { cn } from "@/lib/utils"
import { useAuth } from "@/context/auth-context"

const STATUS_CONFIG: Record<TaskStatus, { label: string; cls: string }> = {
  backlog:     { label: "Backlog",    cls: "text-slate-400 border-slate-300/60 bg-slate-50/30" },
  pending:     { label: "Pendiente",  cls: "text-muted-foreground border-border/60 bg-muted/30" },
  in_progress: { label: "En curso",   cls: "text-amber-600 border-amber-400/60 bg-amber-50/40" },
  waiting:     { label: "En espera",  cls: "text-purple-600 border-purple-400/60 bg-purple-50/40" },
  in_review:   { label: "En revisión", cls: "text-blue-600 border-blue-400/60 bg-blue-50/40" },
  completed:   { label: "Completada", cls: "text-green-600 border-green-400/60 bg-green-50/40" },
}

interface Props {
  tasks: Task[]
  onStatusChange: (id: number, status: TaskStatus) => void
  onOpenEdit: (task: Task) => void
}

const priorityOrder: Record<string, number> = { urgent: 0, high: 1, medium: 2, low: 3 }

const priorityBadge = (priority: string) => {
  const map: Record<string, { label: string; variant: "destructive" | "warning" | "secondary" | "outline" }> = {
    urgent: { label: "Urgente", variant: "destructive" },
    high: { label: "Alta", variant: "warning" },
    medium: { label: "Media", variant: "secondary" },
    low: { label: "Baja", variant: "outline" },
  }
  const { label, variant } = map[priority] ?? { label: priority, variant: "secondary" as const }
  return <Badge variant={variant} dot={false} className="text-[10px]">{label}</Badge>
}

const formatMinutes = (mins: number) => {
  if (mins < 60) return `${mins}m`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

export function MyDayView({ tasks, onStatusChange, onOpenEdit }: Props) {
  const { user } = useAuth()
  const now = new Date()
  const today = now.toISOString().split("T")[0]

  // Filter: active tasks that are either scheduled for today or assigned to me
  // If a task has a scheduled_date, only show if it's today
  // If no scheduled_date, fall back to "assigned to me"
  const myTasks = tasks.filter((t) => {
    if (t.status === "completed") return false
    if (t.scheduled_date === today) return true
    if (t.scheduled_date) return false // scheduled for another day
    return t.assigned_to === user?.id // no scheduled_date — show if assigned to me
  })

  // Sort: overdue first, then by priority, then by due date
  const sorted = [...myTasks].sort((a, b) => {
    const aOverdue = a.due_date && a.due_date < today ? 1 : 0
    const bOverdue = b.due_date && b.due_date < today ? 1 : 0
    if (aOverdue !== bOverdue) return bOverdue - aOverdue

    const pa = priorityOrder[a.priority] ?? 2
    const pb = priorityOrder[b.priority] ?? 2
    if (pa !== pb) return pa - pb

    if (a.due_date && b.due_date) return a.due_date.localeCompare(b.due_date)
    if (a.due_date) return -1
    if (b.due_date) return 1
    return 0
  })

  const completedToday = tasks.filter(
    (t) => t.assigned_to === user?.id && t.status === "completed" && t.updated_at?.startsWith(today)
  )

  const totalEstimated = sorted.reduce((sum, t) => sum + (t.estimated_minutes || 0), 0)
  const inProgressCount = sorted.filter((t) => t.status === "in_progress").length
  const overdueCount = sorted.filter((t) => t.due_date && t.due_date < today).length

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="text-sm text-muted-foreground">
          <span className="font-semibold text-foreground">{sorted.length}</span> tareas pendientes
        </div>
        {inProgressCount > 0 && (
          <div className="text-sm text-amber-600">
            <span className="font-semibold">{inProgressCount}</span> en curso
          </div>
        )}
        {overdueCount > 0 && (
          <div className="text-sm text-red-500">
            <span className="font-semibold">{overdueCount}</span> atrasadas
          </div>
        )}
        {totalEstimated > 0 && (
          <div className="text-sm text-muted-foreground flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" />
            ~{formatMinutes(totalEstimated)} estimado
          </div>
        )}
      </div>

      {/* Task list */}
      {sorted.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <CheckCircle2 className="h-10 w-10 mx-auto mb-3 text-green-400" />
            <p className="font-medium">¡Todo al día!</p>
            <p className="text-sm mt-1">No tienes tareas pendientes asignadas</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {sorted.map((task) => {
            const isOverdue = task.due_date && task.due_date < today
            const isInProgress = task.status === "in_progress"

            return (
              <Card
                key={task.id}
                className={cn(
                  "group hover:shadow-sm transition-all cursor-pointer",
                  isOverdue && "border-red-200 bg-red-50/30",
                  isInProgress && !isOverdue && "border-amber-200 bg-amber-50/30"
                )}
                onClick={() => onOpenEdit(task)}
              >
                <CardContent className="p-3 flex items-center gap-3">
                  {/* Status dropdown */}
                  <select
                    value={task.status}
                    onChange={(e) => {
                      e.stopPropagation()
                      onStatusChange(task.id, e.target.value as TaskStatus)
                    }}
                    onClick={(e) => e.stopPropagation()}
                    title="Cambiar estado"
                    className={cn(
                      "shrink-0 text-[10px] rounded-md border px-1.5 py-1 h-7 cursor-pointer font-medium transition-colors",
                      STATUS_CONFIG[task.status]?.cls ?? STATUS_CONFIG.pending.cls
                    )}
                  >
                    <option value="backlog">Backlog</option>
                    <option value="pending">Pendiente</option>
                    <option value="in_progress">En curso</option>
                    <option value="waiting">En espera</option>
                    <option value="in_review">En revisión</option>
                    <option value="completed">Completada</option>
                  </select>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium truncate inline-flex items-center gap-1">
                        {task.recurring_parent_id && <Repeat className="w-3 h-3 text-muted-foreground shrink-0" />}
                        {task.title}
                      </span>
                      {priorityBadge(task.priority)}
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-[11px] text-muted-foreground">
                      {task.client_name && <span>{task.client_name}</span>}
                      {task.estimated_minutes && (
                        <span className="flex items-center gap-0.5">
                          <Clock className="h-2.5 w-2.5" />{formatMinutes(task.estimated_minutes)}
                        </span>
                      )}
                      {task.due_date ? (
                        <span className={cn("flex items-center gap-0.5", isOverdue && "text-red-500 font-medium")}>
                          {isOverdue && <AlertTriangle className="h-2.5 w-2.5" />}
                          {new Date(task.due_date).toLocaleDateString("es-ES", { day: "numeric", month: "short" })}
                        </span>
                      ) : (
                        <span className="flex items-center gap-0.5 text-muted-foreground/60">
                          <CalendarX className="h-2.5 w-2.5" />
                          Sin fecha
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Edit */}
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                    onClick={(e) => { e.stopPropagation(); onOpenEdit(task) }}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* Completed today */}
      {completedToday.length > 0 && (
        <div className="mt-6">
          <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
            Completadas hoy ({completedToday.length})
          </p>
          <div className="space-y-1">
            {completedToday.map((task) => (
              <div key={task.id} className="flex items-center gap-2 py-1.5 px-2 rounded text-muted-foreground group/done">
                <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
                <span className="text-sm line-through truncate flex-1">{task.title}</span>
                {task.client_name && <span className="text-[10px] shrink-0">{task.client_name}</span>}
                <button
                  title="Reabrir tarea"
                  className="opacity-0 group-hover/done:opacity-100 transition-opacity shrink-0 text-muted-foreground hover:text-amber-600"
                  onClick={() => onStatusChange(task.id, "pending")}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
