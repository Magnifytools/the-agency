import { useState } from "react"
import {
  DndContext, KeyboardSensor, PointerSensor, TouchSensor, closestCenter, pointerWithin, useSensor, useSensors,
  type CollisionDetection, type DragEndEvent, type DragStartEvent,
} from "@dnd-kit/core"
import { SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy } from "@dnd-kit/sortable"
import { toast } from "sonner"
import type { PaginatedResponse, Task, TaskStatus } from "@/lib/types"
import { Card, CardContent } from "@/components/ui/card"
import { TimerButton } from "@/components/timer/timer-button"
import { Button } from "@/components/ui/button"
import { Pencil, Eye, CheckCircle2, Clock, AlertTriangle, CalendarX, RotateCcw, Repeat, CalendarClock } from "lucide-react"
import { InlineDate } from "@/components/ui/inline-edit"
import { TaskPriorityField, type TaskFieldUpdate } from "@/components/tasks/task-inline-fields"
import { formatMinutes } from "@/lib/inline-edit"
import { nextWorkdays, plannableFrom, sortAgendaTasks, sortFollowups } from "@/components/tasks/task-page-utils"
import { AgendaDropZone, DayStrip, DragHandle, SortableAgendaItem, type AgendaDropData, type AgendaSection, type DragHandleProps } from "@/components/tasks/agenda-dnd"
import { orderAfterDrop } from "@/lib/task-rank"
import { cn } from "@/lib/utils"
import { addCivilDays, agencyTimezoneLabel, businessDateString, formatCivilDate, parseApiInstant } from "@/lib/dates"
import { taskStatusPresentation, taskStatusSelectClass } from "@/lib/task-status"


interface Props {
  planned: PaginatedResponse<Task>
  carryover: PaginatedResponse<Task>
  unplanned: PaginatedResponse<Task>
  /** Esperas cuyo seguimiento ya toca y que no salen en otra sección. */
  followups?: PaginatedResponse<Task>
  completed: PaginatedResponse<Task>
  retired: PaginatedResponse<Task>
  isLoadingMore?: boolean
  onLoadMore: (section: "planned" | "carryover" | "unplanned" | "followups" | "completed" | "retired") => void
  onStatusChange: (id: number, status: TaskStatus) => void
  onOpenEdit: (task: Task, initialStatus?: TaskStatus) => void
  onReviewCarryover: (task: Task) => void
  retiredLoading?: boolean
  retiredError?: boolean
  onRetryRetired?: () => void
  canWrite?: boolean
  canCompleteReviewedTask?: (task: Task) => boolean
  /** Prioridad y "Mover a…" sin abrir la tarea. */
  onUpdate?: (task: Task, update: Parameters<TaskFieldUpdate>[0]) => void
  /** Arrastrar: la sección donde queda (en orden) y, si entra en hoy, el día. */
  onMove?: (task: Task, orderedIds: number[], scheduledDate?: string) => void
}

export function MyDayView({ planned, carryover, unplanned, followups = { items: [], total: 0, page: 1, page_size: 25 }, completed, retired, isLoadingMore, onLoadMore, onStatusChange, onOpenEdit, onReviewCarryover, retiredLoading = false, retiredError = false, onRetryRetired, canWrite = false, canCompleteReviewedTask = () => true, onUpdate, onMove }: Props) {
  const today = businessDateString()
  const [showRetired, setShowRetired] = useState(false)

  const sortTasks = (items: Task[]) => sortAgendaTasks(items, today)

  const plannedTodayTasks = sortTasks(planned.items)
  const carryoverTasks = sortTasks(carryover.items)
  const unplannedTasks = sortTasks(unplanned.items)
  const followupTasks = sortFollowups(followups.items)
  const completedToday = completed.items

  // Arrastrar (con el asa): ordenar cada sección, llevar a "Planificadas hoy"
  // desde arrastre o sin planificar, o soltar en un día de la tira.
  const canDrag = canWrite && !!onMove
  const [dragging, setDragging] = useState<Task | null>(null)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
  // Manda lo que hay bajo el puntero (una tarjeta antes que su sección); con
  // teclado, sin puntero, lo más cercano.
  const collision: CollisionDetection = (args) => {
    const hits = pointerWithin(args)
    if (!hits.length) return closestCenter(args)
    const cards = hits.filter((hit) => (args.droppableContainers.find((container) => container.id === hit.id)?.data.current as AgendaDropData | undefined)?.task)
    return cards.length ? cards : hits
  }
  const sections: Record<AgendaSection, Task[]> = { planned: plannedTodayTasks, carryover: carryoverTasks, unplanned: unplannedTasks }
  const days = nextWorkdays(today, 5)
  const notPlannable = () => toast.message("Tiene la fecha límite vencida: cámbiala con «Revisar» para sacarla del arrastre.")
  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    setDragging(null)
    const from = active.data.current as AgendaDropData | undefined
    const target = over?.data.current as AgendaDropData | undefined
    const task = from?.task
    if (!task || !from?.section || !target || !onMove) return
    if (target.day) {
      if (!plannableFrom(task, today)) return notPlannable()
      if (task.scheduled_date !== target.day) onUpdate?.(task, {
        data: { scheduled_date: target.day },
        success: `Planificada: ${formatCivilDate(target.day, { weekday: "short", day: "numeric", month: "short" })}`,
      })
      return
    }
    const section = target.section
    if (!section) return
    const overId = target.task && target.task.id !== task.id ? target.task.id : null
    if (section !== from.section) {
      // Entre secciones sólo se lleva a hoy; sacar de hoy es "Mover a…" o la tira.
      if (section !== "planned") return
      if (!plannableFrom(task, today)) return notPlannable()
      onMove(task, orderAfterDrop(sections.planned.map((item) => item.id), task.id, overId), today)
      return
    }
    const ids = sections[section].map((item) => item.id)
    const ordered = orderAfterDrop(ids, task.id, target.task ? target.task.id : null)
    if (ordered.some((id, index) => id !== ids[index])) onMove(task, ordered)
  }
  const sortable = (section: AgendaSection, items: Task[], carryover = false) => (
    <SortableContext id={section} items={items.map((task) => task.id)} strategy={verticalListSortingStrategy}>
      <div className="space-y-2">
        {items.map((task) => (
          <SortableAgendaItem key={task.id} task={task} section={section} disabled={!canDrag}>
            {(handle) => renderTaskCard(task, carryover, handle)}
          </SortableAgendaItem>
        ))}
      </div>
    </SortableContext>
  )

  const renderTaskCard = (task: Task, carryover = false, handle: DragHandleProps | null = null) => {
    const isOverdue = task.due_date && task.due_date < today
    const isInProgress = task.status === "in_progress"
    const sendsForReview = !!task.project_requires_task_review && !task.is_recurring && !canCompleteReviewedTask(task)
    const statusPresentation = taskStatusPresentation(task.status, task.scheduled_date)

    return (
      <Card
        key={task.id}
        data-task-row={task.id}
        className={cn(
          "group hover:shadow-sm transition-all cursor-pointer",
          isOverdue && "border-l-2 border-l-destructive",
          isInProgress && !isOverdue && "border-l-2 border-l-brand"
        )}
        onClick={() => onOpenEdit(task)}
      >
        <CardContent className="p-3 grid grid-cols-[minmax(0,1fr)_auto] gap-3 sm:flex sm:items-center">
          {canWrite ? <select
            value={statusPresentation.group}
            onChange={(e) => {
              e.stopPropagation()
              const next = e.target.value as TaskStatus
              if (next === "waiting") onOpenEdit(task, "waiting")
              else onStatusChange(task.id, next === "completed" && sendsForReview ? "in_review" : next)
            }}
            onClick={(e) => e.stopPropagation()}
            aria-label={`Estado de ${task.title}`}
            className={cn(
              "col-span-2 row-start-2 w-fit sm:w-auto shrink-0 text-xs sm:text-[10px] rounded-md border px-2 py-1 min-h-9 sm:min-h-7 cursor-pointer font-semibold transition-colors shadow-sm",
              "text-foreground",
              taskStatusSelectClass(task.status, task.scheduled_date)
            )}
          >
            <option value="pending">Pendiente</option>
            <option value="in_progress">En curso</option>
            <option value="waiting">En espera…</option>
            <option value="in_review">En revisión</option>
            <option value="completed">{sendsForReview ? "Enviar a revisión" : "Hecho"}</option>
          </select> : <span className="col-span-2 row-start-2 w-fit rounded-md border border-border bg-muted px-2 py-1 text-xs font-semibold text-muted-foreground sm:min-h-7 sm:text-[10px]">
            {statusPresentation.label}
          </span>}

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              {handle && <DragHandle handle={handle} title={task.title} />}
              <span className="min-w-0 text-sm font-medium whitespace-normal sm:truncate inline-flex items-center gap-1">
                {task.recurring_parent_id && <Repeat className="w-3 h-3 text-muted-foreground shrink-0" />}
                {task.title}
              </span>
              <TaskPriorityField task={task} canWrite={canWrite && !!onUpdate} onUpdate={(update) => onUpdate?.(task, update)} className="text-[10px]" />
            </div>
            <div className="flex items-center gap-3 mt-1 text-[11px] text-muted-foreground flex-wrap">
              {statusPresentation.detail && <span>{statusPresentation.detail}</span>}
              {task.client_name && <span>{task.client_name}</span>}
              {task.status === "waiting" && task.waiting_for && <span>Esperando a {task.waiting_for}</span>}
              {task.status === "waiting" && task.follow_up_date && (
                <span className={cn(task.follow_up_date < today && "text-red-500 font-medium")}>
                  Seguimiento {formatCivilDate(task.follow_up_date, { day: "numeric", month: "short" })}
                </span>
              )}
              {task.project_name && <span className="text-muted-foreground">· {task.project_name}</span>}
              {task.estimated_minutes && (
                <span className="flex items-center gap-0.5">
                  <Clock className="h-2.5 w-2.5" />{formatMinutes(task.estimated_minutes)}
                </span>
              )}
              {task.checklist_count > 0 && (
                <span className="flex items-center gap-0.5">
                  <CheckCircle2 className="h-2.5 w-2.5" />{task.checklist_count} subtarea{task.checklist_count !== 1 ? "s" : ""}
                </span>
              )}
              {task.scheduled_date ? (
                <span className="flex items-center gap-0.5">
                  <Clock className="h-2.5 w-2.5" />
                  Planificada {formatCivilDate(task.scheduled_date, { day: "numeric", month: "short" })}
                </span>
              ) : !task.due_date && (
                <span className="flex items-center gap-0.5 text-muted-foreground">
                  <CalendarX className="h-2.5 w-2.5" />
                  Sin fecha planificada
                </span>
              )}
              {task.due_date && (
                <span className={cn("flex items-center gap-0.5", isOverdue && "text-red-500 font-medium")}>
                  {isOverdue && <AlertTriangle className="h-2.5 w-2.5" />}
                  Fecha límite {formatCivilDate(task.due_date, { day: "numeric", month: "short" })}
                </span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
            {canWrite && task.status !== "completed" && <TimerButton taskId={task.id} taskTitle={task.title} />}
            {canWrite && onUpdate && task.status !== "completed" && (
              <InlineDate
                label={`Mover ${task.title} a otro día`}
                valueText={task.scheduled_date ? formatCivilDate(task.scheduled_date) : "sin planificar"}
                value={task.scheduled_date}
                today={today}
                clearLabel={task.scheduled_date === today ? "Quitar de hoy" : "Sin planificar"}
                onChange={(date) => onUpdate(task, {
                  data: { scheduled_date: date },
                  success: date ? `Planificada: ${formatCivilDate(date, { weekday: "short", day: "numeric", month: "short" })}` : "Sin planificar",
                })}
                className="mx-0 h-9 w-9 justify-center px-0 text-muted-foreground sm:h-7 sm:w-7"
              >
                <CalendarClock className="h-3.5 w-3.5" aria-hidden />
              </InlineDate>
            )}
            <Button
              variant="ghost"
              size="icon"
              aria-label={`${canWrite ? "Editar" : "Ver"} ${task.title}`}
              className="h-9 w-9 sm:h-7 sm:w-7 shrink-0 text-muted-foreground"
              onClick={() => onOpenEdit(task)}
            >
              {canWrite ? <Pencil className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </Button>
          </div>
          {carryover && canWrite && (
            <Button variant="outline" size="sm" className="col-span-2 sm:col-span-1" onClick={(event) => { event.stopPropagation(); onReviewCarryover(task) }}>
              Revisar
            </Button>
          )}
        </CardContent>
      </Card>
    )
  }

  return (
    <DndContext
      sensors={canDrag ? sensors : []}
      collisionDetection={collision}
      onDragStart={({ active }: DragStartEvent) => setDragging((active.data.current as AgendaDropData | undefined)?.task ?? null)}
      onDragEnd={handleDragEnd}
      onDragCancel={() => setDragging(null)}
      accessibility={{
        screenReaderInstructions: { draggable: "Con el asa: espacio para coger la tarea, flechas para moverla, espacio para soltarla y Escape para cancelar." },
        announcements: {
          onDragStart: () => "Moviendo tarea.",
          onDragOver: ({ over }) => {
            const target = over?.data.current as AgendaDropData | undefined
            if (target?.day) return `Sobre el ${formatCivilDate(target.day, { weekday: "long", day: "numeric" })}.`
            return target?.section === "planned" ? "Sobre Planificadas hoy." : "Sobre la lista."
          },
          onDragEnd: ({ over }) => over ? "Tarea soltada." : "Tarea devuelta a su sitio.",
          onDragCancel: () => "Movimiento cancelado.",
        },
      }}
    >
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">{agencyTimezoneLabel()}</p>
      {dragging && <DayStrip days={days} tomorrow={addCivilDays(today, 1)} />}
      {/* Tareas del día */}
      <div>
        <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
          Planificadas hoy ({planned.total})
        </p>
        <AgendaDropZone section="planned">
        {plannedTodayTasks.length === 0 ? (
          <Card>
            <CardContent className="py-4 flex items-center gap-3 text-muted-foreground">
              <CheckCircle2 className="h-5 w-5 shrink-0" />
              <p className="font-medium">{dragging ? "Suelta aquí para hacerla hoy" : "Sin tareas planificadas para hoy"}</p>
            </CardContent>
          </Card>
        ) : sortable("planned", plannedTodayTasks)}
        </AgendaDropZone>
        {planned.total > planned.items.length && (
          <Button variant="outline" className="mt-3" disabled={isLoadingMore} onClick={() => onLoadMore("planned")}>
            Ver más planificadas ({planned.total - planned.items.length} restantes)
          </Button>
        )}
      </div>

      {carryoverTasks.length > 0 && (
        <div className="mt-6">
          <p className="text-xs font-bold uppercase tracking-wider text-red-600 mb-2">Arrastre pendiente ({carryover.total})</p>
          <p className="text-sm text-muted-foreground mb-2">No son compromisos nuevos de hoy. Reprograma, deja en espera o completa cada una.</p>
          {sortable("carryover", carryoverTasks, true)}
          {carryover.total > carryover.items.length && (
            <Button variant="outline" className="mt-3" disabled={isLoadingMore} onClick={() => onLoadMore("carryover")}>
              Ver más de arrastre ({carryover.total - carryover.items.length} restantes)
            </Button>
          )}
        </div>
      )}

      {followupTasks.length > 0 && (
        <div className="mt-6">
          <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">Seguimientos ({followups.total})</p>
          <p className="mb-2 text-sm text-muted-foreground">Tareas en espera del cliente cuya fecha de seguimiento ya ha llegado.</p>
          <div className="space-y-2">{followupTasks.map((task) => renderTaskCard(task))}</div>
          {followups.total > followups.items.length && (
            <Button variant="outline" className="mt-3" disabled={isLoadingMore} onClick={() => onLoadMore("followups")}>
              Ver más seguimientos ({followups.total - followups.items.length} restantes)
            </Button>
          )}
        </div>
      )}

      {unplannedTasks.length > 0 && (
        <div className="mt-6">
          <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
            Sin planificar ({unplanned.total})
          </p>
          <p className="mb-2 text-sm text-muted-foreground">Tareas activas que todavía no tienen fecha planificada.</p>
          {sortable("unplanned", unplannedTasks)}
          {unplanned.total > unplanned.items.length && (
            <Button variant="outline" className="mt-3" disabled={isLoadingMore} onClick={() => onLoadMore("unplanned")}>
              Ver más sin planificar ({unplanned.total - unplanned.items.length} restantes)
            </Button>
          )}
        </div>
      )}

      {/* Completed today */}
      {completedToday.length > 0 && (
        <div className="mt-6">
          <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
            Completadas hoy ({completed.total})
          </p>
          <p className="mb-2 text-xs text-muted-foreground">Sólo aparecen tareas con fecha de finalización registrada para hoy.</p>
          <div className="space-y-1">
            {completedToday.map((task) => (
              <div key={task.id} className="flex items-center gap-2 py-1.5 px-2 rounded text-muted-foreground group/done">
                <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
                <span className="text-sm line-through truncate flex-1">{task.title}</span>
                {task.client_name && <span className="text-[10px] shrink-0">{task.client_name}</span>}
                {canWrite && <button
                  title="Reabrir tarea"
                  aria-label={`Reabrir ${task.title}`}
                  className="sm:opacity-0 group-hover/done:opacity-100 focus-visible:opacity-100 transition-opacity shrink-0 text-muted-foreground hover:text-amber-600"
                  onClick={() => onStatusChange(task.id, "pending")}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                </button>}
              </div>
            ))}
          </div>
          {completed.total > completed.items.length && (
            <Button variant="outline" className="mt-3" disabled={isLoadingMore} onClick={() => onLoadMore("completed")}>
              Ver más completadas ({completed.total - completed.items.length} restantes)
            </Button>
          )}
        </div>
      )}

      <div className="pt-2">
        <Button type="button" variant="ghost" size="sm" onClick={() => setShowRetired((value) => !value)}>
          {showRetired ? "Ocultar retiradas" : `Ver retiradas${retired.total ? ` (${retired.total})` : ""}`}
        </Button>
        {showRetired && (
          <div className="mt-2 space-y-2">
            {retiredLoading && retired.items.length === 0 ? <p role="status" className="text-sm text-muted-foreground">Cargando retiradas…</p> : retiredError && retired.items.length === 0 ? <div role="alert" className="text-sm text-destructive">No se pudieron cargar las retiradas. <Button type="button" size="sm" variant="outline" onClick={onRetryRetired}>Reintentar</Button></div> : retired.items.length === 0 ? <p className="text-sm text-muted-foreground">No hay tareas retiradas.</p> : retired.items.map((task) => (
              <Card key={task.id}>
                <CardContent className="p-0">
                  <button type="button" className="w-full rounded-[inherit] p-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand" onClick={() => onOpenEdit(task)}>
                    <p className="text-sm font-medium">{task.title}</p>
                    <p className="mt-1 text-xs text-muted-foreground">Retirada el {task.retired_at ? formatCivilDate(businessDateString(parseApiInstant(task.retired_at)), { day: "numeric", month: "short", year: "numeric" }) : "—"} · {task.retired_reason}</p>
                  </button>
                </CardContent>
              </Card>
            ))}
            {retiredError && retired.items.length > 0 && <div role="alert" className="text-sm text-warning">Mostramos retiradas guardadas; no se pudieron actualizar. <Button type="button" size="sm" variant="outline" onClick={onRetryRetired}>Reintentar</Button></div>}
            {retired.total > retired.items.length && <Button type="button" variant="outline" size="sm" disabled={isLoadingMore} onClick={() => onLoadMore("retired")}>Ver más retiradas ({retired.total - retired.items.length} restantes)</Button>}
          </div>
        )}
      </div>
    </div>
    </DndContext>
  )
}
