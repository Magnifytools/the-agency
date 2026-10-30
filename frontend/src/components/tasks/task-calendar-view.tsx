import { useMemo, useState } from "react"
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  TouchSensor,
  pointerWithin,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core"
import { Button } from "@/components/ui/button"
import { ChevronLeft, ChevronRight } from "lucide-react"
import type { Task } from "@/lib/types"
import { cn } from "@/lib/utils"
import { parseCivilDate } from "@/lib/dates"
import { useBusinessDate } from "@/hooks/use-business-date"

const DAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
const MONTHS = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
const VISIBLE_PER_DAY = 3

const STATUS_COLORS: Record<string, string> = {
  backlog: "bg-gray-500 text-white",
  pending: "bg-yellow-500 text-white",
  in_progress: "bg-blue-500 text-white",
  waiting: "bg-orange-500 text-white",
  in_review: "bg-purple-500 text-white",
  advanced: "bg-teal-500 text-white",
  completed: "bg-green-500 text-white line-through opacity-60",
}

interface TaskCalendarViewProps {
  tasks: Task[]
  year: number
  month: number
  onPrev: () => void
  onNext: () => void
  onToday?: () => void
  onOpenEdit: (task: Task) => void
  /** Soltar una tarea en otro día cambia su fecha límite. Sin él, no se arrastra. */
  onDueDateChange?: (taskId: number, date: string) => void
}

const civilDate = (year: number, month: number, day: number) =>
  `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`

function DayCell({ date, children, className }: { date: string | null; children?: React.ReactNode; className?: string }) {
  const { setNodeRef, isOver } = useDroppable({ id: `day-${date ?? "none"}`, data: { date }, disabled: !date })
  return (
    <div ref={setNodeRef} className={cn("min-h-[90px] bg-background p-1.5 transition-colors", !date && "bg-muted/20", isOver && "bg-brand/10 ring-2 ring-inset ring-brand", className)}>
      {children}
    </div>
  )
}

function CalendarTask({ task, draggable, onOpenEdit }: { task: Task; draggable: boolean; onOpenEdit: (task: Task) => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: `task-${task.id}`, data: { task }, disabled: !draggable })
  return (
    <button
      ref={setNodeRef}
      type="button"
      {...(draggable ? attributes : {})}
      {...(draggable ? listeners : {})}
      onClick={() => onOpenEdit(task)}
      title={task.title}
      className={cn(
        "w-full text-left text-[10px] rounded px-1 py-0.5 truncate leading-tight hover:opacity-80 transition-opacity touch-manipulation",
        STATUS_COLORS[task.status] || "bg-secondary",
        draggable && "cursor-grab active:cursor-grabbing",
        isDragging && "opacity-30",
      )}
    >
      {task.title}
    </button>
  )
}

export function TaskCalendarView({ tasks, year, month, onPrev, onNext, onToday, onOpenEdit, onDueDateChange }: TaskCalendarViewProps) {
  const [expandedDays, setExpandedDays] = useState<Set<number>>(new Set())
  const [activeTask, setActiveTask] = useState<Task | null>(null)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 5 } }),
  )
  const days = useMemo(() => {
    const firstDay = new Date(year, month, 1)
    // Monday-based: 0=Mon ... 6=Sun
    const startOffset = (firstDay.getDay() + 6) % 7
    const daysInMonth = new Date(year, month + 1, 0).getDate()
    const cells: (number | null)[] = []
    for (let i = 0; i < startOffset; i++) cells.push(null)
    for (let d = 1; d <= daysInMonth; d++) cells.push(d)
    // Pad to complete last row
    while (cells.length % 7 !== 0) cells.push(null)
    return cells
  }, [year, month])

  const tasksByDay = useMemo(() => {
    const map: Record<number, Task[]> = {}
    for (const t of tasks) {
      if (!t.due_date) continue
      const d = parseCivilDate(t.due_date)
      if (d.getFullYear() === year && d.getMonth() === month) {
        const day = d.getDate()
        if (!map[day]) map[day] = []
        map[day].push(t)
      }
    }
    return map
  }, [tasks, year, month])

  const today = parseCivilDate(useBusinessDate())
  const isToday = (d: number) => today.getFullYear() === year && today.getMonth() === month && today.getDate() === d
  const isCurrentMonth = today.getFullYear() === year && today.getMonth() === month
  const canDrag = !!onDueDateChange

  const handleDragStart = (event: DragStartEvent) => {
    const task = (event.active.data.current as { task?: Task } | undefined)?.task
    if (task) setActiveTask(task)
  }
  const handleDragEnd = (event: DragEndEvent) => {
    setActiveTask(null)
    const task = (event.active.data.current as { task?: Task } | undefined)?.task
    const date = (event.over?.data.current as { date?: string | null } | undefined)?.date
    if (!task || !date || task.due_date?.slice(0, 10) === date) return
    onDueDateChange?.(task.id, date)
  }
  const toggleDay = (day: number) => setExpandedDays((previous) => {
    const next = new Set(previous)
    if (next.has(day)) next.delete(day)
    else next.add(day)
    return next
  })

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-lg font-semibold">{MONTHS[month]} {year}</h3>
        <div className="flex gap-1">
          {onToday && !isCurrentMonth && <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={onToday}>Hoy</Button>}
          <Button variant="outline" size="icon" aria-label="Mes anterior" className="h-8 w-8" onClick={onPrev}><ChevronLeft className="h-4 w-4" /></Button>
          <Button variant="outline" size="icon" aria-label="Mes siguiente" className="h-8 w-8" onClick={onNext}><ChevronRight className="h-4 w-4" /></Button>
        </div>
      </div>
      {canDrag && <p className="text-xs text-muted-foreground">Arrastra una tarea a otro día para cambiar su fecha límite.</p>}

      <DndContext
        sensors={canDrag ? sensors : []}
        collisionDetection={pointerWithin}
        onDragStart={canDrag ? handleDragStart : undefined}
        onDragEnd={canDrag ? handleDragEnd : undefined}
        onDragCancel={() => setActiveTask(null)}
      >
        <div className="overflow-x-auto">
          <div className="grid grid-cols-7 gap-px bg-border rounded-lg overflow-hidden border border-border min-w-[560px]">
            {/* Day headers */}
            {DAYS.map(d => (
              <div key={d} className="bg-muted/50 text-center text-xs font-medium text-muted-foreground py-2">{d}</div>
            ))}

            {/* Cells */}
            {days.map((d, i) => {
              const dayTasks = d ? tasksByDay[d] || [] : []
              const expanded = d !== null && expandedDays.has(d)
              const shown = expanded ? dayTasks : dayTasks.slice(0, VISIBLE_PER_DAY)
              return (
                <DayCell key={i} date={d ? civilDate(year, month, d) : null}>
                  {d && (
                    <>
                      <span className={`text-xs font-medium mb-1 block w-5 h-5 flex items-center justify-center rounded-full ${isToday(d) ? "bg-brand text-primary-foreground" : "text-muted-foreground"}`}>
                        {d}
                      </span>
                      <div className="space-y-0.5">
                        {shown.map(t => (
                          <CalendarTask key={t.id} task={t} draggable={canDrag && t.status !== "completed"} onOpenEdit={onOpenEdit} />
                        ))}
                        {dayTasks.length > VISIBLE_PER_DAY && (
                          <button
                            type="button"
                            className="text-[10px] text-muted-foreground pl-1 hover:text-foreground hover:underline"
                            aria-expanded={expanded}
                            onClick={() => toggleDay(d)}
                          >
                            {expanded ? "Ver menos" : `+${dayTasks.length - VISIBLE_PER_DAY} más`}
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </DayCell>
              )
            })}
          </div>
        </div>
        <DragOverlay dropAnimation={null}>
          {activeTask ? (
            <div className={cn("text-[11px] rounded px-2 py-1 shadow-lg max-w-[180px] truncate", STATUS_COLORS[activeTask.status] || "bg-secondary")}>
              {activeTask.title}
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>

      {/* Empty state when no tasks have a due_date in this month */}
      {Object.keys(tasksByDay).length === 0 && (
        <p className="text-center text-sm text-muted-foreground py-4">
          No hay tareas con fecha en {MONTHS[month]}. Asigna una fecha de entrega a tus tareas para verlas aquí.
        </p>
      )}
    </div>
  )
}
