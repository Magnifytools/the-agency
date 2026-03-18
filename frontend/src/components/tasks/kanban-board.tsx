import { useRef, useState } from "react"
import type { Task, TaskStatus } from "@/lib/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Pencil, Clock, AlertTriangle, User, GripVertical, UserX, CalendarX, Repeat } from "lucide-react"
import { cn } from "@/lib/utils"

interface Props {
  tasks: Task[]
  onStatusChange: (taskId: number, newStatus: TaskStatus) => void
  onOpenEdit: (task: Task) => void
}

const columns: { status: TaskStatus; label: string; color: string; bgColor: string }[] = [
  { status: "in_review", label: "En revisión", color: "text-blue-400", bgColor: "bg-blue-950/60 border-blue-700" },
  { status: "waiting", label: "En espera", color: "text-purple-400", bgColor: "bg-purple-950/60 border-purple-700" },
  { status: "in_progress", label: "En curso", color: "text-amber-400", bgColor: "bg-amber-950/60 border-amber-700" },
  { status: "pending", label: "Pendiente", color: "text-yellow-400", bgColor: "bg-yellow-950/60 border-yellow-700" },
  { status: "backlog", label: "Backlog", color: "text-slate-400", bgColor: "bg-slate-900/60 border-slate-700" },
]

const priorityColors: Record<string, string> = {
  urgent: "bg-red-500",
  high: "bg-orange-400",
  medium: "bg-blue-400",
  low: "bg-slate-300",
}

const priorityLabels: Record<string, string> = {
  urgent: "Urgente",
  high: "Alta",
  medium: "Media",
  low: "Baja",
}

const formatMinutes = (mins: number) => {
  if (mins < 60) return `${mins}m`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

export function KanbanBoard({ tasks, onStatusChange, onOpenEdit }: Props) {
  const dragTaskRef = useRef<Task | null>(null)
  const [dragOverColumn, setDragOverColumn] = useState<TaskStatus | null>(null)

  const handleDragStart = (e: React.DragEvent, task: Task) => {
    dragTaskRef.current = task
    e.dataTransfer.effectAllowed = "move"
    // Make ghost semi-transparent
    if (e.currentTarget instanceof HTMLElement) {
      e.currentTarget.style.opacity = "0.5"
    }
  }

  const handleDragEnd = (e: React.DragEvent) => {
    if (e.currentTarget instanceof HTMLElement) {
      e.currentTarget.style.opacity = "1"
    }
    setDragOverColumn(null)
    dragTaskRef.current = null
  }

  const handleDragOver = (e: React.DragEvent, status: TaskStatus) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = "move"
    setDragOverColumn(status)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    // Only clear if leaving the column (not entering a child)
    const relatedTarget = e.relatedTarget as HTMLElement | null
    if (!relatedTarget || !e.currentTarget.contains(relatedTarget)) {
      setDragOverColumn(null)
    }
  }

  const handleDrop = (e: React.DragEvent, newStatus: TaskStatus) => {
    e.preventDefault()
    setDragOverColumn(null)
    const task = dragTaskRef.current
    if (task && task.status !== newStatus) {
      onStatusChange(task.id, newStatus)
    }
    dragTaskRef.current = null
  }

  const todayStr = new Date().toISOString().slice(0, 10)

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {columns.map((col) => {
        const colTasks = tasks.filter((t) => t.status === col.status)
        const isDragOver = dragOverColumn === col.status

        return (
          <div
            key={col.status}
            className={cn(
              "rounded-xl border p-3 min-h-[300px] transition-all",
              col.bgColor,
              isDragOver && "ring-2 ring-brand ring-offset-2 scale-[1.01]"
            )}
            onDragOver={(e) => handleDragOver(e, col.status)}
            onDragLeave={handleDragLeave}
            onDrop={(e) => handleDrop(e, col.status)}
          >
            {/* Column header */}
            <div className="flex items-center justify-between mb-3 px-1">
              <div className="flex items-center gap-2">
                <span className={cn("text-sm font-bold uppercase tracking-wider", col.color)}>
                  {col.label}
                </span>
                <Badge variant="outline" className="text-[10px] h-5 px-1.5">
                  {colTasks.length}
                </Badge>
              </div>
            </div>

            {/* Task cards */}
            <div className="space-y-2">
              {colTasks.map((task) => {
                const isOverdue = task.due_date && task.due_date < todayStr && task.status !== "completed"
                const isUnassigned = !task.assigned_to && task.status !== "completed"
                const noDate = !task.due_date && task.status !== "completed"

                return (
                  <Card
                    key={task.id}
                    draggable
                    onDragStart={(e) => handleDragStart(e, task)}
                    onDragEnd={handleDragEnd}
                    className={cn(
                      "cursor-grab active:cursor-grabbing hover:shadow-md transition-all group border",
                      isOverdue && "border-red-300 bg-red-50/50"
                    )}
                  >
                    <CardContent className="p-3">
                      {/* Priority indicator + title */}
                      <div className="flex items-start gap-2">
                        <GripVertical className="h-4 w-4 text-muted-foreground/40 mt-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5 mb-1">
                            <div className={cn("h-2 w-2 rounded-full shrink-0", priorityColors[task.priority] || "bg-slate-300")} />
                            <span className="text-xs text-muted-foreground">{priorityLabels[task.priority] || task.priority}</span>
                          </div>
                          <p className="text-sm font-medium leading-snug line-clamp-2 inline-flex items-center gap-1">
                            {task.recurring_parent_id && <Repeat className="w-3 h-3 text-muted-foreground shrink-0" />}
                            {task.title}
                          </p>
                        </div>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                          onClick={() => onOpenEdit(task)}
                        >
                          <Pencil className="h-3 w-3" />
                        </Button>
                      </div>

                      {/* Meta row */}
                      <div className="flex items-center gap-2 mt-2 flex-wrap">
                        {task.client_name && (
                          <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded truncate max-w-[120px]">
                            {task.client_name}
                          </span>
                        )}
                        {task.estimated_minutes && (
                          <span className="text-[10px] text-muted-foreground flex items-center gap-0.5">
                            <Clock className="h-2.5 w-2.5" />
                            {formatMinutes(task.estimated_minutes)}
                          </span>
                        )}
                        {task.assigned_user_name && (
                          <span className="text-[10px] text-muted-foreground flex items-center gap-0.5">
                            <User className="h-2.5 w-2.5" />
                            {task.assigned_user_name.split(" ")[0]}
                          </span>
                        )}
                        {isOverdue && (
                          <span className="text-[10px] text-red-500 flex items-center gap-0.5 font-medium">
                            <AlertTriangle className="h-2.5 w-2.5" />
                            Atrasada
                          </span>
                        )}
                        {task.due_date && !isOverdue && (
                          <span className="text-[10px] text-muted-foreground">
                            {new Date(task.due_date).toLocaleDateString("es-ES", { day: "numeric", month: "short" })}
                          </span>
                        )}
                        {isUnassigned && (
                          <span className="text-[10px] text-orange-500 flex items-center gap-0.5 font-medium">
                            <UserX className="h-2.5 w-2.5" />
                            Sin responsable
                          </span>
                        )}
                        {noDate && (
                          <span className="text-[10px] text-muted-foreground/70 flex items-center gap-0.5">
                            <CalendarX className="h-2.5 w-2.5" />
                            Sin fecha
                          </span>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                )
              })}

              {colTasks.length === 0 && (
                <div className={cn(
                  "text-center py-8 text-xs text-muted-foreground border-2 border-dashed rounded-lg transition-colors",
                  isDragOver ? "border-brand bg-brand/5 text-brand" : "border-transparent"
                )}>
                  {isDragOver ? "Soltar aquí" : "Sin tareas"}
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
