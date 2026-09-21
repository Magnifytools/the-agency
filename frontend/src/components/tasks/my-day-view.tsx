import { useState } from "react"
import type { PaginatedResponse, Task, TaskStatus } from "@/lib/types"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Pencil, CheckCircle2, Clock, AlertTriangle, CalendarX, RotateCcw, Repeat } from "lucide-react"
import { cn } from "@/lib/utils"
import { agencyTimezoneLabel, businessDateString, formatCivilDate, parseApiInstant } from "@/lib/dates"
import { taskStatusPresentation } from "@/lib/task-status"


interface Props {
  planned: PaginatedResponse<Task>
  carryover: PaginatedResponse<Task>
  unplanned: PaginatedResponse<Task>
  completed: PaginatedResponse<Task>
  retired: PaginatedResponse<Task>
  isLoadingMore?: boolean
  onLoadMore: (section: "planned" | "carryover" | "unplanned" | "completed" | "retired") => void
  onStatusChange: (id: number, status: TaskStatus) => void
  onOpenEdit: (task: Task, initialStatus?: TaskStatus) => void
  onReviewCarryover: (task: Task) => void
  retiredLoading?: boolean
  retiredError?: boolean
  onRetryRetired?: () => void
  canWrite?: boolean
  canCompleteReviewedTask?: (task: Task) => boolean
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

export function MyDayView({ planned, carryover, unplanned, completed, retired, isLoadingMore, onLoadMore, onStatusChange, onOpenEdit, onReviewCarryover, retiredLoading = false, retiredError = false, onRetryRetired, canWrite = false, canCompleteReviewedTask = () => true }: Props) {
  const today = businessDateString()
  const [showRetired, setShowRetired] = useState(false)

  const sortTasks = (items: Task[]) => [...items].sort((a, b) => {
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

  const plannedTodayTasks = sortTasks(planned.items)
  const carryoverTasks = sortTasks(carryover.items)
  const unplannedTasks = sortTasks(unplanned.items)
  const completedToday = completed.items

  const renderTaskCard = (task: Task, carryover = false) => {
    const isOverdue = task.due_date && task.due_date < today
    const isInProgress = task.status === "in_progress"
    const sendsForReview = !!task.project_requires_task_review && !task.is_recurring && !canCompleteReviewedTask(task)

    return (
      <Card
        key={task.id}
        className={cn(
          "group hover:shadow-sm transition-all cursor-pointer",
          isOverdue && "border-l-2 border-l-destructive",
          isInProgress && !isOverdue && "border-l-2 border-l-brand"
        )}
        onClick={() => onOpenEdit(task)}
      >
        <CardContent className="p-3 grid grid-cols-[minmax(0,1fr)_auto] gap-3 sm:flex sm:items-center">
          <select
            value={taskStatusPresentation(task.status, task.scheduled_date).group}
            onChange={(e) => {
              e.stopPropagation()
              const next = e.target.value as TaskStatus
              if (next === "waiting") onOpenEdit(task, "waiting")
              else onStatusChange(task.id, next === "completed" && sendsForReview ? "in_review" : next)
            }}
            onClick={(e) => e.stopPropagation()}
            aria-label={`Estado de ${task.title}`}
            disabled={!canWrite}
            className={cn(
              "col-span-2 row-start-2 w-fit sm:w-auto shrink-0 text-xs sm:text-[10px] rounded-md border px-2 py-1 min-h-9 sm:min-h-7 cursor-pointer font-semibold transition-colors shadow-sm",
              "bg-background text-foreground border-input"
            )}
          >
            <option value="pending">Pendiente</option>
            <option value="in_progress">En curso</option>
            <option value="waiting">En espera…</option>
            <option value="in_review">En revisión</option>
            <option value="completed">{sendsForReview ? "Enviar a revisión" : "Hecho"}</option>
          </select>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="min-w-0 text-sm font-medium whitespace-normal sm:truncate inline-flex items-center gap-1">
                {task.recurring_parent_id && <Repeat className="w-3 h-3 text-muted-foreground shrink-0" />}
                {task.title}
              </span>
              {priorityBadge(task.priority)}
            </div>
            <div className="flex items-center gap-3 mt-1 text-[11px] text-muted-foreground flex-wrap">
              {taskStatusPresentation(task.status, task.scheduled_date).detail && <span>{taskStatusPresentation(task.status, task.scheduled_date).detail}</span>}
              {task.client_name && <span>{task.client_name}</span>}
              {task.project_name && <span className="text-muted-foreground">· {task.project_name}</span>}
              {task.estimated_minutes && (
                <span className="flex items-center gap-0.5">
                  <Clock className="h-2.5 w-2.5" />{formatMinutes(task.estimated_minutes)}
                </span>
              )}
              {task.checklist_count > 0 && (
                <span className="flex items-center gap-0.5">
                  <CheckCircle2 className="h-2.5 w-2.5" />{task.checklist_count} subtask{task.checklist_count !== 1 ? "s" : ""}
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

          <Button
            variant="ghost"
            size="icon"
            aria-label={`Editar ${task.title}`}
            className="h-9 w-9 sm:h-7 sm:w-7 sm:opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity shrink-0"
            onClick={(e) => { e.stopPropagation(); onOpenEdit(task) }}
          >
            <Pencil className="h-3.5 w-3.5" />
          </Button>
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
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">{agencyTimezoneLabel()}</p>
      {/* Tareas del día */}
      <div>
        <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
          Planificadas hoy ({planned.total})
        </p>
        {plannedTodayTasks.length === 0 ? (
          <Card>
            <CardContent className="py-4 flex items-center gap-3 text-muted-foreground">
              <CheckCircle2 className="h-5 w-5 shrink-0" />
              <p className="font-medium">Sin tareas planificadas para hoy</p>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">{plannedTodayTasks.map((task) => renderTaskCard(task))}</div>
        )}
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
          <div className="space-y-2">{carryoverTasks.map((task) => renderTaskCard(task, true))}</div>
          {carryover.total > carryover.items.length && (
            <Button variant="outline" className="mt-3" disabled={isLoadingMore} onClick={() => onLoadMore("carryover")}>
              Ver más de arrastre ({carryover.total - carryover.items.length} restantes)
            </Button>
          )}
        </div>
      )}

      {unplannedTasks.length > 0 && (
        <div className="mt-6">
          <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
            Sin planificar ({unplanned.total})
          </p>
          <div className="space-y-2">
            {unplannedTasks.map((task) => renderTaskCard(task))}
          </div>
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
                  className="opacity-0 group-hover/done:opacity-100 transition-opacity shrink-0 text-muted-foreground hover:text-amber-600"
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
  )
}
