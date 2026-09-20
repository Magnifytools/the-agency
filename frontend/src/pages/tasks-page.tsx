import { useEffect, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useQuery, useMutation, useQueryClient, useInfiniteQuery } from "@tanstack/react-query"
import { tasksApi, clientsApi, categoriesApi, usersApi } from "@/lib/api"
import type { Task, TaskCreate, TaskStatus, TaskPriority } from "@/lib/types"
import { cn } from "@/lib/utils"
import { usePagination } from "@/hooks/use-pagination"
import { useAuth } from "@/context/auth-context"
import { Pagination } from "@/components/ui/pagination"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { InfoTooltip } from "@/components/ui/tooltip"
import { Plus, Pencil, Trash2, Clock, Calendar, Kanban, List, CheckSquare, CalendarDays, Repeat } from "lucide-react"
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
import { CarryoverReviewDialog } from "@/components/tasks/carryover-review-dialog"
import { IncidentInbox } from "@/components/incidents/incident-inbox"
import { KanbanBoard } from "@/components/tasks/kanban-board"
import { TaskCalendarView } from "@/components/tasks/task-calendar-view"
import { WeeklyPlannerView } from "@/components/tasks/weekly-planner-view"
import { TaskPanel } from "@/components/tasks/task-panel"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import { initialTasksView, taskQueryKeyWithWeek } from "@/components/tasks/task-page-utils"
import { invalidateTaskChange, optimisticallyUpdateExactQuery, restoreQuerySnapshot, taskKeys } from "@/lib/query-keys"
import type { OperationalImpact } from "@/lib/query-keys"
import { addCivilDays, formatCivilDate } from "@/lib/dates"
import { useBusinessDate } from "@/hooks/use-business-date"
import { taskStatusPresentation } from "@/lib/task-status"

const priorityBadge = (priority: TaskPriority) => {
  const map: Record<TaskPriority, { label: string; variant: "destructive" | "warning" | "secondary" | "outline" }> = {
    urgent: { label: "Urgente", variant: "destructive" },
    high: { label: "Alta", variant: "warning" },
    medium: { label: "Media", variant: "secondary" },
    low: { label: "Baja", variant: "outline" },
  }
  const { label, variant } = map[priority] ?? { label: priority, variant: "secondary" as const }
  return <Badge variant={variant} dot={false}>{label}</Badge>
}

const formatMinutes = (mins: number) => {
  if (mins < 60) return `${mins}m`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

const weekRange = (offset: number, today: string) => {
  const day = new Date(`${today}T12:00:00`).getDay()
  const monday = addCivilDays(today, (day === 0 ? -6 : 1 - day) + offset * 7)
  return { from: monday, to: addCivilDays(monday, 4) }
}

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
  const [weekOffset, setWeekOffset] = useState(0)
  const [calMonth, setCalMonth] = useState(() => {
    const d = new Date(); return { year: d.getFullYear(), month: d.getMonth() }
  })

  // Filters
  const [filterClient, setFilterClient] = useState<string>("")
  const [filterCategory, setFilterCategory] = useState<string>("")
  const [filterStatus, setFilterStatus] = useState<string>("backlog,pending,in_progress,advanced,waiting,in_review")
  const [filterPriority, setFilterPriority] = useState<string>("")
  const [filterAssigned, setFilterAssigned] = useState<string>(() =>
    user && user.role !== "admin" ? String(user.id) : ""
  )
  const [filterDateFrom, setFilterDateFrom] = useState<string>("")
  const [filterDateTo, setFilterDateTo] = useState<string>("")
  const [filterDateField, setFilterDateField] = useState<"due_date" | "scheduled_date">("due_date")
  const [searchQuery, setSearchQuery] = useState<string>("")

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

  // Calendar date range: first and last day of the selected month
  const calDateFrom = view === "calendar"
    ? `${calMonth.year}-${String(calMonth.month + 1).padStart(2, "0")}-01`
    : undefined
  const calDateTo = view === "calendar"
    ? (() => { const d = new Date(calMonth.year, calMonth.month + 1, 0); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}` })()
    : undefined

  const selectedWeek = weekRange(weekOffset, businessToday)
  const tasksQueryKey = taskQueryKeyWithWeek(
    taskKeys.list([filterClient, filterCategory, filterStatus, filterPriority, filterAssigned, filterDateFrom, filterDateTo, filterDateField, searchQuery, page, pageSize, qaFilter, view, calMonth.year, calMonth.month]),
    selectedWeek,
  )
  const { data: tasksData, isLoading, isError: isTasksError, refetch: refetchTasks } = useQuery({
    queryKey: tasksQueryKey,
    queryFn: () =>
      tasksApi.list({
        client_id: filterClient ? Number(filterClient) : undefined,
        category_id: filterCategory ? Number(filterCategory) : undefined,
        status: filterStatus || undefined,
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
        page,
        page_size: pageSize,
      }),
    enabled: view !== "my_day",
  })

  const useAgendaQuery = (section: "planned" | "carryover" | "unplanned" | "completed") => useInfiniteQuery({
    queryKey: taskKeys.agenda(section, businessToday, user?.id, 0, agendaScope),
    queryFn: ({ pageParam }) => tasksApi.agenda({ date: businessToday, section, assigned_to: agendaScope === "team" ? "all" : "me", page: pageParam, page_size: pageSize }),
    initialPageParam: 1,
    getNextPageParam: (lastPage) => lastPage.page * lastPage.page_size < lastPage.total ? lastPage.page + 1 : undefined,
    enabled: view === "my_day",
  })
  const plannedAgenda = useAgendaQuery("planned")
  const carryoverAgenda = useAgendaQuery("carryover")
  const unplannedAgenda = useAgendaQuery("unplanned")
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
  const agendaLoading = plannedAgenda.isLoading || carryoverAgenda.isLoading || unplannedAgenda.isLoading || completedAgenda.isLoading
  const invalidateTaskViews = (affected: OperationalImpact = {}) =>
    invalidateTaskChange(queryClient, affected)
  const allTasks = tasksData?.items ?? []
  const agendaTasks = [plannedAgenda, carryoverAgenda, unplannedAgenda, completedAgenda]
    .flatMap((query) => agendaData(query).items)
  const visibleTasks = [...allTasks, ...agendaTasks]

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

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<TaskCreate> }) => tasksApi.update(id, data),
    onSuccess: (task) => {
      const previous = visibleTasks.find((item) => item.id === task.id) ?? editing
      invalidateTaskViews({
        projectId: task.project_id,
        previousProjectId: previous?.project_id,
        clientId: task.client_id,
        previousClientId: previous?.client_id,
      })
      queryClient.invalidateQueries({ queryKey: taskKeys.recurring() })
      closeDialog()
      toast.success("Tarea actualizada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar tarea")),
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

  // Separate mutation for drag & drop schedule changes (no dialog close, optimistic update)
  const scheduleQueryKey = tasksQueryKey
  const scheduleMutation = useMutation({
    mutationFn: ({ id, scheduled_date }: { id: number; scheduled_date: string | null }) =>
      tasksApi.update(id, { scheduled_date }),
    onMutate: async ({ id, scheduled_date }) => {
      const snapshot = await optimisticallyUpdateExactQuery<typeof tasksData>(queryClient, scheduleQueryKey, (old) => {
        if (!old) return old
        return { ...old, items: old.items.map((t: Task) => t.id === id ? { ...t, scheduled_date } : t) }
      })
      const movedTask = visibleTasks.find((task) => task.id === id)
      return { snapshot, projectId: movedTask?.project_id, clientId: movedTask?.client_id }
    },
    onError: (_err, _vars, ctx) => {
      restoreQuerySnapshot(queryClient, ctx?.snapshot)
      toast.error("Error al mover tarea")
    },
    onSettled: (_data, _error, _vars, ctx) => invalidateTaskViews({ projectId: ctx?.projectId, clientId: ctx?.clientId }),
  })

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
          <h1 className="text-2xl font-bold">{view === "my_day" ? "Hoy" : "Tareas"}</h1>
          {view === "my_day" ? (
            <p className="text-sm text-muted-foreground mt-1">
              {agendaData(plannedAgenda).total} para hoy · {agendaData(carryoverAgenda).total} de arrastre · {agendaData(unplannedAgenda).total} sin planificar · {agendaData(completedAgenda).total} completadas hoy
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
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4 mr-2" /> Nueva tarea
        </Button>
      </div>

      {view === "my_day" && (user?.role === "admin" ? <Select aria-label="Ámbito de Hoy" className="w-full sm:w-48" value={agendaScope} onChange={(event) => setAgendaScope(event.target.value)}><option value="mine">Mi trabajo</option><option value="team">Todo el equipo</option></Select> : <p className="text-sm text-muted-foreground">Mi trabajo</p>)}
      {view === "my_day" && agendaScope === "mine" && user && <NextMeeting today={businessToday} />}
      {view === "my_day" && agendaScope === "mine" && user && <IncidentInbox key={user.id} userId={user.id} compact />}
      {view !== "my_day" && view !== "recurring" && <>
      {/* Search + Filters */}
      <div className="flex flex-wrap gap-3">
        <Input
          type="search"
          placeholder="Buscar tareas..."
          value={searchQuery}
          onChange={(e) => { setSearchQuery(e.target.value); reset() }}
          className="w-64"
        />
        <Select value={filterClient} onChange={(e) => { setFilterClient(e.target.value); reset() }} className="w-48">
          <option value="">Todos los clientes</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
        <Select value={filterCategory} onChange={(e) => { setFilterCategory(e.target.value); reset() }} className="w-48">
          <option value="">Todas las categorias</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
        <Select value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); reset() }} className="w-48">
          <option value="">Todos (incl. completadas)</option>
          <option value="backlog,pending,in_progress,advanced,waiting,in_review">Activas</option>
          <option value="pending,backlog">Pendiente</option>
          <option value="in_progress,advanced">En curso</option>
          <option value="waiting">En espera</option>
          <option value="in_review">En revisión</option>
          <option value="completed">Hecho</option>
          <option value="backlog">Pendiente · backlog</option>
          <option value="advanced">En curso · avance registrado</option>
        </Select>
        <Select value={filterPriority} onChange={(e) => { setFilterPriority(e.target.value); reset() }} className="w-48">
          <option value="">Todas las prioridades</option>
          <option value="urgent">Urgente</option>
          <option value="high">Alta</option>
          <option value="medium">Media</option>
          <option value="low">Baja</option>
        </Select>
        <Select value={filterAssigned} onChange={(e) => { setFilterAssigned(e.target.value); reset() }} className="w-48">
          <option value="">Todos los asignados</option>
          {users.map((u) => (
            <option key={u.id} value={u.id}>
              {u.full_name}
            </option>
          ))}
        </Select>
        <Select value={filterDateField} onChange={(e) => { setFilterDateField(e.target.value as "due_date" | "scheduled_date"); reset() }} className="w-40">
          <option value="due_date">Fecha límite</option>
          <option value="scheduled_date">Fecha planificada</option>
        </Select>
        <Input
          type="date"
          value={filterDateFrom}
          onChange={(e) => { setFilterDateFrom(e.target.value); reset() }}
          placeholder="Desde"
          title={`${filterDateField === "due_date" ? "Fecha límite" : "Fecha planificada"} desde`}
          className="w-40"
        />
        <Input
          type="date"
          value={filterDateTo}
          onChange={(e) => { setFilterDateTo(e.target.value); reset() }}
          placeholder="Hasta"
          title={`${filterDateField === "due_date" ? "Fecha límite" : "Fecha planificada"} hasta`}
          className="w-40"
        />
      </div>

      {/* QA Health Filters */}
      <div className="flex gap-2 flex-wrap mb-4">
        <Button
          variant={qaFilter === "unassigned" ? "secondary" : "outline"}
          size="sm"
          onClick={() => { setQaFilter(qaFilter === "unassigned" ? "none" : "unassigned"); reset() }}
          className="text-xs h-8 bg-orange-500/10 hover:bg-orange-500/20 text-orange-600 border-orange-500/20"
        >
          ⚠️ Sin Asignar
        </Button>
        <Button
          variant={qaFilter === "no_date" ? "secondary" : "outline"}
          size="sm"
          onClick={() => { setQaFilter(qaFilter === "no_date" ? "none" : "no_date"); reset() }}
          className="text-xs h-8 bg-blue-500/10 hover:bg-blue-500/20 text-blue-600 border-blue-500/20"
        >
          ⚠️ Sin Fechas
        </Button>
        <Button
          variant={qaFilter === "no_estimate" ? "secondary" : "outline"}
          size="sm"
          onClick={() => { setQaFilter(qaFilter === "no_estimate" ? "none" : "no_estimate"); reset() }}
          className="text-xs h-8 bg-purple-500/10 hover:bg-purple-500/20 text-purple-600 border-purple-500/20"
        >
          ⚠️ Sin Estimación
        </Button>
        <Button
          variant={qaFilter === "no_project" ? "secondary" : "outline"}
          size="sm"
          onClick={() => { setQaFilter(qaFilter === "no_project" ? "none" : "no_project"); reset() }}
          className="text-xs h-8 bg-amber-500/10 hover:bg-amber-500/20 text-amber-600 border-amber-500/20"
          title="Tareas sin proyecto asignado (no cuentan en métricas de proyecto)"
        >
          ⚠️ Sin Proyecto
        </Button>
        <Button
          variant={qaFilter === "overdue" ? "secondary" : "outline"}
          size="sm"
          onClick={() => { setQaFilter(qaFilter === "overdue" ? "none" : "overdue"); reset() }}
          className="text-xs h-8 bg-red-500/10 hover:bg-red-500/20 text-red-600 border-red-500/20"
        >
          🔥 Atrasadas
        </Button>
        {qaFilter !== "none" && (
          <Button variant="ghost" size="sm" onClick={() => { setQaFilter("none"); reset() }} className="text-xs h-8 text-muted-foreground">
            Limpiar filtros QA
          </Button>
        )}
      </div>
      </>}

      {view !== "my_day" && <div className="relative mb-6">
      <div className="flex gap-2 overflow-x-auto scrollbar-none flex-nowrap bg-muted/30 p-1 sm:w-fit rounded-lg border border-border">
        <Button
          variant={view === "sprint" ? "default" : "ghost"}
          size="sm"
          className="shrink-0 whitespace-nowrap"
          onClick={() => setView("sprint")}
        >
          <Kanban className="w-4 h-4 mr-2" /> Tablero
        </Button>
        <Button
          variant={view === "all" ? "default" : "ghost"}
          size="sm"
          className="shrink-0 whitespace-nowrap"
          onClick={() => setView("all")}
        >
          <List className="w-4 h-4 mr-2" /> Todas
        </Button>
        <Button
          variant={view === "calendar" ? "default" : "ghost"}
          size="sm"
          className="shrink-0 whitespace-nowrap"
          onClick={() => setView("calendar")}
        >
          <CalendarDays className="w-4 h-4 mr-2" /> Calendario
        </Button>
        <Button
          variant={view === "weekly" ? "default" : "ghost"}
          size="sm"
          className="shrink-0 whitespace-nowrap"
          onClick={() => setView("weekly")}
        >
          <Calendar className="w-4 h-4 mr-2" /> Semana
        </Button>
        <Button
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
              <TableHead><span className="inline-flex items-center gap-1">Est / Real <InfoTooltip content="Estimado: minutos previstos al crear la tarea. Real: minutos declarados al cerrarla. Para horas fichadas con el cronómetro, mira la columna Tiempo/Timer." /></span></TableHead>
              <TableHead>Fecha limite</TableHead>
              <TableHead>Tiempo</TableHead>
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
              <TableHead className="w-10">
                <input
                  type="checkbox"
                  checked={allTasksSelected}
                  onChange={toggleAllTasks}
                  className="rounded border-border"
                />
              </TableHead>
              <SortableTableHead sortKey="title" currentSort={taskSortConfig} onSort={requestTaskSort}>Título</SortableTableHead>
              <SortableTableHead sortKey="client_name" currentSort={taskSortConfig} onSort={requestTaskSort}>Cliente</SortableTableHead>
              <SortableTableHead sortKey="priority" currentSort={taskSortConfig} onSort={requestTaskSort}>Prioridad</SortableTableHead>
              <TableHead>Asignado</TableHead>
              <SortableTableHead sortKey="status" currentSort={taskSortConfig} onSort={requestTaskSort}>Estado</SortableTableHead>
              <TableHead><span className="inline-flex items-center gap-1">Est / Real <InfoTooltip content="Estimado: minutos previstos al crear la tarea. Real: minutos declarados al cerrarla. Para horas fichadas con el cronómetro, mira la columna Tiempo/Timer." /></span></TableHead>
              <SortableTableHead sortKey="due_date" currentSort={taskSortConfig} onSort={requestTaskSort}>Fecha limite</SortableTableHead>
              <TableHead>Timer</TableHead>
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
                <TableRow key={t.id} className={rowHighlight}>
                  <TableCell>
                    <input
                      type="checkbox"
                      checked={isTaskSelected(t.id)}
                      onChange={() => toggleTask(t.id)}
                      className="rounded border-border"
                    />
                  </TableCell>
                  <TableCell className="font-medium">
                    <span className="inline-flex items-center gap-1">
                      {t.recurring_parent_id && <Repeat className="w-3 h-3 text-muted-foreground shrink-0" aria-label="Recurrente" />}
                      {t.title}
                    </span>
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
                  <TableCell>{priorityBadge(t.priority)}</TableCell>
                  <TableCell className={qaFilter === "unassigned" && QA_unassigned ? "text-destructive font-bold" : ""}>
                    {t.assigned_user_name || (QA_unassigned && qaFilter === "unassigned" ? "⚠️ Faltante" : "-")}
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
                    <Select
                      value={taskStatusPresentation(t.status, t.scheduled_date).group}
                      onChange={(e) => {
                        const next = e.target.value as TaskStatus
                        if (next === "waiting") {
                          openEdit(t, "waiting")
                          return
                        }
                        updateMutation.mutate({ id: t.id, data: { status: next === "completed" && sendsForReview(t) ? "in_review" : next } })
                      }}
                      className="h-7 text-xs w-32 py-0"
                    >
                      <option value="pending">Pendiente</option>
                      <option value="in_progress">En curso</option>
                      <option value="waiting">En espera…</option>
                      <option value="in_review">En revisión</option>
                      <option value="completed">{sendsForReview(t) ? "Enviar a revisión" : "Hecho"}</option>
                    </Select>
                    </div>
                  </TableCell>
                  <TableCell className="text-xs mono">
                    {est || real ? (
                      <span>
                        {est ? formatMinutes(est) : "-"}
                        {" / "}
                        {real ? formatMinutes(real) : "-"}
                        {diff !== null && diff !== 0 && (
                          <span className={diff > 0 ? "text-red-400 ml-1" : "text-green-400 ml-1"}>
                            ({diff > 0 ? "+" : ""}{formatMinutes(Math.abs(diff))})
                          </span>
                        )}
                      </span>
                    ) : (
                      <span className={qaFilter === "no_estimate" && QA_noestimate ? "text-destructive font-bold" : ""}>
                        {QA_noestimate && qaFilter === "no_estimate" ? "⚠️ 0" : "-"}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className={`mono ${(qaFilter === "no_date" && QA_nodate) || (qaFilter === "overdue" && QA_overdue)
                      ? "text-destructive font-bold" : ""
                    }`}>
                    {t.due_date ? formatCivilDate(t.due_date) : (QA_nodate && qaFilter === "no_date" ? "⚠️ Sin planificar" : "-")}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <TimerButton taskId={t.id} />
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setTimeLogTask(t)}
                        title="Ver registro de tiempo"
                      >
                        <Clock className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="icon" aria-label="Editar tarea" onClick={() => openEdit(t)}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" aria-label="Eliminar tarea" onClick={() => setDeleteId(t.id)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
            {tasks.length === 0 && (
              <EmptyTableState colSpan={10} icon={CheckSquare} title="Sin tareas" description="Crea tareas, asígnalas y trackea con timer integrado." />
            )}
          </TableBody>
        </Table>
      ) : null}

      {(view === "all" || view === "sprint" || view === "weekly" || view === "calendar") && (
        <Pagination page={page} pageSize={pageSize} total={tasksData?.total ?? 0} onPageChange={setPage} />
      )}

      {/* Conditional Rendering of Views */}
      {!isLoading && !agendaLoading && view === "my_day" && (
        plannedAgenda.isError || carryoverAgenda.isError || unplannedAgenda.isError || completedAgenda.isError ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center">
            <p className="font-medium">No hemos podido cargar tus tareas. Reintenta.</p>
            <Button variant="outline" className="mt-3" onClick={() => { plannedAgenda.refetch(); carryoverAgenda.refetch(); unplannedAgenda.refetch(); completedAgenda.refetch() }}>Reintentar</Button>
          </div>
        ) : (
          <MyDayView
            planned={agendaData(plannedAgenda)}
            carryover={agendaData(carryoverAgenda)}
            unplanned={agendaData(unplannedAgenda)}
            completed={agendaData(completedAgenda)}
            retired={agendaData(retiredTasks)}
            retiredLoading={retiredTasks.isLoading}
            retiredError={retiredTasks.isError}
            onRetryRetired={() => void retiredTasks.refetch()}
            isLoadingMore={plannedAgenda.isFetchingNextPage || carryoverAgenda.isFetchingNextPage || unplannedAgenda.isFetchingNextPage || completedAgenda.isFetchingNextPage || retiredTasks.isFetchingNextPage}
            onLoadMore={(section) => ({ planned: plannedAgenda, carryover: carryoverAgenda, unplanned: unplannedAgenda, completed: completedAgenda, retired: retiredTasks }[section].fetchNextPage())}
            onStatusChange={(id, status) => {
              const task = [...agendaData(plannedAgenda).items, ...agendaData(carryoverAgenda).items, ...agendaData(unplannedAgenda).items, ...agendaData(completedAgenda).items].find((item) => item.id === id)
              updateMutation.mutate({ id, data: { status: status === "completed" && task && sendsForReview(task) ? "in_review" : status } })
            }}
            onOpenEdit={openEdit}
            canCompleteReviewedTask={(task) => !!(isAdmin || task.project_review_owner_id === user?.id)}
            onReviewCarryover={setCarryoverTask}
            canWrite={canWriteTasks}
          />
        )
      )}

      {!isLoading && !isTasksError && view === "sprint" && (
        <KanbanBoard
          tasks={tasks}
          onStatusChange={(taskId, newStatus) => {
            const task = tasks.find((item) => item.id === taskId)
            updateMutation.mutate({ id: taskId, data: { status: newStatus === "completed" && task && sendsForReview(task) ? "in_review" : newStatus } })
          }}
          onOpenEdit={openEdit}
        />
      )}

      {!isLoading && !isTasksError && view === "calendar" && (
        <TaskCalendarView
          tasks={allTasks}
          year={calMonth.year}
          month={calMonth.month}
          onPrev={() => { reset(); setCalMonth(({ year, month }) => month === 0 ? { year: year - 1, month: 11 } : { year, month: month - 1 }) }}
          onNext={() => { reset(); setCalMonth(({ year, month }) => month === 11 ? { year: year + 1, month: 0 } : { year, month: month + 1 }) }}
          onOpenEdit={openEdit}
        />
      )}

      {!isLoading && !isTasksError && view === "weekly" && (
        <WeeklyPlannerView
          tasks={allTasks}
          weekOffset={weekOffset}
          onWeekOffsetChange={(offset) => { setWeekOffset(offset); reset() }}
          onScheduleChange={(taskId, date) => scheduleMutation.mutate({ id: taskId, scheduled_date: date })}
          onOpenEdit={openEdit}
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
                      {t.recurrence_pattern === "daily" && "Diaria (L-V)"}
                      {t.recurrence_pattern === "weekly" && `Semanal · ${["Lun", "Mar", "Mié", "Jue", "Vie"][t.recurrence_day ?? 0]}`}
                      {t.recurrence_pattern === "biweekly" && `Cada dos semanas · ${["Lun", "Mar", "Mié", "Jue", "Vie"][t.recurrence_day ?? 0]}`}
                      {t.recurrence_pattern === "monthly" && `Mensual · Día ${t.recurrence_day}`}
                      {t.recurrence_summary && <><p className="mt-1 text-xs text-muted-foreground">{t.recurrence_summary.label}{t.recurrence_summary.reason ? ` · ${t.recurrence_summary.reason}` : ""}</p>{t.recurrence_summary.next_dates.length > 0 && <p className="mt-1 text-xs text-muted-foreground">Próximas: {t.recurrence_summary.next_dates.join(" · ")}</p>}</>}
                    </TableCell>
                    <TableCell>{t.client_name ?? <span className="text-muted-foreground">Sin cliente</span>}</TableCell>
                    <TableCell>{t.assigned_user_name}</TableCell>
                    <TableCell>{priorityBadge(t.priority)}</TableCell>
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
        description="Esta acción no se puede deshacer. Se eliminará la tarea permanentemente."
        onConfirm={() => {
          if (deleteId !== null) {
            deleteMutation.mutate(deleteId)
            setDeleteId(null)
          }
        }}
      />

      {/* Bulk Action Bar */}
      <BulkActionBar selectedCount={selectedTaskCount} onClear={clearTaskSelection}>
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
        <Button
          size="sm"
          variant="destructive"
          onClick={() => setBulkDeleteOpen(true)}
          disabled={bulkDeleteMutation.isPending}
        >
          Eliminar
        </Button>
      </BulkActionBar>

      <ConfirmDialog
        open={bulkDeleteOpen}
        onOpenChange={setBulkDeleteOpen}
        title="Eliminar tareas"
        description={`Esta acción no se puede deshacer. Se eliminarán ${selectedTaskCount} tareas permanentemente.`}
        confirmLabel="Eliminar"
        onConfirm={() => bulkDeleteMutation.mutate([...selectedTaskIds])}
      />
    </div>
  )
}
