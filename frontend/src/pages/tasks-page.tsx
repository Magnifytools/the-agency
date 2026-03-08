import { useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { tasksApi, clientsApi, categoriesApi, usersApi } from "@/lib/api"
import type { Task, TaskCreate, TaskStatus, TaskPriority } from "@/lib/types"
import { usePagination } from "@/hooks/use-pagination"
import { Pagination } from "@/components/ui/pagination"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Plus, Pencil, Trash2, Clock, Calendar, Kanban, List, CheckSquare, Loader2, CalendarDays, ChevronDown, ChevronUp, MessageSquare, Paperclip, Download, Send } from "lucide-react"
import { useTableSort } from "@/hooks/use-table-sort"
import { useBulkSelect } from "@/hooks/use-bulk-select"
import { SortableTableHead } from "@/components/ui/sortable-table-head"
import { BulkActionBar } from "@/components/ui/bulk-action-bar"
import { EmptyTableState } from "@/components/ui/empty-state"
import { SkeletonTableRow } from "@/components/ui/skeleton"
import { TimerButton } from "@/components/timer/timer-button"
import { TimeLogDialog } from "@/components/timer/time-log-dialog"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { MyDayView } from "@/components/tasks/my-day-view"
import { KanbanBoard } from "@/components/tasks/kanban-board"
import { TaskCalendarView } from "@/components/tasks/task-calendar-view"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

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

export default function TasksPage() {
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const { page, pageSize, setPage, reset } = usePagination(25)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Task | null>(null)
  const [timeLogTask, setTimeLogTask] = useState<Task | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [view, setView] = useState<"my_day" | "sprint" | "all" | "calendar">("my_day")
  const [calMonth, setCalMonth] = useState(() => {
    const d = new Date(); return { year: d.getFullYear(), month: d.getMonth() }
  })

  const [depSearch, setDepSearch] = useState("")

  // Filters
  const [filterClient, setFilterClient] = useState<string>("")
  const [filterCategory, setFilterCategory] = useState<string>("")
  const [filterStatus, setFilterStatus] = useState<string>("")
  const [filterPriority, setFilterPriority] = useState<string>("")
  const [filterAssigned, setFilterAssigned] = useState<string>("")

  // QA Health Filters — initialise from URL param if present
  const urlQaFilter = searchParams.get("qaFilter") as "none" | "unassigned" | "no_date" | "no_estimate" | "overdue" | null
  const [qaFilter, setQaFilter] = useState<"none" | "unassigned" | "no_date" | "no_estimate" | "overdue">(
    urlQaFilter ?? "none"
  )
  const [bulkStatus, setBulkStatus] = useState("")

  // Checklist state
  const [newChecklistText, setNewChecklistText] = useState("")
  // Comments & attachments state
  const [newCommentText, setNewCommentText] = useState("")
  const [attachmentFileRef, setAttachmentFileRef] = useState<HTMLInputElement | null>(null)
  // Dialog — collapsible assignment fields
  const [showAssignmentFields, setShowAssignmentFields] = useState(true)

  const { data: tasksData, isLoading } = useQuery({
    queryKey: ["tasks", filterClient, filterCategory, filterStatus, filterPriority, filterAssigned, page, pageSize],
    queryFn: () =>
      tasksApi.list({
        client_id: filterClient ? Number(filterClient) : undefined,
        category_id: filterCategory ? Number(filterCategory) : undefined,
        status: filterStatus || undefined,
        priority: filterPriority || undefined,
        assigned_to: filterAssigned ? Number(filterAssigned) : undefined,
        page,
        page_size: pageSize,
      }),
  })
  const allTasks = tasksData?.items ?? []

  // Apply QA Health Filters on the frontend
  const now = new Date()
  const tasks = allTasks.filter(t => {
    if (qaFilter === "none") return true
    if (t.status === "completed") return false // QA mostly applies to active tasks

    if (qaFilter === "unassigned") return t.assigned_to === null
    if (qaFilter === "no_date") return t.due_date === null
    if (qaFilter === "no_estimate") return t.estimated_minutes === null
    if (qaFilter === "overdue") {
      if (!t.due_date) return false
      return new Date(t.due_date) < now
    }
    return true
  })

  const { sortedItems: sortedTasks, sortConfig: taskSortConfig, requestSort: requestTaskSort } = useTableSort(tasks)
  const { selectedIds: selectedTaskIds, isSelected: isTaskSelected, toggleItem: toggleTask, toggleAll: toggleAllTasks, clearSelection: clearTaskSelection, selectedCount: selectedTaskCount, allSelected: allTasksSelected } = useBulkSelect(tasks)

  const bulkStatusMutation = useMutation({
    mutationFn: async ({ ids, status }: { ids: number[]; status: string }) => {
      const results = await Promise.allSettled(ids.map((id) => tasksApi.update(id, { status: status as TaskStatus })))
      const fulfilled = results.filter((r) => r.status === "fulfilled").length
      const rejected = results.length - fulfilled
      return { fulfilled, rejected }
    },
    onSuccess: ({ fulfilled, rejected }) => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      clearTaskSelection()
      setBulkStatus("")
      if (rejected === 0) {
        toast.success(`${fulfilled} tareas actualizadas`)
      } else {
        toast.warning(`${fulfilled} actualizadas, ${rejected} fallaron`)
      }
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar tareas")),
  })

  const bulkDeleteMutation = useMutation({
    mutationFn: async (ids: number[]) => {
      const results = await Promise.allSettled(ids.map((id) => tasksApi.delete(id)))
      const fulfilled = results.filter((r) => r.status === "fulfilled").length
      const rejected = results.length - fulfilled
      return { fulfilled, rejected }
    },
    onSuccess: ({ fulfilled, rejected }) => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      clearTaskSelection()
      if (rejected === 0) {
        toast.success(`${fulfilled} tareas eliminadas`)
      } else {
        toast.warning(`${fulfilled} eliminadas, ${rejected} fallaron`)
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

  const createMutation = useMutation({
    mutationFn: (data: TaskCreate) => tasksApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      closeDialog()
      toast.success("Tarea creada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear tarea")),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<TaskCreate> }) => tasksApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      closeDialog()
      toast.success("Tarea actualizada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar tarea")),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => tasksApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks"] })
      toast.success("Tarea eliminada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar tarea")),
  })


  // Checklist query — enabled only when editing an existing task
  const { data: checklistItems = [], refetch: refetchChecklist } = useQuery({
    queryKey: ["task-checklist", editing?.id],
    queryFn: () => tasksApi.checklist.list(editing!.id),
    enabled: !!editing?.id,
  })

  const addChecklistMut = useMutation({
    mutationFn: (text: string) => tasksApi.checklist.create(editing!.id, text),
    onSuccess: () => { refetchChecklist(); setNewChecklistText("") },
  })
  const toggleChecklistMut = useMutation({
    mutationFn: ({ id, is_done }: { id: number; is_done: boolean }) =>
      tasksApi.checklist.update(editing!.id, id, { is_done }),
    onSuccess: () => { refetchChecklist(); queryClient.invalidateQueries({ queryKey: ["tasks"] }) },
  })
  const deleteChecklistMut = useMutation({
    mutationFn: (id: number) => tasksApi.checklist.delete(editing!.id, id),
    onSuccess: () => refetchChecklist(),
  })
  // Comments queries/mutations
  const { data: comments = [], refetch: refetchComments } = useQuery({
    queryKey: ["task-comments", editing?.id],
    queryFn: () => tasksApi.comments.list(editing!.id),
    enabled: !!editing?.id,
  })
  const addCommentMut = useMutation({
    mutationFn: (text: string) => tasksApi.comments.create(editing!.id, text),
    onSuccess: () => { refetchComments(); setNewCommentText("") },
  })
  const deleteCommentMut = useMutation({
    mutationFn: (id: number) => tasksApi.comments.delete(editing!.id, id),
    onSuccess: () => refetchComments(),
  })

  // Attachments queries/mutations
  const { data: attachments = [], refetch: refetchAttachments } = useQuery({
    queryKey: ["task-attachments", editing?.id],
    queryFn: () => tasksApi.attachments.list(editing!.id),
    enabled: !!editing?.id,
  })
  const uploadAttachmentMut = useMutation({
    mutationFn: (file: File) => tasksApi.attachments.upload(editing!.id, file),
    onSuccess: () => refetchAttachments(),
    onError: (err) => toast.error(getErrorMessage(err, "Error al subir archivo")),
  })
  const deleteAttachmentMut = useMutation({
    mutationFn: (id: number) => tasksApi.attachments.delete(editing!.id, id),
    onSuccess: () => refetchAttachments(),
  })
  const handleDownloadAttachment = async (attachmentId: number, filename: string) => {
    try {
      const blob = await tasksApi.attachments.download(editing!.id, attachmentId)
      const url = URL.createObjectURL(blob as Blob)
      const a = document.createElement("a")
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast.error(getErrorMessage(err, "Error al descargar"))
    }
  }

  const closeDialog = () => {
    setDialogOpen(false)
    setEditing(null)
    setNewChecklistText("")
    setNewCommentText("")
  }

  const openCreate = () => {
    setEditing(null)
    setShowAssignmentFields(true)
    setDialogOpen(true)
  }

  const openEdit = (task: Task) => {
    setEditing(task)
    setShowAssignmentFields(true)
    setDialogOpen(true)
  }

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    const clientIdStr = fd.get("client_id") as string
    if (!clientIdStr) {
      // client_id may be inside the collapsed section — expand it and alert
      setShowAssignmentFields(true)
      toast.error("Selecciona un cliente antes de guardar")
      return
    }
    const data: TaskCreate = {
      title: fd.get("title") as string,
      description: (fd.get("description") as string) || null,
      status: (fd.get("status") as TaskStatus) || "pending",
      priority: (fd.get("priority") as TaskPriority) || "medium",
      estimated_minutes: fd.get("estimated_minutes") ? Number(fd.get("estimated_minutes")) : null,
      actual_minutes: fd.get("actual_minutes") ? Number(fd.get("actual_minutes")) : null,
      due_date: (fd.get("due_date") as string) || null,
      client_id: Number(clientIdStr),
      category_id: fd.get("category_id") ? Number(fd.get("category_id")) : null,
      assigned_to: fd.get("assigned_to") ? Number(fd.get("assigned_to")) : null,
      depends_on: fd.get("depends_on") ? Number(fd.get("depends_on")) : null,
      scheduled_date: (fd.get("scheduled_date") as string) || null,
      waiting_for: (fd.get("waiting_for") as string) || null,
      follow_up_date: (fd.get("follow_up_date") as string) || null,
    }
    if (editing) {
      updateMutation.mutate({ id: editing.id, data })
    } else {
      createMutation.mutate(data)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold uppercase tracking-wide">Tareas</h2>
          {tasksData && <p className="text-sm text-muted-foreground mt-1">{tasksData.total} tareas · {tasks.filter(t => t.status === "in_progress").length} en curso</p>}
        </div>
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4 mr-2" /> Nueva tarea
        </Button>
      </div>

      {/* Filters */}
      <div className="flex gap-3">
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
          <option value="">Todos los estados</option>
          <option value="backlog">Backlog</option>
          <option value="pending">Pendiente</option>
          <option value="in_progress">En curso</option>
          <option value="waiting">En espera</option>
          <option value="in_review">En revisión</option>
          <option value="completed">Completada</option>
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
      </div>

      {/* QA Health Filters */}
      <div className="flex gap-2 flex-wrap mb-4">
        <Button
          variant={qaFilter === "unassigned" ? "secondary" : "outline"}
          size="sm"
          onClick={() => setQaFilter(f => f === "unassigned" ? "none" : "unassigned")}
          className="text-xs h-8 bg-orange-500/10 hover:bg-orange-500/20 text-orange-600 border-orange-500/20"
        >
          ⚠️ Sin Asignar
        </Button>
        <Button
          variant={qaFilter === "no_date" ? "secondary" : "outline"}
          size="sm"
          onClick={() => setQaFilter(f => f === "no_date" ? "none" : "no_date")}
          className="text-xs h-8 bg-blue-500/10 hover:bg-blue-500/20 text-blue-600 border-blue-500/20"
        >
          ⚠️ Sin Fechas
        </Button>
        <Button
          variant={qaFilter === "no_estimate" ? "secondary" : "outline"}
          size="sm"
          onClick={() => setQaFilter(f => f === "no_estimate" ? "none" : "no_estimate")}
          className="text-xs h-8 bg-purple-500/10 hover:bg-purple-500/20 text-purple-600 border-purple-500/20"
        >
          ⚠️ Sin Estimación
        </Button>
        <Button
          variant={qaFilter === "overdue" ? "secondary" : "outline"}
          size="sm"
          onClick={() => setQaFilter(f => f === "overdue" ? "none" : "overdue")}
          className="text-xs h-8 bg-red-500/10 hover:bg-red-500/20 text-red-600 border-red-500/20"
        >
          🔥 Atrasadas
        </Button>
        {qaFilter !== "none" && (
          <Button variant="ghost" size="sm" onClick={() => setQaFilter("none")} className="text-xs h-8 text-muted-foreground">
            Limpiar filtros QA
          </Button>
        )}
      </div>

      <div className="flex items-center space-x-2 bg-muted/30 p-1 w-full sm:w-fit rounded-lg mb-6 border border-border">
        <Button
          variant={view === "my_day" ? "default" : "ghost"}
          size="sm"
          className="flex-1 sm:w-32"
          onClick={() => setView("my_day")}
        >
          <Calendar className="w-4 h-4 mr-2" /> Mi Día
        </Button>
        <Button
          variant={view === "sprint" ? "default" : "ghost"}
          size="sm"
          className="flex-1 sm:w-32"
          onClick={() => setView("sprint")}
        >
          <Kanban className="w-4 h-4 mr-2" /> Tablero
        </Button>
        <Button
          variant={view === "all" ? "default" : "ghost"}
          size="sm"
          className="flex-1 sm:w-32"
          onClick={() => setView("all")}
        >
          <List className="w-4 h-4 mr-2" /> Todas
        </Button>
        <Button
          variant={view === "calendar" ? "default" : "ghost"}
          size="sm"
          className="flex-1 sm:w-32"
          onClick={() => setView("calendar")}
        >
          <CalendarDays className="w-4 h-4 mr-2" /> Calendario
        </Button>
      </div>

      {/* Table & Planner */}
      {isLoading ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10" />
              <TableHead>Título</TableHead>
              <TableHead>Cliente</TableHead>
              <TableHead>Prioridad</TableHead>
              <TableHead>Asignado</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead>Est / Real</TableHead>
              <TableHead>Fecha limite</TableHead>
              <TableHead>Tiempo</TableHead>
              <TableHead className="w-24">Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Array.from({ length: 5 }).map((_, i) => <SkeletonTableRow key={i} cols={10} />)}
          </TableBody>
        </Table>
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
              <TableHead>Est / Real</TableHead>
              <SortableTableHead sortKey="due_date" currentSort={taskSortConfig} onSort={requestTaskSort}>Fecha limite</SortableTableHead>
              <TableHead>Timer</TableHead>
              <TableHead className="w-24">Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedTasks.map((t) => {
              const QA_unassigned = t.assigned_to === null;
              const QA_nodate = t.due_date === null;
              const QA_noestimate = t.estimated_minutes === null;
              const QA_overdue = t.due_date && new Date(t.due_date) < now;

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
                    {t.title}
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
                    <Select
                      value={t.status}
                      onChange={(e) => updateMutation.mutate({ id: t.id, data: { status: e.target.value as TaskStatus } })}
                      className="h-7 text-xs w-32 py-0"
                    >
                      <option value="backlog">Backlog</option>
                      <option value="pending">Pendiente</option>
                      <option value="in_progress">En curso</option>
                      <option value="waiting">En espera</option>
                      <option value="in_review">En revisión</option>
                      <option value="completed">Completada</option>
                    </Select>
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
                    {t.due_date ? new Date(t.due_date).toLocaleDateString("es-ES") : (QA_nodate && qaFilter === "no_date" ? "⚠️ Sin fecha" : "-")}
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

      {view === "all" && (
        <Pagination page={page} pageSize={pageSize} total={tasksData?.total ?? 0} onPageChange={setPage} />
      )}

      {/* Conditional Rendering of Views */}
      {!isLoading && view === "my_day" && (
        <MyDayView
          tasks={tasks}
          onStatusChange={(id, status) => updateMutation.mutate({ id, data: { status } })}
          onOpenEdit={openEdit}
        />
      )}

      {!isLoading && view === "sprint" && (
        <KanbanBoard
          tasks={tasks}
          onStatusChange={(taskId, newStatus) => updateMutation.mutate({ id: taskId, data: { status: newStatus } })}
          onOpenEdit={openEdit}
        />
      )}

      {!isLoading && view === "calendar" && (
        <TaskCalendarView
          tasks={allTasks}
          year={calMonth.year}
          month={calMonth.month}
          onPrev={() => setCalMonth(({ year, month }) => month === 0 ? { year: year - 1, month: 11 } : { year, month: month - 1 })}
          onNext={() => setCalMonth(({ year, month }) => month === 11 ? { year: year + 1, month: 0 } : { year, month: month + 1 })}
          onOpenEdit={openEdit}
        />
      )}

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogHeader>
          <DialogTitle>{editing ? "Editar tarea" : "Nueva tarea"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Title */}
          <div className="space-y-2">
            <Label htmlFor="title">Título *</Label>
            <Input id="title" name="title" defaultValue={editing?.title ?? ""} required />
          </div>

          {/* Description — prominent, tall */}
          <div className="space-y-2">
            <Label htmlFor="description">Descripción</Label>
            <Textarea
              id="description"
              name="description"
              defaultValue={editing?.description ?? ""}
              rows={6}
              className="resize-y min-h-[120px]"
              placeholder="Contenido de la nota o descripción de la tarea..."
            />
          </div>

          {/* Datos de asignación — collapsible */}
          <div className="border border-border/60 rounded-lg overflow-hidden">
            <button
              type="button"
              className="w-full flex items-center justify-between px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
              onClick={() => setShowAssignmentFields((v) => !v)}
            >
              <span>Datos de asignación</span>
              {showAssignmentFields
                ? <ChevronUp className="h-4 w-4" />
                : <ChevronDown className="h-4 w-4" />}
            </button>
            {/* Fields stay in DOM (so form values are always submitted) but hidden visually */}
            <div className={showAssignmentFields ? "p-3 pt-2 border-t border-border/60" : "hidden"}>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="client_id" className="text-xs">Cliente *</Label>
                  <Select id="client_id" name="client_id" defaultValue={editing?.client_id ?? ""}>
                    <option value="">Seleccionar...</option>
                    {clients.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="category_id" className="text-xs">Categoría</Label>
                  <Select id="category_id" name="category_id" defaultValue={editing?.category_id ?? ""}>
                    <option value="">Sin categoría</option>
                    {categories.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="assigned_to" className="text-xs">Asignado a</Label>
                  <Select id="assigned_to" name="assigned_to" defaultValue={editing?.assigned_to ?? ""}>
                    <option value="">Sin asignar</option>
                    {users.map((u) => (
                      <option key={u.id} value={u.id}>{u.full_name}</option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="status" className="text-xs">Estado</Label>
                  <Select id="status" name="status" defaultValue={editing?.status ?? "pending"}>
                    <option value="backlog">Backlog</option>
                    <option value="pending">Pendiente</option>
                    <option value="in_progress">En curso</option>
                    <option value="waiting">En espera</option>
                    <option value="in_review">En revisión</option>
                    <option value="completed">Completada</option>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="priority" className="text-xs">Prioridad</Label>
                  <Select id="priority" name="priority" defaultValue={editing?.priority ?? "medium"}>
                    <option value="urgent">Urgente</option>
                    <option value="high">Alta</option>
                    <option value="medium">Media</option>
                    <option value="low">Baja</option>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="estimated_minutes" className="text-xs">Minutos estimados</Label>
                  <Input
                    id="estimated_minutes"
                    name="estimated_minutes"
                    type="number"
                    defaultValue={editing?.estimated_minutes ?? ""}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="actual_minutes" className="text-xs">Minutos reales</Label>
                  <Input
                    id="actual_minutes"
                    name="actual_minutes"
                    type="number"
                    defaultValue={editing?.actual_minutes ?? ""}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="due_date" className="text-xs">Fecha límite</Label>
                  <Input
                    id="due_date"
                    name="due_date"
                    type="date"
                    defaultValue={editing?.due_date ? editing.due_date.split("T")[0] : ""}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="scheduled_date" className="text-xs">Fecha planificada</Label>
                  <Input
                    id="scheduled_date"
                    name="scheduled_date"
                    type="date"
                    defaultValue={editing?.scheduled_date ?? ""}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="waiting_for" className="text-xs">En espera de</Label>
                  <Input
                    id="waiting_for"
                    name="waiting_for"
                    defaultValue={editing?.waiting_for ?? ""}
                    placeholder="Ej: respuesta del cliente"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="follow_up_date" className="text-xs">Fecha de seguimiento</Label>
                  <Input
                    id="follow_up_date"
                    name="follow_up_date"
                    type="date"
                    defaultValue={editing?.follow_up_date ?? ""}
                  />
                </div>
                <div className="space-y-1.5 col-span-2">
                  <Label htmlFor="depends_on" className="text-xs">Depende de <span className="text-muted-foreground">(opcional)</span></Label>
                  <Input
                    placeholder="Buscar tarea..."
                    value={depSearch}
                    onChange={(e) => setDepSearch(e.target.value)}
                    className="h-7 text-xs mb-1"
                  />
                  <Select id="depends_on" name="depends_on" defaultValue={editing?.depends_on ?? ""} className="max-h-40">
                    <option value="">Sin dependencia</option>
                    {allTasks
                      .filter((t) => t.id !== editing?.id)
                      .filter((t) => !depSearch || t.title.toLowerCase().includes(depSearch.toLowerCase()) || t.client_name?.toLowerCase().includes(depSearch.toLowerCase()))
                      .map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.client_name ? `[${t.client_name}] ` : ""}{t.title.length > 50 ? t.title.slice(0, 50) + "…" : t.title}
                        </option>
                      ))}
                  </Select>
                </div>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="flex items-center gap-2">
            {editing && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive hover:bg-destructive/10 gap-1.5"
                onClick={() => { setDeleteId(editing.id); closeDialog() }}
              >
                <Trash2 className="h-3.5 w-3.5" />
                Eliminar
              </Button>
            )}
            <div className="flex gap-2 ml-auto">
              <Button type="button" variant="outline" onClick={closeDialog}>
                Cancelar
              </Button>
              <Button type="submit">{editing ? "Guardar" : "Crear"}</Button>
            </div>
          </div>
        </form>

        {/* Subtasks / Checklist — only shown when editing an existing task */}
        {editing && (
          <div className="mt-4 border-t pt-4 space-y-3">
            <p className="text-sm font-semibold">
              Subtasks ({checklistItems.filter(i => i.is_done).length}/{checklistItems.length})
            </p>
            <div className="space-y-1.5">
              {checklistItems.map((item) => (
                <div key={item.id} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={item.is_done}
                    onChange={(e) => toggleChecklistMut.mutate({ id: item.id, is_done: e.target.checked })}
                    className="rounded border-border"
                  />
                  <span className={`text-sm flex-1 ${item.is_done ? "line-through text-muted-foreground" : ""}`}>
                    {item.text}
                  </span>
                  <Button variant="ghost" size="icon" className="h-6 w-6"
                    onClick={() => deleteChecklistMut.mutate(item.id)}>
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <Input
                value={newChecklistText}
                onChange={(e) => setNewChecklistText(e.target.value)}
                placeholder="Añadir subtask..."
                className="text-sm h-8"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newChecklistText.trim()) {
                    e.preventDefault()
                    addChecklistMut.mutate(newChecklistText.trim())
                  }
                }}
              />
              <Button size="sm" variant="outline" className="h-8"
                onClick={() => newChecklistText.trim() && addChecklistMut.mutate(newChecklistText.trim())}
                disabled={!newChecklistText.trim()}>
                <Plus className="h-3 w-3" />
              </Button>
            </div>
          </div>
        )}

        {/* Comments — only shown when editing an existing task */}
        {editing && (
          <div className="mt-4 border-t pt-4 space-y-3">
            <p className="text-sm font-semibold flex items-center gap-1.5">
              <MessageSquare className="h-3.5 w-3.5" /> Comentarios ({comments.length})
            </p>
            {comments.length > 0 && (
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {comments.map((c) => (
                  <div key={c.id} className="text-sm bg-muted/50 rounded p-2">
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium text-xs">{c.user_name ?? `User #${c.user_id}`}</span>
                      <div className="flex items-center gap-1">
                        <span className="text-xs text-muted-foreground">
                          {new Date(c.created_at).toLocaleDateString("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                        </span>
                        <Button variant="ghost" size="icon" className="h-5 w-5"
                          onClick={() => deleteCommentMut.mutate(c.id)}>
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                    <p className="text-sm whitespace-pre-wrap">{c.text}</p>
                  </div>
                ))}
              </div>
            )}
            <div className="flex gap-2">
              <Input
                value={newCommentText}
                onChange={(e) => setNewCommentText(e.target.value)}
                placeholder="Añadir comentario..."
                className="text-sm h-8"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && newCommentText.trim()) {
                    e.preventDefault()
                    addCommentMut.mutate(newCommentText.trim())
                  }
                }}
              />
              <Button size="sm" variant="outline" className="h-8"
                onClick={() => newCommentText.trim() && addCommentMut.mutate(newCommentText.trim())}
                disabled={!newCommentText.trim() || addCommentMut.isPending}>
                <Send className="h-3 w-3" />
              </Button>
            </div>
          </div>
        )}

        {/* Attachments — only shown when editing an existing task */}
        {editing && (
          <div className="mt-4 border-t pt-4 space-y-3">
            <p className="text-sm font-semibold flex items-center gap-1.5">
              <Paperclip className="h-3.5 w-3.5" /> Adjuntos ({attachments.length})
            </p>
            {attachments.length > 0 && (
              <div className="space-y-1.5">
                {attachments.map((a) => (
                  <div key={a.id} className="flex items-center gap-2 text-sm bg-muted/50 rounded px-2 py-1.5">
                    <Paperclip className="h-3 w-3 shrink-0" />
                    <span className="flex-1 truncate">{a.name}</span>
                    <span className="text-xs text-muted-foreground shrink-0">
                      {a.size_bytes < 1024 ? `${a.size_bytes} B` : a.size_bytes < 1048576 ? `${Math.round(a.size_bytes / 1024)} KB` : `${(a.size_bytes / 1048576).toFixed(1)} MB`}
                    </span>
                    <Button variant="ghost" size="icon" className="h-6 w-6"
                      onClick={() => handleDownloadAttachment(a.id, a.name)}>
                      <Download className="h-3 w-3" />
                    </Button>
                    <Button variant="ghost" size="icon" className="h-6 w-6"
                      onClick={() => deleteAttachmentMut.mutate(a.id)}>
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
            <div>
              <input
                type="file"
                className="hidden"
                ref={(el) => setAttachmentFileRef(el)}
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) {
                    uploadAttachmentMut.mutate(file)
                    e.target.value = ""
                  }
                }}
              />
              <Button size="sm" variant="outline" className="h-8"
                onClick={() => attachmentFileRef?.click()}
                disabled={uploadAttachmentMut.isPending}>
                {uploadAttachmentMut.isPending ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Plus className="h-3 w-3 mr-1" />}
                Subir archivo
              </Button>
            </div>
          </div>
        )}
      </Dialog>

      {/* Time Log Dialog */}
      {timeLogTask && (
        <TimeLogDialog
          taskId={timeLogTask.id}
          taskTitle={timeLogTask.title}
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
          onChange={(e) => setBulkStatus(e.target.value)}
          className="h-8 text-xs w-36"
        >
          <option value="">Cambiar estado</option>
          <option value="backlog">Backlog</option>
          <option value="pending">Pendiente</option>
          <option value="in_progress">En curso</option>
          <option value="waiting">En espera</option>
          <option value="in_review">En revisión</option>
          <option value="completed">Completada</option>
        </Select>
        {bulkStatus && (
          <Button
            size="sm"
            onClick={() => bulkStatusMutation.mutate({ ids: [...selectedTaskIds], status: bulkStatus })}
            disabled={bulkStatusMutation.isPending}
          >
            {bulkStatusMutation.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Aplicar"}
          </Button>
        )}
        <Button
          size="sm"
          variant="destructive"
          onClick={() => {
            if (confirm(`Eliminar ${selectedTaskCount} tareas?`)) {
              bulkDeleteMutation.mutate([...selectedTaskIds])
            }
          }}
          disabled={bulkDeleteMutation.isPending}
        >
          Eliminar
        </Button>
      </BulkActionBar>
    </div>
  )
}
