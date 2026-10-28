import { useEffect, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useQuery, useMutation, useQueryClient, useInfiniteQuery } from "@tanstack/react-query"
import { tasksApi, clientsApi, categoriesApi, usersApi } from "@/lib/api"
import type { Task, TaskAgendaSection, TaskCreate, TaskStatus } from "@/lib/types"
import { cn } from "@/lib/utils"
import { usePagination } from "@/hooks/use-pagination"
import { useAuth } from "@/context/auth-context"
import { Pagination } from "@/components/ui/pagination"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { InfoTooltip } from "@/components/ui/tooltip"
import { Plus, Pencil, Eye, Trash2, Clock, Calendar, Kanban, List, CheckSquare, CalendarDays, Repeat } from "lucide-react"
import { InlineDate } from "@/components/ui/inline-edit"
import { TaskAssigneeField, TaskDateField, TaskEstimateField, TaskPriorityBadge, TaskPriorityField, TaskTitleField } from "@/components/tasks/task-inline-fields"
import { useTaskMove, useTaskQuickUpdate, type TaskMove, type TaskQuickUpdate } from "@/hooks/use-task-quick-update"
import { useTableSort } from "@/hooks/use-table-sort"
import { useBulkSelect } from "@/hooks/use-bulk-select"
import { SortableTableHead } from "@/components/ui/sortable-table-head"
import { BulkActionBar } from "@/components/ui/bulk-action-bar"
import { EmptyTableState } from "@/components/ui/empty-state"
import { SkeletonTableRow } from "@/components/ui/skeleton"
import { TimerButton } from "@/components/timer/timer-button"
import { TimeLogDialog } from "@/components/timer/time-log-dialog"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { NextMeeting } from "@/components/tasks/next-meeting"
import { MyDayView } from "@/components/tasks/my-day-view"
import { AgendaSubtasks } from "@/components/tasks/agenda-subtasks"
import { AgendaLeadFollowups } from "@/components/tasks/agenda-lead-followups"
import { isEnabled } from "@/lib/hidden-modules"
import { AgendaHoursView, type HoursMode } from "@/components/tasks/agenda-hours-view"
import { CarryoverReviewDialog } from "@/components/tasks/carryover-review-dialog"
import { IncidentInbox } from "@/components/incidents/incident-inbox"
import { KanbanBoard } from "@/components/tasks/kanban-board"
import { TaskCalendarView } from "@/components/tasks/task-calendar-view"
import { WeeklyPlannerView } from "@/components/tasks/weekly-planner-view"
import { TaskPanel } from "@/components/tasks/task-panel"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import { LAST_TASKS_VIEW, agendaOrder, boardStatusQuery, calendarMonthFrom, calendarMonthParam, initialTasksView, rememberTasksView, selectedTaskAssignee, shiftCalendarMonth, taskQueryKeyWithWeek, weekOffsetFrom, weekParam, withTaskAssignee } from "@/components/tasks/task-page-utils"
import { invalidateTaskChange, taskKeys } from "@/lib/query-keys"
import type { OperationalImpact } from "@/lib/query-keys"
import { addCivilDays } from "@/lib/dates"
import { formatMinutes } from "@/lib/inline-edit"
import { useBusinessDate } from "@/hooks/use-business-date"
import { taskStatusPresentation, taskStatusSelectClass } from "@/lib/task-status"


const weekRange = (offset: number, today: string) => {
  const day = new Date(`${today}T12:00:00`).getDay()
  const monday = addCivilDays(today, (day === 0 ? -6 : 1 - day) + offset * 7)
  return { from: monday, to: addCivilDays(monday, 4) }
}

const ACTIVE_STATUS_FILTER = "backlog,pending,in_progress,advanced,waiting,in_review"
// Tablero, calendario y semana no paginan: traen hasta este tope y avisan si
// hay más. "Sin planificar" y "Hecho" (últimos 7 días) llevan el suyo.
const BOARD_LIMIT = 500
const UNSCHEDULED_LIMIT = 100
const COMPLETED_LIMIT = 200
const COMPLETED_DAYS = 7

export default function TasksPage() {
  const { user, isAdmin, hasPermission } = useAuth()
  const canWriteTasks = hasPermission?.("tasks", true) ?? false
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const { page, pageSize, setPage, reset } = usePagination(25)
  const businessToday = useBusinessDate()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [carryoverTask, setCarryoverTask] = useState<Task | null>(null)
  const [editing, setEditing] = useState<Task | null>(null)
  const [editingInitialStatus, setEditingInitialStatus] = useState<TaskStatus | undefined>()
  const [timeLogTask, setTimeLogTask] = useState<Task | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false)
  const view = initialTasksView(searchParams)
  const setView = (nextView: typeof view) => setSearchParams((previous) => {
    const next = new URLSearchParams(previous)
    next.set("view", nextView)
    next.delete("qaFilter")
    return next
  })
  // El menú abre "la última vista de Tareas": se resuelve y se escribe la real
  // en la URL para que recargar o compartir enseñe lo mismo.
  useEffect(() => {
    if (searchParams.get("view") !== LAST_TASKS_VIEW) return
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous)
      next.set("view", view)
      return next
    }, { replace: true })
  }, [searchParams, setSearchParams, view])
  useEffect(() => { rememberTasksView(view) }, [view])
  const isBoardView = view === "sprint" || view === "calendar" || view === "weekly"
  // Mes del calendario y semana del planificador también viven en la URL.
  const calMonth = calendarMonthFrom(searchParams.get("mes"), businessToday)
  const setCalMonth = (next: { year: number; month: number }) => setSearchParams((previous) => {
    const params = new URLSearchParams(previous)
    if (calendarMonthParam(next) === businessToday.slice(0, 7)) params.delete("mes")
    else params.set("mes", calendarMonthParam(next))
    return params
  }, { replace: true })
  const weekOffset = weekOffsetFrom(searchParams.get("semana"), businessToday)
  const setWeekOffset = (offset: number) => setSearchParams((previous) => {
    const params = new URLSearchParams(previous)
    if (offset === 0) params.delete("semana")
    else params.set("semana", weekParam(offset, businessToday))
    return params
  }, { replace: true })

  // Filters
  // Los filtros viven en la URL: sobreviven a abrir una tarea, volver atrás o
  // compartir el enlace. El estado por defecto ("Activas") no se escribe.
  const urlFilter = (key: string, fallback = "") => searchParams.get(key) ?? fallback
  const setUrlFilter = (key: string, value: string, fallback = "") => setSearchParams((previous) => {
    const next = new URLSearchParams(previous)
    if (value === fallback) next.delete(key)
    else next.set(key, value)
    return next
  }, { replace: true })
  const filterClient = urlFilter("cliente")
  const setFilterClient = (value: string) => setUrlFilter("cliente", value)
  const filterCategory = urlFilter("categoria")
  const setFilterCategory = (value: string) => setUrlFilter("categoria", value)
  const filterStatus = urlFilter("estado", ACTIVE_STATUS_FILTER)
  const setFilterStatus = (value: string) => setUrlFilter("estado", value, ACTIVE_STATUS_FILTER)
  const filterPriority = urlFilter("prioridad")
  const setFilterPriority = (value: string) => setUrlFilter("prioridad", value)
  const filterAssigned = selectedTaskAssignee(searchParams, user?.id, user?.role === "admin")
  const setFilterAssigned = (value: string) => setSearchParams((previous) =>
    withTaskAssignee(previous, value, user?.role === "admin"))
  const filterDateFrom = urlFilter("desde")
  const setFilterDateFrom = (value: string) => setUrlFilter("desde", value)
  const filterDateTo = urlFilter("hasta")
  const setFilterDateTo = (value: string) => setUrlFilter("hasta", value)
  const filterDateField: "due_date" | "scheduled_date" = urlFilter("fecha") === "planificada" ? "scheduled_date" : "due_date"
  const setFilterDateField = (value: "due_date" | "scheduled_date") => setUrlFilter("fecha", value === "scheduled_date" ? "planificada" : "")
  // La búsqueda escrita se aplica (URL + consulta) 300 ms después de la última tecla.
  const searchQuery = urlFilter("q")
  const [searchInput, setSearchInput] = useState(searchQuery)
  useEffect(() => {
    if (searchInput.trim() === searchQuery) return
    const timer = window.setTimeout(() => { setUrlFilter("q", searchInput.trim()); reset() }, 300)
    return () => window.clearTimeout(timer)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput])
  const secondaryFilters = [filterCategory, filterPriority, filterDateFrom, filterDateTo].filter(Boolean).length

  // The URL is the single source of truth, including browser Back/Forward.
  type QaFilter = "none" | "unassigned" | "no_date" | "no_estimate" | "no_project" | "overdue"
  const rawQaFilter = searchParams.get("qaFilter")
  const qaFilter: QaFilter = ["unassigned", "no_date", "no_estimate", "no_project", "overdue"].includes(rawQaFilter ?? "") ? rawQaFilter as QaFilter : "none"
  const setQaFilter = (value: QaFilter) => setSearchParams((previous) => {
    const next = new URLSearchParams(previous)
    next.set("view", "all")
    if (value === "none") next.delete("qaFilter")
    else next.set("qaFilter", value)
    return next
  })
  const agendaScope = user?.role === "admin" && searchParams.get("scope") === "team" ? "team" : "mine"
  const setAgendaScope = (scope: string) => setSearchParams((previous) => {
    const next = new URLSearchParams(previous)
    if (scope === "team") next.set("scope", "team")
    else next.delete("scope")
    return next
  })
  const [bulkStatus, setBulkStatus] = useState("")

  const deepLinkTaskId = searchParams.get("edit") || searchParams.get("task") || searchParams.get("id")

  // Mi agenda en lista (por defecto) o con horas (`agenda=horas`): bloques de
  // trabajo propios y reuniones de Google; día o semana (`horas=semana`) y el
  // día que se mira (`dia=AAAA-MM-DD`). Los bloques son de cada uno: con "Todo
  // el equipo" sólo hay lista.
  const agendaMode = searchParams.get("agenda") === "horas" && agendaScope === "mine" ? "hours" : "list"
  const hoursMode: HoursMode = searchParams.get("horas") === "semana" ? "week" : "day"
  const hoursAnchor = /^\d{4}-\d{2}-\d{2}$/.test(searchParams.get("dia") ?? "") ? searchParams.get("dia")! : businessToday
  const setAgendaParams = (changes: Record<string, string | null>) => setSearchParams((previous) => {
    const next = new URLSearchParams(previous)
    Object.entries(changes).forEach(([key, value]) => (value === null ? next.delete(key) : next.set(key, value)))
    return next
  }, { replace: true })

  // Calendar date range: first and last day of the selected month
  const calDateFrom = view === "calendar"
    ? `${calMonth.year}-${String(calMonth.month + 1).padStart(2, "0")}-01`
    : undefined
  const calDateTo = view === "calendar"
    ? (() => { const d = new Date(calMonth.year, calMonth.month + 1, 0); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}` })()
    : undefined

  const selectedWeek = weekRange(weekOffset, businessToday)
  const boardStatus = boardStatusQuery(filterStatus, ACTIVE_STATUS_FILTER)
  const listStatus = view === "sprint" ? boardStatus.active : filterStatus
  const listPage = isBoardView ? 1 : page
  const listPageSize = isBoardView ? BOARD_LIMIT : pageSize
  const tasksQueryKey = taskQueryKeyWithWeek(
    taskKeys.list([filterClient, filterCategory, listStatus, filterPriority, filterAssigned, filterDateFrom, filterDateTo, filterDateField, searchQuery, listPage, listPageSize, qaFilter, view, calMonth.year, calMonth.month]),
    selectedWeek,
  )
  // Mismos filtros que la lista para las consultas auxiliares del tablero y la semana.
  const sharedFilters = {
    client_id: filterClient ? Number(filterClient) : undefined,
    category_id: filterCategory ? Number(filterCategory) : undefined,
    priority: filterPriority || undefined,
    assigned_to: filterAssigned ? Number(filterAssigned) : undefined,
    search: searchQuery || undefined,
  }
  const { data: tasksData, isLoading, isError: isTasksError, refetch: refetchTasks } = useQuery({
    queryKey: tasksQueryKey,
    queryFn: () =>
      tasksApi.list({
        client_id: filterClient ? Number(filterClient) : undefined,
        category_id: filterCategory ? Number(filterCategory) : undefined,
        status: listStatus || undefined,
        priority: filterPriority || undefined,
        assigned_to: qaFilter === "unassigned" ? ("unassigned" as unknown as number) : (filterAssigned ? Number(filterAssigned) : undefined),
        due_date_from: calDateFrom ?? (filterDateField === "due_date" && filterDateFrom ? filterDateFrom : undefined),
        due_date_to: calDateTo ?? (filterDateField === "due_date" && filterDateTo ? filterDateTo : undefined),
        scheduled_date_from: view === "weekly" ? selectedWeek.from : (filterDateField === "scheduled_date" && filterDateFrom ? filterDateFrom : undefined),
        scheduled_date_to: view === "weekly" ? selectedWeek.to : (filterDateField === "scheduled_date" && filterDateTo ? filterDateTo : undefined),
        overdue: qaFilter === "overdue" ? true : undefined,
        no_date: qaFilter === "no_date" ? true : undefined,
        no_estimate: qaFilter === "no_estimate" ? true : undefined,
        no_project: qaFilter === "no_project" ? true : undefined,
        search: searchQuery || undefined,
        page: listPage,
        page_size: listPageSize,
      }),
    enabled: view !== "my_day" && listStatus !== null,
  })
  const completedFrom = addCivilDays(businessToday, -(COMPLETED_DAYS - 1))
  const completedQueryKey = taskKeys.list(["board-completed", completedFrom, sharedFilters])
  const showCompletedColumn = view === "sprint" && boardStatus.completed
  const { data: completedData, isError: isCompletedError } = useQuery({
    queryKey: completedQueryKey,
    queryFn: () => tasksApi.list({ ...sharedFilters, status: "completed", completed_from: completedFrom, page: 1, page_size: COMPLETED_LIMIT }),
    enabled: showCompletedColumn,
  })
  const unscheduledQueryKey = taskKeys.list(["week-unscheduled", sharedFilters])
  const { data: unscheduledData } = useQuery({
    queryKey: unscheduledQueryKey,
    queryFn: () => tasksApi.list({ ...sharedFilters, status: "pending,backlog", unscheduled: true, page: 1, page_size: UNSCHEDULED_LIMIT }),
    enabled: view === "weekly",
  })

  const useAgendaQuery = (section: TaskAgendaSection) => useInfiniteQuery({
    queryKey: taskKeys.agenda(section, businessToday, user?.id, 0, agendaScope),
    queryFn: ({ pageParam }) => tasksApi.agenda({ date: businessToday, section, assigned_to: agendaScope === "team" ? "all" : "me", page: pageParam, page_size: pageSize }),
    initialPageParam: 1,
    getNextPageParam: (lastPage) => lastPage.page * lastPage.page_size < lastPage.total ? lastPage.page + 1 : undefined,
    enabled: view === "my_day",
  })
  const plannedAgenda = useAgendaQuery("planned")
  const carryoverAgenda = useAgendaQuery("carryover")
  const unplannedAgenda = useAgendaQuery("unplanned")
  const followupsAgenda = useAgendaQuery("followups")
  const completedAgenda = useAgendaQuery("completed")
  const retiredTasks = useInfiniteQuery({
    queryKey: taskKeys.list(["retired", user?.id]),
    queryFn: ({ pageParam }) => tasksApi.list({ retirement: "retired", page: pageParam, page_size: pageSize }),
    initialPageParam: 1,
    getNextPageParam: (lastPage) => lastPage.page * lastPage.page_size < lastPage.total ? lastPage.page + 1 : undefined,
    enabled: view === "my_day",
  })
  const agendaData = (query: typeof plannedAgenda) => {
    const pages = query.data?.pages ?? []
    const last = pages[pages.length - 1]
    return { items: pages.flatMap((item) => item.items), total: last?.total ?? 0, page: last?.page ?? 1, page_size: last?.page_size ?? pageSize }
  }
  const agendaLoading = plannedAgenda.isLoading || carryoverAgenda.isLoading || unplannedAgenda.isLoading || followupsAgenda.isLoading || completedAgenda.isLoading
  const invalidateTaskViews = (affected: OperationalImpact = {}) =>
    invalidateTaskChange(queryClient, affected)
  const allTasks = listStatus === null ? [] : tasksData?.items ?? []
  const withoutDuplicates = (items: Task[]) => items.filter((task, index) => items.findIndex((other) => other.id === task.id) === index)
  const boardTasks = withoutDuplicates([...allTasks, ...(showCompletedColumn ? completedData?.items ?? [] : [])])
  const weekTasks = withoutDuplicates([...allTasks, ...(unscheduledData?.items ?? [])])
  const boardTruncated = isBoardView && !!tasksData && tasksData.total > tasksData.items.length
  const agendaTasks = [plannedAgenda, carryoverAgenda, unplannedAgenda, followupsAgenda, completedAgenda]
    .flatMap((query) => agendaData(query).items)
  const visibleTasks = [...boardTasks, ...weekTasks, ...agendaTasks]

  const impactForTasks = (items: Task[], extra: Record<string, unknown> = {}) => ({
    projectIds: [...items.map((task) => task.project_id), typeof extra.project_id === "number" ? extra.project_id : undefined],
    clientIds: [...items.map((task) => task.client_id), typeof extra.client_id === "number" ? extra.client_id : undefined],
  })

  const todayStr = businessToday
  const tasks = allTasks

  const { sortedItems: sortedTasks, sortConfig: taskSortConfig, requestSort: requestTaskSort } = useTableSort(tasks)
  const { selectedIds: selectedTaskIds, isSelected: isTaskSelected, toggleItem: toggleTask, toggleAll: toggleAllTasks, clearSelection: clearTaskSelection, selectedCount: selectedTaskCount, allSelected: allTasksSelected } = useBulkSelect(tasks)

  // Clear bulk selection when switching views
  useEffect(() => { clearTaskSelection(); reset() }, [view, qaFilter, reset, clearTaskSelection])
  useEffect(() => { if (!canWriteTasks) clearTaskSelection() }, [canWriteTasks, clearTaskSelection])

  const bulkUpdateMutation = useMutation({
    mutationFn: async ({ ids, updates }: { ids: number[]; updates: Record<string, unknown> }) =>
      tasksApi.bulkUpdate(ids, updates),
    onSuccess: ({ updated, requested, results }, { ids, updates }) => {
      invalidateTaskViews(impactForTasks(visibleTasks.filter((task) => ids.includes(task.id)), updates))
      const failedIds = (results ?? []).filter((result) => !result.updated).map((result) => result.id)
      if (failedIds.length) {
        clearTaskSelection()
        failedIds.forEach(toggleTask)
      } else clearTaskSelection()
      setBulkStatus("")
      if (updated === requested) {
        toast.success(`${updated} tareas actualizadas`)
      } else {
        const detail = results?.find((result) => !result.updated)?.detail
        toast.warning(detail ? `${updated}/${requested} actualizadas. ${detail}` : `${updated}/${requested} actualizadas`)
      }
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar tareas")),
  })

  const bulkDeleteMutation = useMutation({
    mutationFn: async (ids: number[]) => tasksApi.bulkDelete(ids),
    onSuccess: ({ deleted, requested }, ids) => {
      invalidateTaskViews(impactForTasks(visibleTasks.filter((task) => ids.includes(task.id))))
      clearTaskSelection()
      if (deleted === requested) {
        toast.success(`${deleted} tareas eliminadas`)
      } else {
        toast.warning(`${deleted}/${requested} eliminadas`)
      }
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar tareas")),
  })

  const { data: clients = [] } = useQuery({
    queryKey: ["clients-all"],
    queryFn: () => clientsApi.listAll(),
  })

  const { data: categories = [] } = useQuery({
    queryKey: ["categories"],
    queryFn: () => categoriesApi.list(),
  })

  const { data: users = [] } = useQuery({
    queryKey: ["users-all"],
    queryFn: () => usersApi.listAll(),
  })

  // Recurring templates query (only fetched when tab is active)
  const { data: recurringTemplates = [], isLoading: isRecurringLoading, isError: isRecurringError, refetch: refetchRecurring } = useQuery({
    queryKey: taskKeys.recurring(),
    queryFn: () => tasksApi.listAll({ is_recurring: true }),
    enabled: view === "recurring",
  })

  const recurrencePauseMutation = useMutation({
    mutationFn: ({ id, paused }: { id: number; paused: boolean }) =>
      tasksApi.update(id, { recurrence_paused: paused }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: taskKeys.recurring() })
      toast.success("Recurrencia actualizada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "No se pudo cambiar la recurrencia")),
  })

  // Cambios rápidos (celdas de la lista, tablero, calendario, semana y Mi
  // agenda): sin abrir el panel y al momento; si el servidor dice que no,
  // vuelve atrás y lo explica.
  const quickUpdate = useTaskQuickUpdate()
  const updateTask = (task: Task | undefined, update: Omit<TaskQuickUpdate, "task">) => {
    if (task) quickUpdate.mutate({ task, ...update })
  }
  const moveTask = (task: Task | undefined, data: Partial<TaskCreate>) =>
    updateTask(task, { data, error: "No se pudo mover la tarea" })
  // Arrastrar en el tablero o en Mi agenda: orden manual y, si cambia, estado o día.
  const taskMove = useTaskMove()
  const dragTask = (task: Task, orderedIds: number[], extra: Pick<TaskMove, "status" | "scheduledDate"> = {}) => {
    const byId = new Map(visibleTasks.map((item) => [item.id, item]))
    const ordered = orderedIds.map((id) => id === task.id ? task : byId.get(id)).filter((item): item is Task => !!item)
    taskMove.mutate({ task, ordered, ...extra })
  }

  const deleteMutation = useMutation({
    mutationFn: (id: number) => tasksApi.delete(id),
    onSuccess: (_data, deletedId) => {
      const deletedTask = visibleTasks.find((task) => task.id === deletedId)
      invalidateTaskViews({ projectId: deletedTask?.project_id, clientId: deletedTask?.client_id })
      toast.success("Tarea eliminada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar tarea")),
  })


  const closeDialog = () => {
    setDialogOpen(false)
    setEditing(null)
    setEditingInitialStatus(undefined)
  }

  const openCreate = () => {
    setEditing(null)
    setEditingInitialStatus(undefined)
    setDialogOpen(true)
  }

  const openEdit = (task: Task, initialStatus?: TaskStatus) => {
    setEditing(task)
    setEditingInitialStatus(initialStatus)
    setDialogOpen(true)
  }

  // El panel pasa a la tarea anterior o siguiente en el orden que se ve: la
  // lista (página actual, con su orden) o Mi agenda (sección a sección).
  const navigableTasks = view === "all" ? sortedTasks
    : view === "my_day" ? agendaOrder({
      planned: agendaData(plannedAgenda).items,
      carryover: agendaData(carryoverAgenda).items,
      followups: agendaData(followupsAgenda).items,
      unplanned: agendaData(unplannedAgenda).items,
      completed: agendaData(completedAgenda).items,
    }, businessToday)
    : []
  const openIndex = dialogOpen && editing ? navigableTasks.findIndex((task) => task.id === editing.id) : -1
  const panelNavigation = openIndex >= 0 ? {
    position: openIndex + 1,
    total: navigableTasks.length,
    onNavigate: (direction: 1 | -1) => {
      const next = navigableTasks[openIndex + direction]
      if (!next) return
      openEdit(next)
      document.querySelector(`[data-task-row="${next.id}"]`)?.scrollIntoView({ block: "nearest" })
    },
  } : undefined

  const sendsForReview = (task: Task) => !!task.project_requires_task_review
    && !task.is_recurring
    && !isAdmin
    && task.project_review_owner_id !== user?.id

  useEffect(() => {
    if (!deepLinkTaskId) return
    const taskId = Number(deepLinkTaskId)
    if (!Number.isFinite(taskId) || taskId <= 0) return

    let cancelled = false

    tasksApi.get(taskId)
      .then((task) => {
        if (cancelled) return
        openEdit(task)
        // Clean up deep link params without re-triggering
        const next = new URLSearchParams(window.location.search)
        next.delete("edit")
        next.delete("task")
        next.delete("id")
        setSearchParams(next, { replace: true })
      })
      .catch((err) => {
        if (!cancelled) {
          toast.error(getErrorMessage(err, "No se pudo abrir la tarea"))
        }
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkTaskId])

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{view === "my_day" ? "Mi agenda" : "Tareas"}</h1>
          {view === "my_day" ? (
            <p className="text-sm text-muted-foreground mt-1">
              {agendaData(plannedAgenda).total} para hoy · {agendaData(carryoverAgenda).total} de arrastre · {agendaData(unplannedAgenda).total} sin planificar · {agendaData(followupsAgenda).total} seguimientos · {agendaData(completedAgenda).total} completadas hoy
            </p>
          ) : view === "recurring" ? (
            <p className="text-sm text-muted-foreground mt-1">
              {isRecurringLoading ? "Cargando plantillas…" : isRecurringError ? "Plantillas no disponibles" : `${recurringTemplates.length} plantilla${recurringTemplates.length === 1 ? "" : "s"} recurrente${recurringTemplates.length === 1 ? "" : "s"}`}
            </p>
          ) : tasksData && (
            <p className="text-sm text-muted-foreground mt-1">
              {tasksData.total} tareas
              <span className="text-muted-foreground/70 text-xs ml-1">(según filtros)</span>
              {" · "}
              {tasks.filter(t => t.status === "in_progress").length} en curso
            </p>
          )}
        </div>
        {canWriteTasks && <Button onClick={openCreate}>
          <Plus className="h-4 w-4 mr-2" /> Nueva tarea
        </Button>}
      </div>

      {view === "my_day" && <div className="flex flex-wrap items-center gap-3">
        {user?.role === "admin" ? <Select aria-label="Ámbito de Hoy" className="w-full sm:w-48" value={agendaScope} onChange={(event) => setAgendaScope(event.target.value)}><option value="mine">Mi trabajo</option><option value="team">Todo el equipo</option></Select> : <p className="text-sm text-muted-foreground">Mi trabajo</p>}
        {agendaScope === "mine" && (
          <div role="group" aria-label="Cómo ver Mi agenda" className="flex rounded-lg border border-border bg-muted/30 p-0.5">
            <Button type="button" size="sm" variant={agendaMode === "list" ? "default" : "ghost"} aria-pressed={agendaMode === "list"} className="h-7 px-3 text-xs"
              onClick={() => setAgendaParams({ agenda: null, horas: null, dia: null })}>
              <List className="mr-1.5 h-3.5 w-3.5" /> Lista
            </Button>
            <Button type="button" size="sm" variant={agendaMode === "hours" ? "default" : "ghost"} aria-pressed={agendaMode === "hours"} className="h-7 px-3 text-xs"
              onClick={() => setAgendaParams({ agenda: "horas" })}>
              <Clock className="mr-1.5 h-3.5 w-3.5" /> Horas
            </Button>
          </div>
        )}
      </div>}
      {view === "my_day" && agendaScope === "mine" && user && <NextMeeting today={businessToday} />}
      {view === "my_day" && agendaScope === "mine" && user && <IncidentInbox key={user.id} userId={user.id} compact />}
      {view !== "my_day" && view !== "recurring" && <>
      {/* Search + Filters */}
      <div className="flex flex-wrap gap-3">
        <Input
          type="search"
          aria-label="Buscar tareas"
          placeholder="Buscar tareas..."
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          className="w-64"
        />
        <Select aria-label="Filtrar por cliente" value={filterClient} onChange={(e) => { setFilterClient(e.target.value); reset() }} className="w-48">
          <option value="">Todos los clientes</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
        <Select aria-label="Filtrar por estado" value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); reset() }} className="w-48">
          <option value="">Todos (incl. completadas)</option>
          <option value={ACTIVE_STATUS_FILTER}>Activas</option>
          <option value="pending,backlog">Pendiente</option>
          <option value="in_progress,advanced">En curso</option>
          <option value="waiting">En espera</option>
          <option value="in_review">En revisión</option>
          <option value="completed">Hecho</option>
        </Select>
        <Select aria-label="Filtrar por responsable" value={filterAssigned} onChange={(e) => { setFilterAssigned(e.target.value); reset() }} className="w-48">
          <option value="">Todos los asignados</option>
          {users.map((u) => (
            <option key={u.id} value={u.id}>
              {u.full_name}
            </option>
          ))}
        </Select>
        <details className="w-full" open={secondaryFilters > 0}>
          <summary className="cursor-pointer select-none text-sm text-muted-foreground">Más filtros{secondaryFilters > 0 ? ` (${secondaryFilters})` : ""}</summary>
          <div className="mt-3 flex flex-wrap gap-3">
        <Select aria-label="Filtrar por categoría" value={filterCategory} onChange={(e) => { setFilterCategory(e.target.value); reset() }} className="w-48">
          <option value="">Todas las categorias</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
        <Select aria-label="Filtrar por prioridad" value={filterPriority} onChange={(e) => { setFilterPriority(e.target.value); reset() }} className="w-48">
          <option value="">Todas las prioridades</option>
          <option value="urgent">Urgente</option>
          <option value="high">Alta</option>
          <option value="medium">Media</option>
          <option value="low">Baja</option>
        </Select>
        <Select aria-label="Tipo de fecha para filtrar" value={filterDateField} onChange={(e) => { setFilterDateField(e.target.value as "due_date" | "scheduled_date"); reset() }} className="w-40">
          <option value="due_date">Fecha límite</option>
          <option value="scheduled_date">Fecha planificada</option>
        </Select>
        <Input
          type="date"
          aria-label={`${filterDateField === "due_date" ? "Fecha límite" : "Fecha planificada"} desde`}
          value={filterDateFrom}
          onChange={(e) => { setFilterDateFrom(e.target.value); reset() }}
          placeholder="Desde"
          title={`${filterDateField === "due_date" ? "Fecha límite" : "Fecha planificada"} desde`}
          className="w-40"
        />
        <Input
          type="date"
          aria-label={`${filterDateField === "due_date" ? "Fecha límite" : "Fecha planificada"} hasta`}
          value={filterDateTo}
          onChange={(e) => { setFilterDateTo(e.target.value); reset() }}
          placeholder="Hasta"
          title={`${filterDateField === "due_date" ? "Fecha límite" : "Fecha planificada"} hasta`}
          className="w-40"
        />
          </div>
        </details>
      </div>

      {/* Revisión rápida: huecos de datos que conviene completar */}
      <div className="flex gap-2 flex-wrap items-center mb-4" role="group" aria-label="Revisión rápida">
        <span className="text-xs text-muted-foreground">Revisión rápida:</span>
        {([
          ["unassigned", "Sin responsable", undefined],
          ["no_date", "Sin fecha límite ni plan", undefined],
          ["no_estimate", "Sin estimación de tiempo", undefined],
          ["no_project", "Sin proyecto", "Tareas sin proyecto asignado (no cuentan en métricas de proyecto)"],
          ["overdue", "Vencidas", undefined],
        ] as const).map(([value, label, title]) => (
          <Button
            key={value}
            variant={qaFilter === value ? "secondary" : "outline"}
            size="sm"
            aria-pressed={qaFilter === value}
            onClick={() => { setQaFilter(qaFilter === value ? "none" : value); reset() }}
            className="text-xs h-8"
            title={title}
          >
            {label}
          </Button>
        ))}
        {qaFilter !== "none" && (
          <Button variant="ghost" size="sm" onClick={() => { setQaFilter("none"); reset() }} className="text-xs h-8 text-muted-foreground">
            Quitar revisión
          </Button>
        )}
      </div>
      </>}

      {view !== "my_day" && <div className="relative mb-6">
      <div role="group" aria-label="Vista de tareas" className="flex gap-2 overflow-x-auto scrollbar-none flex-nowrap bg-muted/30 p-1 sm:w-fit rounded-lg border border-border">
        <Button
          aria-pressed={view === "all"}
          variant={view === "all" ? "default" : "ghost"}
          size="sm"
          className="shrink-0 whitespace-nowrap"
          onClick={() => setView("all")}
        >
          <List className="w-4 h-4 mr-2" /> Lista
        </Button>
        <Button
          aria-pressed={view === "sprint"}
          variant={view === "sprint" ? "default" : "ghost"}
          size="sm"
          className="shrink-0 whitespace-nowrap"
          onClick={() => setView("sprint")}
        >
          <Kanban className="w-4 h-4 mr-2" /> Tablero
        </Button>
        <Button
          aria-pressed={view === "calendar"}
          variant={view === "calendar" ? "default" : "ghost"}
          size="sm"
          className="shrink-0 whitespace-nowrap"
          onClick={() => setView("calendar")}
        >
          <CalendarDays className="w-4 h-4 mr-2" /> Calendario
        </Button>
        <Button
          aria-pressed={view === "weekly"}
          variant={view === "weekly" ? "default" : "ghost"}
          size="sm"
          className="shrink-0 whitespace-nowrap"
          onClick={() => setView("weekly")}
        >
          <Calendar className="w-4 h-4 mr-2" /> Semana
        </Button>
        <Button
          aria-pressed={view === "recurring"}
          variant={view === "recurring" ? "default" : "ghost"}
          size="sm"
          className="shrink-0 whitespace-nowrap"
          onClick={() => setView("recurring")}
        >
          <Repeat className="w-4 h-4 mr-2" /> Recurrentes
        </Button>
      </div>
      <div className="absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-background to-transparent pointer-events-none sm:hidden" />
      </div>}

      {/* Table & Planner */}
      {((view !== "recurring" && isLoading) || (view === "my_day" && agendaLoading)) ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10" />
              <TableHead>Título</TableHead>
              <TableHead>Cliente</TableHead>
              <TableHead>Prioridad</TableHead>
              <TableHead>Asignado</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead><span className="inline-flex items-center gap-1">Est / Real <InfoTooltip content="Estimado: minutos previstos al crear la tarea. Real: minutos declarados al cerrarla. Para horas fichadas con el cronómetro, mira la columna Tiempo." /></span></TableHead>
              <TableHead>Planificada</TableHead>
              <TableHead>Fecha límite</TableHead>
              <TableHead className="w-24">Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Array.from({ length: 5 }).map((_, i) => <SkeletonTableRow key={i} cols={10} />)}
          </TableBody>
        </Table>
      ) : isTasksError && view !== "my_day" && view !== "recurring" ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center">
          <p className="font-medium">No se pudieron cargar las tareas</p>
          <p className="text-sm text-muted-foreground mt-1">No mostramos un estado vacío porque la información no está disponible.</p>
          <Button variant="outline" className="mt-3" onClick={() => refetchTasks()}>Reintentar</Button>
        </div>
      ) : view === "all" ? (
        <Table>
          <TableHeader>
            <TableRow>
              {canWriteTasks && <TableHead className="w-10">
                <input
                  type="checkbox"
                  aria-label="Seleccionar todas las tareas visibles"
                  checked={allTasksSelected}
                  onChange={toggleAllTasks}
                  className="rounded border-border"
                />
              </TableHead>}
              <SortableTableHead sortKey="title" currentSort={taskSortConfig} onSort={requestTaskSort}>Título</SortableTableHead>
              <SortableTableHead sortKey="client_name" currentSort={taskSortConfig} onSort={requestTaskSort}>Cliente</SortableTableHead>
              <SortableTableHead sortKey="priority" currentSort={taskSortConfig} onSort={requestTaskSort}>Prioridad</SortableTableHead>
              <TableHead>Asignado</TableHead>
              <SortableTableHead sortKey="status" currentSort={taskSortConfig} onSort={requestTaskSort}>Estado</SortableTableHead>
              <TableHead><span className="inline-flex items-center gap-1">Est / Real <InfoTooltip content="Estimado: minutos previstos al crear la tarea. Real: minutos declarados al cerrarla. Para horas fichadas con el cronómetro, mira la columna Tiempo." /></span></TableHead>
              <SortableTableHead sortKey="scheduled_date" currentSort={taskSortConfig} onSort={requestTaskSort}>Planificada</SortableTableHead>
              <SortableTableHead sortKey="due_date" currentSort={taskSortConfig} onSort={requestTaskSort}>Fecha límite</SortableTableHead>
              <TableHead className="w-24">Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedTasks.map((t) => {
              const QA_unassigned = t.assigned_to === null;
              const QA_nodate = t.scheduled_date === null;
              const QA_noestimate = t.estimated_minutes === null;
              const QA_overdue = t.due_date && t.due_date < todayStr;

              const rowHighlight =
                (qaFilter === "unassigned" && QA_unassigned) ||
                  (qaFilter === "no_date" && QA_nodate) ||
                  (qaFilter === "no_estimate" && QA_noestimate) ||
                  (qaFilter === "overdue" && QA_overdue)
                  ? "bg-destructive/5" : "";

              const est = t.estimated_minutes
              const real = t.actual_minutes
              const diff = est && real ? real - est : null

              return (
                <TableRow key={t.id} data-task-row={t.id} aria-current={openIndex >= 0 && editing?.id === t.id ? "true" : undefined} className={cn(rowHighlight, "aria-[current=true]:bg-muted/60")}>
                  {canWriteTasks && <TableCell>
                    <input
                      type="checkbox"
                      aria-label={`Seleccionar tarea ${t.title}`}
                      checked={isTaskSelected(t.id)}
                      onChange={() => toggleTask(t.id)}
                      className="rounded border-border"
                    />
                  </TableCell>}
                  <TableCell className="min-w-40 font-medium">
                    <TaskTitleField task={t} canWrite={canWriteTasks} onUpdate={(update) => updateTask(t, update)} onOpen={() => openEdit(t)}>
                      {t.recurring_parent_id && <Repeat className="w-3 h-3 text-muted-foreground shrink-0" aria-label="Recurrente" />}
                    </TaskTitleField>
                    {t.recurring_parent_title && t.recurrence_occurrence_date && (
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        Prevista por {t.recurring_parent_title} para {t.recurrence_occurrence_date}
                      </p>
                    )}
                    {t.checklist_count > 0 && (
                      <span className="ml-2 text-xs text-muted-foreground">&#9745; {t.checklist_count}</span>
                    )}
                    {t.dependency_title && (
                      <span className="ml-2 text-xs text-muted-foreground">⟶ {t.dependency_title.length > 20 ? t.dependency_title.slice(0, 20) + "…" : t.dependency_title}</span>
                    )}
                  </TableCell>
                  <TableCell>{t.client_name ?? (t.client_id != null ? <span className="text-muted-foreground">(eliminado)</span> : "-")}</TableCell>
                  <TableCell><TaskPriorityField task={t} canWrite={canWriteTasks} onUpdate={(update) => updateTask(t, update)} /></TableCell>
                  <TableCell className={qaFilter === "unassigned" && QA_unassigned ? "text-destructive font-bold" : ""}>
                    <TaskAssigneeField task={t} users={users} canWrite={canWriteTasks} onUpdate={(update) => updateTask(t, update)} emptyText={QA_unassigned && qaFilter === "unassigned" ? "Falta" : "-"} />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1.5">
                    <span className={cn("w-2.5 h-2.5 rounded-full shrink-0", {
                      "bg-gray-500": t.status === "backlog",
                      "bg-yellow-500": t.status === "pending",
                      "bg-blue-500": t.status === "in_progress",
                      "bg-orange-500": t.status === "waiting",
                      "bg-purple-500": t.status === "in_review",
                      "bg-teal-500": t.status === "advanced",
                      "bg-green-500": t.status === "completed",
                    })} />
                    {canWriteTasks ? <Select
                      value={taskStatusPresentation(t.status, t.scheduled_date).group}
                      className={cn("h-7 text-xs w-32 py-0", taskStatusSelectClass(t.status, t.scheduled_date))}
                      onChange={(e) => {
                        const next = e.target.value as TaskStatus
                        if (next === "waiting") {
                          openEdit(t, "waiting")
                          return
                        }
                        updateTask(t, { data: { status: next === "completed" && sendsForReview(t) ? "in_review" : next } })
                      }}
                    >
                      <option value="pending">Pendiente</option>
                      <option value="in_progress">En curso</option>
                      <option value="waiting">En espera…</option>
                      <option value="in_review">En revisión</option>
                      <option value="completed">{sendsForReview(t) ? "Enviar a revisión" : "Hecho"}</option>
                    </Select> : <span className={cn("rounded-md border px-2 py-1 text-xs", taskStatusSelectClass(t.status, t.scheduled_date))}>{taskStatusPresentation(t.status, t.scheduled_date).label}</span>}
                    </div>
                  </TableCell>
                  <TableCell className={cn("text-xs mono whitespace-nowrap", qaFilter === "no_estimate" && QA_noestimate && "text-destructive font-bold")}>
                    <TaskEstimateField task={t} canWrite={canWriteTasks} onUpdate={(update) => updateTask(t, update)} />
                    {" / "}
                    {real ? formatMinutes(real) : "-"}
                    {diff !== null && diff !== 0 && (
                      <span className={diff > 0 ? "text-red-400 ml-1" : "text-green-400 ml-1"}>
                        ({diff > 0 ? "+" : ""}{formatMinutes(Math.abs(diff))})
                      </span>
                    )}
                  </TableCell>
                  <TableCell className={cn("mono whitespace-nowrap", qaFilter === "no_date" && QA_nodate && "text-destructive font-bold")}>
                    <TaskDateField task={t} field="scheduled_date" today={todayStr} canWrite={canWriteTasks} onUpdate={(update) => updateTask(t, update)} emptyText={QA_nodate && qaFilter === "no_date" ? "Falta" : "-"} />
                  </TableCell>
                  <TableCell className={cn("mono whitespace-nowrap", qaFilter === "overdue" && QA_overdue && "text-destructive font-bold")}>
                    <TaskDateField task={t} field="due_date" today={todayStr} canWrite={canWriteTasks} onUpdate={(update) => updateTask(t, update)} />
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-0.5">
                      <TimerButton taskId={t.id} />
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => setTimeLogTask(t)}
                        title="Ver registro de tiempo"
                      >
                        <Clock className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-8 w-8" aria-label={canWriteTasks ? "Editar tarea" : "Ver tarea"} onClick={() => openEdit(t)}>
                        {canWriteTasks ? <Pencil className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </Button>
                      {canWriteTasks && <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="Eliminar tarea" onClick={() => setDeleteId(t.id)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>}
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
            {tasks.length === 0 && (
              searchQuery || filterClient || filterCategory || filterPriority || filterDateFrom || filterDateTo || qaFilter !== "none"
                ? <EmptyTableState colSpan={canWriteTasks ? 10 : 9} icon={CheckSquare} title="Ninguna tarea con estos filtros" description="Quita algún filtro o cambia la búsqueda para ver más." />
                : <EmptyTableState colSpan={canWriteTasks ? 10 : 9} icon={CheckSquare} title="Sin tareas" description="Crea tareas, asígnalas y ficha su tiempo con el cronómetro." />
            )}
          </TableBody>
        </Table>
      ) : null}

      {view === "all" && (
        <Pagination page={page} pageSize={pageSize} total={tasksData?.total ?? 0} onPageChange={setPage} />
      )}
      {boardTruncated && tasksData && (
        <p role="status" className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
          Se ven {tasksData.items.length} de {tasksData.total} tareas. Filtra por cliente, responsable o estado para ver el resto.
        </p>
      )}

      {/* Conditional Rendering of Views */}
      {view === "my_day" && agendaMode === "hours" && (
        <AgendaHoursView
          mode={hoursMode}
          anchor={hoursAnchor}
          today={businessToday}
          onAnchorChange={(day) => setAgendaParams({ dia: day === businessToday ? null : day })}
          onModeChange={(mode) => setAgendaParams({ horas: mode === "week" ? "semana" : null })}
          candidates={[...agendaData(plannedAgenda).items, ...agendaData(carryoverAgenda).items]}
          canWrite={canWriteTasks}
          onOpenTask={(taskId) => setAgendaParams({ task: String(taskId) })}
        />
      )}
      {!isLoading && !agendaLoading && view === "my_day" && agendaMode === "list" && (
        plannedAgenda.isError || carryoverAgenda.isError || unplannedAgenda.isError || followupsAgenda.isError || completedAgenda.isError ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center">
            <p className="font-medium">No hemos podido cargar tus tareas. Reintenta.</p>
            <Button variant="outline" className="mt-3" onClick={() => { plannedAgenda.refetch(); carryoverAgenda.refetch(); unplannedAgenda.refetch(); followupsAgenda.refetch(); completedAgenda.refetch() }}>Reintentar</Button>
          </div>
        ) : (
          <>
          {agendaScope === "mine" && (
            <AgendaSubtasks
              today={businessToday}
              userId={user?.id}
              canWrite={canWriteTasks}
              onOpenTask={(taskId) => setAgendaParams({ task: String(taskId) })}
            />
          )}
          {agendaScope === "mine" && hasPermission?.("growth") && isEnabled("leads") && (
            <AgendaLeadFollowups today={businessToday} userId={user?.id} />
          )}
          <MyDayView
            planned={agendaData(plannedAgenda)}
            carryover={agendaData(carryoverAgenda)}
            unplanned={agendaData(unplannedAgenda)}
            followups={agendaData(followupsAgenda)}
            completed={agendaData(completedAgenda)}
            retired={agendaData(retiredTasks)}
            retiredLoading={retiredTasks.isLoading}
            retiredError={retiredTasks.isError}
            onRetryRetired={() => void retiredTasks.refetch()}
            isLoadingMore={plannedAgenda.isFetchingNextPage || carryoverAgenda.isFetchingNextPage || unplannedAgenda.isFetchingNextPage || followupsAgenda.isFetchingNextPage || completedAgenda.isFetchingNextPage || retiredTasks.isFetchingNextPage}
            onLoadMore={(section) => ({ planned: plannedAgenda, carryover: carryoverAgenda, unplanned: unplannedAgenda, followups: followupsAgenda, completed: completedAgenda, retired: retiredTasks }[section].fetchNextPage())}
            onStatusChange={(id, status) => {
              const task = [...agendaData(plannedAgenda).items, ...agendaData(carryoverAgenda).items, ...agendaData(unplannedAgenda).items, ...agendaData(followupsAgenda).items, ...agendaData(completedAgenda).items].find((item) => item.id === id)
              updateTask(task, { data: { status: status === "completed" && task && sendsForReview(task) ? "in_review" : status } })
            }}
            onUpdate={updateTask}
            onMove={(task, orderedIds, scheduledDate) => dragTask(task, orderedIds, scheduledDate === undefined ? {} : { scheduledDate })}
            onOpenEdit={openEdit}
            canCompleteReviewedTask={(task) => !!(isAdmin || task.project_review_owner_id === user?.id)}
            onReviewCarryover={setCarryoverTask}
            canWrite={canWriteTasks}
          />
          </>
        )
      )}

      {!isLoading && !isTasksError && view === "sprint" && (
        <KanbanBoard
          tasks={boardTasks}
          onMove={(task, orderedIds, status) => dragTask(task, orderedIds, {
            status: status === "completed" && sendsForReview(task) ? "in_review" : status,
          })}
          onOpenEdit={openEdit}
          canWrite={canWriteTasks}
          showCompleted={showCompletedColumn}
          completedHint={isCompletedError ? "No se pudieron cargar" : `últimos ${COMPLETED_DAYS} días`}
        />
      )}

      {!isLoading && !isTasksError && view === "calendar" && (
        <TaskCalendarView
          tasks={allTasks}
          year={calMonth.year}
          month={calMonth.month}
          onPrev={() => setCalMonth(shiftCalendarMonth(calMonth, -1))}
          onNext={() => setCalMonth(shiftCalendarMonth(calMonth, 1))}
          onToday={() => setCalMonth(calendarMonthFrom(null, businessToday))}
          onOpenEdit={openEdit}
          onDueDateChange={canWriteTasks ? (taskId, date) => moveTask(allTasks.find((task) => task.id === taskId), { due_date: date }) : undefined}
        />
      )}

      {!isLoading && !isTasksError && view === "weekly" && (
        <WeeklyPlannerView
          tasks={weekTasks}
          weekOffset={weekOffset}
          onWeekOffsetChange={setWeekOffset}
          onScheduleChange={(taskId, date) => moveTask(weekTasks.find((task) => task.id === taskId), { scheduled_date: date })}
          onOpenEdit={openEdit}
          canWrite={canWriteTasks}
          unscheduledNote={unscheduledData && unscheduledData.total > unscheduledData.items.length
            ? `Las ${unscheduledData.items.length} más recientes de ${unscheduledData.total}`
            : undefined}
        />
      )}

      {view === "recurring" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold">Plantillas recurrentes</h3>
          </div>
          {isRecurringLoading ? (
            <p role="status" className="py-8 text-center text-sm text-muted-foreground">Cargando plantillas recurrentes…</p>
          ) : isRecurringError ? (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center">
              <p className="font-medium">No se pudieron cargar las plantillas recurrentes</p>
              <p className="mt-1 text-sm text-muted-foreground">No mostramos una lista vacía porque la información no está disponible.</p>
              <Button variant="outline" className="mt-3" onClick={() => void refetchRecurring()}>Reintentar</Button>
            </div>
          ) : recurringTemplates.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">No hay plantillas recurrentes</p>
          ) : (
            <div className="overflow-x-auto">
            <Table className="min-w-[800px]">
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-52">Título</TableHead>
                  <TableHead className="min-w-64">Patrón</TableHead>
                  <TableHead>Cliente</TableHead>
                  <TableHead>Asignado</TableHead>
                  <TableHead>Prioridad</TableHead>
                  <TableHead className="w-[80px]">Acciones</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recurringTemplates.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="min-w-52 font-medium">
                      <div className="flex items-center gap-1.5">
                        <Repeat className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                        {t.title}
                      </div>
                    </TableCell>
                    <TableCell className="min-w-64 text-sm">
                      {t.recurrence_summary && <><p>{t.recurrence_summary.label}</p>{t.recurrence_summary.reason && <p className="mt-1 text-xs text-muted-foreground">{t.recurrence_summary.reason}</p>}{t.recurrence_summary.next_dates.length > 0 && <p className="mt-1 text-xs text-muted-foreground">Próximas: {t.recurrence_summary.next_dates.join(" · ")}</p>}</>}
                    </TableCell>
                    <TableCell>{t.client_name ?? <span className="text-muted-foreground">Sin cliente</span>}</TableCell>
                    <TableCell>{t.assigned_user_name}</TableCell>
                    <TableCell><TaskPriorityBadge priority={t.priority} /></TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-xs"
                          onClick={() => recurrencePauseMutation.mutate({ id: t.id, paused: !t.recurrence_paused_at })}
                          disabled={!canWriteTasks || recurrencePauseMutation.isPending}
                        >
                          {t.recurrence_paused_at ? "Reanudar" : "Pausar"}
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(t)} disabled={!canWriteTasks} aria-label={`Editar plantilla ${t.title}`}>
                          <Pencil className="w-3.5 h-3.5" />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => setDeleteId(t.id)} disabled={!canWriteTasks} aria-label={`Eliminar plantilla ${t.title}`}>
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            </div>
          )}
        </div>
      )}

      {/* Create/Edit Dialog */}
      <TaskPanel
        open={dialogOpen}
        taskId={editing?.id}
        defaults={editingInitialStatus ? { initialStatus: editingInitialStatus } : undefined}
        onOpenChange={(open) => { if (!open) closeDialog() }}
        onOpenTime={(task) => { setTimeLogTask(task); closeDialog() }}
        navigation={panelNavigation}
      />
      {carryoverTask && canWriteTasks && <CarryoverReviewDialog key={carryoverTask.id} task={carryoverTask} open onOpenChange={(open) => !open && setCarryoverTask(null)} />}
      {timeLogTask && (
        <TimeLogDialog
          taskId={timeLogTask.id}
          taskTitle={timeLogTask.title}
          taskRetired={!!timeLogTask.retired_at}
          open={!!timeLogTask}
          onOpenChange={(open) => !open && setTimeLogTask(null)}
        />
      )}

      {/* Delete Confirm */}
      <ConfirmDialog
        open={deleteId !== null}
        onOpenChange={(open) => !open && setDeleteId(null)}
        title="Eliminar tarea"
        description="Se eliminará la tarea. Si te equivocas, puedes deshacerlo con ⌘Z o desde el panel ↶."
        onConfirm={() => {
          if (deleteId !== null) {
            deleteMutation.mutate(deleteId)
            setDeleteId(null)
          }
        }}
      />

      {/* Bulk Action Bar */}
      {canWriteTasks && <BulkActionBar selectedCount={selectedTaskCount} onClear={clearTaskSelection}>
        <Select
          value={bulkStatus}
          onChange={(e) => {
            setBulkStatus(e.target.value)
            if (e.target.value) bulkUpdateMutation.mutate({ ids: [...selectedTaskIds], updates: { status: e.target.value } })
          }}
          className="h-8 text-xs w-36"
        >
          <option value="">Estado...</option>
          <option value="pending">Pendiente</option>
          <option value="in_progress">En curso</option>
          <option value="in_review">En revisión</option>
          <option value="completed">Hecho</option>
        </Select>
        <Select
          value=""
          onChange={(e) => {
            if (e.target.value) bulkUpdateMutation.mutate({ ids: [...selectedTaskIds], updates: { priority: e.target.value } })
          }}
          className="h-8 text-xs w-32"
        >
          <option value="">Prioridad...</option>
          <option value="urgent">Urgente</option>
          <option value="high">Alta</option>
          <option value="medium">Media</option>
          <option value="low">Baja</option>
        </Select>
        <Select
          value=""
          onChange={(e) => {
            if (e.target.value) bulkUpdateMutation.mutate({ ids: [...selectedTaskIds], updates: { assigned_to: e.target.value === "none" ? null : Number(e.target.value) } })
          }}
          className="h-8 text-xs w-32"
        >
          <option value="">Asignar a...</option>
          <option value="none">Sin asignar</option>
          {users.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
        </Select>
        <InlineDate
          label="Planificar las tareas seleccionadas"
          valueText="elige un día"
          value={null}
          today={todayStr}
          clearLabel="Sin planificar"
          alwaysClearable
          onChange={(date) => bulkUpdateMutation.mutate({ ids: [...selectedTaskIds], updates: { scheduled_date: date } })}
          className="mx-0 h-8 whitespace-nowrap rounded-md border border-border bg-background px-3 text-xs"
        >
          <CalendarDays className="h-3.5 w-3.5" aria-hidden /> Planificar para…
        </InlineDate>
        <Button
          size="sm"
          variant="destructive"
          onClick={() => setBulkDeleteOpen(true)}
          disabled={bulkDeleteMutation.isPending}
        >
          Eliminar
        </Button>
      </BulkActionBar>}

      <ConfirmDialog
        open={bulkDeleteOpen}
        onOpenChange={setBulkDeleteOpen}
        title="Eliminar tareas"
        description={`Se eliminarán ${selectedTaskCount} tareas. Si te equivocas, puedes deshacerlo de una vez con ⌘Z o desde el panel ↶.`}
        confirmLabel="Eliminar"
        onConfirm={() => bulkDeleteMutation.mutate([...selectedTaskIds])}
      />
    </div>
  )
}
