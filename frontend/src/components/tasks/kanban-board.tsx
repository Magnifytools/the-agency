import { useState } from "react"
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  TouchSensor,
  pointerWithin,
  rectIntersection,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core"
import type { Task, TaskStatus } from "@/lib/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Pencil, Eye, Clock, AlertTriangle, User, GripVertical, UserX, CalendarX, Repeat, ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { businessDateString, formatCivilDate } from "@/lib/dates"
import { taskStatusPresentation, type TaskStatusGroup } from "@/lib/task-status"
import { boardDrop } from "./board-drop"

interface Props {
  tasks: Task[]
  onStatusChange: (taskId: number, newStatus: TaskStatus) => void
  onOpenEdit: (task: Task, initialStatus?: TaskStatus) => void
  canWrite?: boolean
  /** Columna "Hecho" con lo completado recientemente (plegada al empezar). */
  showCompleted?: boolean
  completedHint?: string
}

const columns: Array<{ status: TaskStatusGroup; label: string; color: string; bgColor: string }> = [
  { status: "pending", label: "Pendiente", color: "text-yellow-400", bgColor: "bg-yellow-950/60 border-yellow-700" },
  { status: "in_progress", label: "En curso", color: "text-blue-400", bgColor: "bg-blue-950/60 border-blue-700" },
  { status: "waiting", label: "En espera", color: "text-orange-400", bgColor: "bg-orange-950/60 border-orange-700" },
  { status: "in_review", label: "En revisión", color: "text-purple-400", bgColor: "bg-purple-950/60 border-purple-700" },
  { status: "completed", label: "Hecho", color: "text-emerald-400", bgColor: "bg-emerald-950/50 border-emerald-800" },
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

// Con el puntero manda la columna que hay debajo; sin él (táctil a medio
// arrastre), la que más se solapa con la tarjeta.
const collision: CollisionDetection = (args) => {
  const hits = pointerWithin(args)
  return hits.length ? hits : rectIntersection(args)
}

function BoardColumn({ status, label, color, bgColor, count, collapsed, onToggle, hint, children }: {
  status: TaskStatusGroup
  label: string
  color: string
  bgColor: string
  count: number
  collapsed?: boolean
  onToggle?: () => void
  hint?: string
  children: React.ReactNode
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `column-${status}`, data: { status } })
  return (
    <section
      ref={setNodeRef}
      aria-label={`Columna ${label}`}
      className={cn(
        "rounded-xl border p-3 transition-all",
        collapsed ? "min-h-0" : "min-h-[300px]",
        bgColor,
        isOver && "ring-2 ring-brand ring-offset-2",
      )}
    >
      <div className="flex items-center justify-between mb-3 px-1 gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={cn("text-sm font-bold uppercase tracking-wider", color)}>{label}</span>
          <Badge variant="outline" className="text-[10px] h-5 px-1.5">{count}</Badge>
        </div>
        {onToggle && (
          <Button variant="ghost" size="sm" className="h-6 px-1.5 text-xs" onClick={onToggle} aria-expanded={!collapsed}>
            {collapsed ? "Mostrar" : "Ocultar"}
            <ChevronDown className={cn("h-3 w-3 ml-1 transition-transform", !collapsed && "rotate-180")} />
          </Button>
        )}
      </div>
      {hint && <p className="-mt-2 mb-3 px-1 text-[10px] text-muted-foreground">{hint}</p>}
      {collapsed ? (
        <div className={cn(
          "text-center py-3 text-xs text-muted-foreground border-2 border-dashed rounded-lg",
          isOver ? "border-brand bg-brand/5 text-brand" : "border-transparent",
        )}>
          {isOver ? "Soltar aquí" : "Arrastra aquí para cerrarla"}
        </div>
      ) : (
        <div className="space-y-2">
          {children}
          {count === 0 && (
            <div className={cn(
              "text-center py-8 text-xs text-muted-foreground border-2 border-dashed rounded-lg transition-colors",
              isOver ? "border-brand bg-brand/5 text-brand" : "border-transparent",
            )}>
              {isOver ? "Soltar aquí" : "Sin tareas"}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

function TaskCardBody({ task, canWrite, onOpenEdit, todayStr }: {
  task: Task
  canWrite: boolean
  onOpenEdit?: (task: Task) => void
  todayStr: string
}) {
  const isCompleted = task.status === "completed"
  const isOverdue = task.due_date && task.due_date < todayStr && !isCompleted
  const isUnassigned = !task.assigned_to && !isCompleted
  const noDate = !task.due_date && !isCompleted
  const detail = taskStatusPresentation(task.status, task.scheduled_date).detail
  // Enter en un botón de la tarjeta no debe llegar al arrastre de la tarjeta.
  const stopKeys = (event: React.KeyboardEvent) => event.stopPropagation()

  return (
    <CardContent className="p-3">
      <div className="flex items-start gap-2">
        {canWrite && <GripVertical className="h-4 w-4 text-muted-foreground/40 mt-0.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-1">
            <div className={cn("h-2 w-2 rounded-full shrink-0", priorityColors[task.priority] || "bg-slate-300")} />
            <span className="text-xs text-muted-foreground">{priorityLabels[task.priority] || task.priority}</span>
          </div>
          <button
            type="button"
            onClick={() => onOpenEdit?.(task)}
            onKeyDown={stopKeys}
            className={cn(
              "text-sm font-medium leading-snug line-clamp-2 inline-flex items-center gap-1 text-left hover:underline rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand",
              isCompleted && "line-through text-muted-foreground",
            )}
          >
            {task.recurring_parent_id && <Repeat className="w-3 h-3 text-muted-foreground shrink-0" />}
            {task.title}
          </button>
          {detail && <p className="text-[10px] text-muted-foreground">{detail}</p>}
        </div>
        {onOpenEdit && (
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity shrink-0"
            onClick={() => onOpenEdit(task)}
            onKeyDown={stopKeys}
            aria-label={`${canWrite ? "Editar" : "Ver"} tarea ${task.title}`}
          >
            {canWrite ? <Pencil className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
          </Button>
        )}
      </div>

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
            {formatCivilDate(task.due_date, { day: "numeric", month: "short" })}
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
  )
}

function DraggableTaskCard({ task, canWrite, onOpenEdit, todayStr }: {
  task: Task
  canWrite: boolean
  onOpenEdit: (task: Task) => void
  todayStr: string
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `task-${task.id}`,
    data: { task },
    disabled: !canWrite,
  })
  const isOverdue = task.due_date && task.due_date < todayStr && task.status !== "completed"

  return (
    <Card
      ref={setNodeRef}
      {...(canWrite ? attributes : {})}
      {...(canWrite ? listeners : {})}
      data-task-card={task.id}
      className={cn(
        "hover:shadow-md transition-all group border touch-manipulation",
        canWrite && "cursor-grab active:cursor-grabbing",
        isDragging && "opacity-40",
        isOverdue && "border-red-300 bg-red-50/50 text-black [&_.text-muted-foreground]:text-black/60",
      )}
    >
      <TaskCardBody task={task} canWrite={canWrite} onOpenEdit={onOpenEdit} todayStr={todayStr} />
    </Card>
  )
}

export function KanbanBoard({ tasks, onStatusChange, onOpenEdit, canWrite = true, showCompleted = false, completedHint }: Props) {
  const [activeTask, setActiveTask] = useState<Task | null>(null)
  const [completedCollapsed, setCompletedCollapsed] = useState(true)
  const todayStr = businessDateString()
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 5 } }),
  )
  const visibleColumns = showCompleted ? columns : columns.filter((column) => column.status !== "completed")

  const handleDragStart = (event: DragStartEvent) => {
    const task = (event.active.data.current as { task?: Task } | undefined)?.task
    if (task) setActiveTask(task)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveTask(null)
    const task = (event.active.data.current as { task?: Task } | undefined)?.task
    const target = (event.over?.data.current as { status?: TaskStatusGroup } | undefined)?.status
    if (!task || !target) return
    const drop = boardDrop(task, target)
    if (drop.kind === "waiting") {
      onOpenEdit(task, "waiting")
      toast.message("Completa Respuesta pendiente, responsable y fecha para poner la tarea en espera.")
    } else if (drop.kind === "status") {
      onStatusChange(task.id, drop.status)
    }
  }

  return (
    <DndContext
      sensors={canWrite ? sensors : []}
      collisionDetection={collision}
      onDragStart={canWrite ? handleDragStart : undefined}
      onDragEnd={canWrite ? handleDragEnd : undefined}
      onDragCancel={() => setActiveTask(null)}
      accessibility={{
        screenReaderInstructions: { draggable: "Mantén pulsado y arrastra la tarea a otra columna para cambiar su estado." },
        announcements: {
          onDragStart: () => "Moviendo tarea.",
          onDragOver: ({ over }) => {
            const status = (over?.data.current as { status?: TaskStatusGroup } | undefined)?.status
            const label = columns.find((column) => column.status === status)?.label
            return label ? `Sobre la columna ${label}.` : "Fuera de las columnas."
          },
          onDragEnd: ({ over }) => over ? "Tarea soltada." : "Tarea devuelta a su sitio.",
          onDragCancel: () => "Movimiento cancelado.",
        },
      }}
    >
      <div className={cn("grid grid-cols-1 md:grid-cols-2 gap-4", showCompleted ? "xl:grid-cols-5" : "xl:grid-cols-4")}>
        {visibleColumns.map((col) => {
          const colTasks = tasks.filter((t) => taskStatusPresentation(t.status, t.scheduled_date).group === col.status)
          const isCompletedColumn = col.status === "completed"
          return (
            <BoardColumn
              key={col.status}
              {...col}
              count={colTasks.length}
              collapsed={isCompletedColumn && completedCollapsed}
              onToggle={isCompletedColumn ? () => setCompletedCollapsed((value) => !value) : undefined}
              hint={isCompletedColumn ? completedHint : undefined}
            >
              {colTasks.map((task) => (
                <DraggableTaskCard key={task.id} task={task} canWrite={canWrite} onOpenEdit={onOpenEdit} todayStr={todayStr} />
              ))}
            </BoardColumn>
          )
        })}
      </div>
      <DragOverlay dropAnimation={null}>
        {activeTask ? (
          <Card className="shadow-lg border rotate-1 w-[260px]">
            <TaskCardBody task={activeTask} canWrite todayStr={todayStr} />
          </Card>
        ) : null}
      </DragOverlay>
    </DndContext>
  )
}
