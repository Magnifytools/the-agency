import { useMemo, useState } from "react"
import {
  DndContext,
  DragOverlay,
  useDroppable,
  useDraggable,
  closestCenter,
  type DragEndEvent,
  type DragStartEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core"
import type { Task } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { ChevronLeft, ChevronRight, Pencil, Clock, Repeat } from "lucide-react"
import { cn } from "@/lib/utils"

interface Props {
  tasks: Task[]
  onScheduleChange: (taskId: number, date: string | null) => void
  onOpenEdit: (task: Task) => void
}

const DAY_NAMES = ["Lun", "Mar", "Mié", "Jue", "Vie"]

const priorityColors: Record<string, string> = {
  urgent: "border-l-red-500",
  high: "border-l-orange-400",
  medium: "border-l-blue-400",
  low: "border-l-slate-300",
}

function getWeekDates(offset: number): { dates: string[]; label: string } {
  const now = new Date()
  const day = now.getDay()
  // Monday = 1, Sunday = 0 → adjust so Monday is start
  const mondayOffset = day === 0 ? -6 : 1 - day
  const monday = new Date(now)
  monday.setDate(now.getDate() + mondayOffset + offset * 7)

  const dates: string[] = []
  for (let i = 0; i < 5; i++) {
    const d = new Date(monday)
    d.setDate(monday.getDate() + i)
    dates.push(d.toISOString().slice(0, 10))
  }

  const fri = new Date(monday)
  fri.setDate(monday.getDate() + 4)
  const label = `${monday.getDate()} ${monday.toLocaleDateString("es-ES", { month: "short" })} – ${fri.getDate()} ${fri.toLocaleDateString("es-ES", { month: "short", year: "numeric" })}`

  return { dates, label }
}

function formatDay(dateStr: string): string {
  const d = new Date(dateStr + "T00:00")
  return `${d.getDate()}`
}

// ─── Droppable Column ─────────────────────────────────────────
function DroppableColumn({
  id,
  label,
  sublabel,
  children,
  isToday,
}: {
  id: string
  label: string
  sublabel?: string
  children: React.ReactNode
  isToday?: boolean
}) {
  const { setNodeRef, isOver } = useDroppable({ id })
  return (
    <div
      ref={setNodeRef}
      className={cn(
        "flex flex-col min-h-[200px] rounded-lg border p-2 transition-colors",
        isOver ? "bg-primary/5 border-primary/40" : "bg-muted/20 border-border/60",
        isToday && "ring-2 ring-primary/30",
      )}
    >
      <div className="text-center mb-2">
        <div className={cn("text-sm font-medium", isToday && "text-primary")}>{label}</div>
        {sublabel && <div className="text-xs text-muted-foreground">{sublabel}</div>}
      </div>
      <div className="flex-1 space-y-1.5 min-h-[60px]">{children}</div>
    </div>
  )
}

// ─── Draggable Task Card ──────────────────────────────────────
function DraggableTaskCard({
  task,
  onOpenEdit,
}: {
  task: Task
  onOpenEdit: (task: Task) => void
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `task-${task.id}`,
    data: { task },
  })

  const style = transform
    ? { transform: `translate(${transform.x}px, ${transform.y}px)` }
    : undefined

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className={cn(
        "bg-background border rounded-md p-2 cursor-grab active:cursor-grabbing",
        "border-l-4 shadow-sm hover:shadow-md transition-shadow text-xs",
        priorityColors[task.priority] || "border-l-slate-300",
        isDragging && "opacity-50",
      )}
    >
      <div className="flex items-start justify-between gap-1">
        <span className="font-medium leading-tight line-clamp-2 flex-1 inline-flex items-center gap-1">
          {task.recurring_parent_id && <Repeat className="w-3 h-3 text-muted-foreground shrink-0" />}
          {task.title}
        </span>
        <button
          onClick={(e) => {
            e.stopPropagation()
            onOpenEdit(task)
          }}
          className="text-muted-foreground hover:text-foreground shrink-0 mt-0.5"
        >
          <Pencil className="w-3 h-3" />
        </button>
      </div>
      <div className="flex items-center gap-1.5 mt-1 text-muted-foreground">
        {task.client_name && (
          <span className="truncate max-w-[100px]">{task.client_name}</span>
        )}
        {task.estimated_minutes && (
          <span className="flex items-center gap-0.5 shrink-0">
            <Clock className="w-3 h-3" />
            {task.estimated_minutes}m
          </span>
        )}
      </div>
      {task.assigned_user_name && (
        <div className="text-muted-foreground mt-0.5 truncate">{task.assigned_user_name}</div>
      )}
    </div>
  )
}

// Overlay card for drag preview
function TaskCardOverlay({ task }: { task: Task }) {
  return (
    <div
      className={cn(
        "bg-background border rounded-md p-2 border-l-4 shadow-lg text-xs w-[200px]",
        priorityColors[task.priority] || "border-l-slate-300",
      )}
    >
      <span className="font-medium leading-tight line-clamp-2">{task.title}</span>
      {task.client_name && (
        <div className="text-muted-foreground mt-1 truncate">{task.client_name}</div>
      )}
    </div>
  )
}

// ─── Main Component ───────────────────────────────────────────
export function WeeklyPlannerView({ tasks, onScheduleChange, onOpenEdit }: Props) {
  const [weekOffset, setWeekOffset] = useState(0)
  const [activeTask, setActiveTask] = useState<Task | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  )

  const { dates, label } = useMemo(() => getWeekDates(weekOffset), [weekOffset])
  const today = new Date().toISOString().slice(0, 10)

  // Group tasks by scheduled_date
  const tasksByDate = useMemo(() => {
    const map: Record<string, Task[]> = {}
    for (const d of dates) map[d] = []
    map["unscheduled"] = []

    for (const task of tasks) {
      if (task.status === "completed") continue
      if (task.scheduled_date && map[task.scheduled_date]) {
        map[task.scheduled_date].push(task)
      } else if (!task.scheduled_date && (task.status === "pending" || task.status === "backlog")) {
        map["unscheduled"].push(task)
      }
    }
    return map
  }, [tasks, dates])

  const handleDragStart = (event: DragStartEvent) => {
    const task = (event.active.data.current as { task: Task })?.task
    if (task) setActiveTask(task)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveTask(null)
    const { active, over } = event
    if (!over) return

    const taskId = Number(String(active.id).replace("task-", ""))
    const targetId = String(over.id)

    let newDate: string | null = null
    if (targetId === "unscheduled") {
      newDate = null
    } else if (String(targetId).startsWith("day-")) {
      newDate = String(targetId).replace("day-", "")
    } else {
      return
    }

    // No-op if task is already in the target
    const task = tasks.find((t) => t.id === taskId)
    if (task) {
      const currentDate = task.scheduled_date || null
      if (currentDate === newDate) return
    }

    onScheduleChange(taskId, newDate)
  }

  return (
    <div className="space-y-4">
      {/* Week navigation */}
      <div className="flex items-center justify-between">
        <Button variant="outline" size="sm" onClick={() => setWeekOffset((o) => o - 1)}>
          <ChevronLeft className="w-4 h-4" />
        </Button>
        <div className="text-center">
          <span className="font-medium">{label}</span>
          {weekOffset !== 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="ml-2 text-xs"
              onClick={() => setWeekOffset(0)}
            >
              Hoy
            </Button>
          )}
        </div>
        <Button variant="outline" size="sm" onClick={() => setWeekOffset((o) => o + 1)}>
          <ChevronRight className="w-4 h-4" />
        </Button>
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        {/* Day columns */}
        <div className="grid grid-cols-5 gap-2">
          {dates.map((dateStr, i) => (
            <DroppableColumn
              key={dateStr}
              id={`day-${dateStr}`}
              label={DAY_NAMES[i]}
              sublabel={formatDay(dateStr)}
              isToday={dateStr === today}
            >
              {(tasksByDate[dateStr] || []).map((task) => (
                <DraggableTaskCard key={task.id} task={task} onOpenEdit={onOpenEdit} />
              ))}
            </DroppableColumn>
          ))}
        </div>

        {/* Unscheduled section */}
        <DroppableColumn id="unscheduled" label="Sin planificar">
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-1.5">
            {(tasksByDate["unscheduled"] || []).map((task) => (
              <DraggableTaskCard key={task.id} task={task} onOpenEdit={onOpenEdit} />
            ))}
          </div>
          {(tasksByDate["unscheduled"] || []).length === 0 && (
            <p className="text-xs text-muted-foreground text-center py-4">
              No hay tareas sin planificar
            </p>
          )}
        </DroppableColumn>

        <DragOverlay>
          {activeTask ? <TaskCardOverlay task={activeTask} /> : null}
        </DragOverlay>
      </DndContext>
    </div>
  )
}
