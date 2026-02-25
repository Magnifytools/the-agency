import { useState } from "react"
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
import { Plus, Pencil, Trash2, Clock, Calendar, Kanban, List, CheckSquare } from "lucide-react"
import { EmptyTableState } from "@/components/ui/empty-state"
import { TimerButton } from "@/components/timer/timer-button"
import { TimeLogDialog } from "@/components/timer/time-log-dialog"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { MyDayView } from "@/components/tasks/my-day-view"
import { KanbanBoard } from "@/components/tasks/kanban-board"
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
  const { page, pageSize, setPage, reset } = usePagination(25)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Task | null>(null)
  const [timeLogTask, setTimeLogTask] = useState<Task | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [view, setView] = useState<"my_day" | "sprint" | "all">("my_day")

  // Filters
  const [filterClient, setFilterClient] = useState<string>("")
  const [filterCategory, setFilterCategory] = useState<string>("")
  const [filterStatus, setFilterStatus] = useState<string>("")
  const [filterPriority, setFilterPriority] = useState<string>("")
  const [filterAssigned, setFilterAssigned] = useState<string>("")

  // QA Health Filters
  const [qaFilter, setQaFilter] = useState<"none" | "unassigned" | "no_date" | "no_estimate" | "overdue">("none")

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

  const closeDialog = () => {
    setDialogOpen(false)
    setEditing(null)
  }

  const openCreate = () => {
    setEditing(null)
    setDialogOpen(true)
  }

  const openEdit = (task: Task) => {
    setEditing(task)
    setDialogOpen(true)
  }

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    const data: TaskCreate = {
      title: fd.get("title") as string,
      description: (fd.get("description") as string) || null,
      status: (fd.get("status") as TaskStatus) || "pending",
      priority: (fd.get("priority") as TaskPriority) || "medium",
      estimated_minutes: fd.get("estimated_minutes") ? Number(fd.get("estimated_minutes")) : null,
      actual_minutes: fd.get("actual_minutes") ? Number(fd.get("actual_minutes")) : null,
      due_date: (fd.get("due_date") as string) || null,
      client_id: Number(fd.get("client_id")),
      category_id: fd.get("category_id") ? Number(fd.get("category_id")) : null,
      assigned_to: fd.get("assigned_to") ? Number(fd.get("assigned_to")) : null,
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
          <option value="pending">Pendiente</option>
          <option value="in_progress">En curso</option>
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
      </div>

      {/* Table & Planner */}
      {isLoading ? (
        <p className="text-muted-foreground">Cargando...</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Titulo</TableHead>
              <TableHead>Cliente</TableHead>
              <TableHead>Prioridad</TableHead>
              <TableHead>Asignado</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead>Est / Real</TableHead>
              <TableHead>Fecha limite</TableHead>
              <TableHead>Timer</TableHead>
              <TableHead className="w-24">Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tasks.map((t) => {
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
                  <TableCell className="font-medium">{t.title}</TableCell>
                  <TableCell>{t.client_name || "-"}</TableCell>
                  <TableCell>{priorityBadge(t.priority)}</TableCell>
                  <TableCell className={qaFilter === "unassigned" && QA_unassigned ? "text-destructive font-bold" : ""}>
                    {t.assigned_user_name || (QA_unassigned && qaFilter === "unassigned" ? "⚠️ Faltante" : "-")}
                  </TableCell>
                  <TableCell>
                    <Select
                      value={t.status}
                      onChange={(e) => updateMutation.mutate({ id: t.id, data: { status: e.target.value as TaskStatus } })}
                      className="h-7 text-xs w-28 py-0"
                    >
                      <option value="pending">Pendiente</option>
                      <option value="in_progress">En curso</option>
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
                      <Button variant="ghost" size="icon" onClick={() => openEdit(t)}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => setDeleteId(t.id)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
            {tasks.length === 0 && (
              <EmptyTableState colSpan={9} icon={CheckSquare} title="Sin tareas" description="Crea tareas, asígnalas y trackea con timer integrado." />
            )}
          </TableBody>
        </Table>
      )}

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

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogHeader>
          <DialogTitle>{editing ? "Editar tarea" : "Nueva tarea"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2 col-span-2">
              <Label htmlFor="title">Titulo *</Label>
              <Input id="title" name="title" defaultValue={editing?.title ?? ""} required />
            </div>
            <div className="space-y-2">
              <Label htmlFor="client_id">Cliente *</Label>
              <Select id="client_id" name="client_id" defaultValue={editing?.client_id ?? ""} required>
                <option value="">Seleccionar...</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="category_id">Categoria</Label>
              <Select id="category_id" name="category_id" defaultValue={editing?.category_id ?? ""}>
                <option value="">Sin categoria</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="assigned_to">Asignado a</Label>
              <Select id="assigned_to" name="assigned_to" defaultValue={editing?.assigned_to ?? ""}>
                <option value="">Sin asignar</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="status">Estado</Label>
              <Select id="status" name="status" defaultValue={editing?.status ?? "pending"}>
                <option value="pending">Pendiente</option>
                <option value="in_progress">En curso</option>
                <option value="completed">Completada</option>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="priority">Prioridad</Label>
              <Select id="priority" name="priority" defaultValue={editing?.priority ?? "medium"}>
                <option value="urgent">Urgente</option>
                <option value="high">Alta</option>
                <option value="medium">Media</option>
                <option value="low">Baja</option>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="estimated_minutes">Minutos estimados</Label>
              <Input
                id="estimated_minutes"
                name="estimated_minutes"
                type="number"
                defaultValue={editing?.estimated_minutes ?? ""}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="actual_minutes">Minutos reales</Label>
              <Input
                id="actual_minutes"
                name="actual_minutes"
                type="number"
                defaultValue={editing?.actual_minutes ?? ""}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="due_date">Fecha limite</Label>
              <Input
                id="due_date"
                name="due_date"
                type="date"
                defaultValue={editing?.due_date ? editing.due_date.split("T")[0] : ""}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="description">Descripcion</Label>
            <Textarea id="description" name="description" defaultValue={editing?.description ?? ""} />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={closeDialog}>
              Cancelar
            </Button>
            <Button type="submit">{editing ? "Guardar" : "Crear"}</Button>
          </div>
        </form>
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
        description="Esta accion no se puede deshacer. Se eliminara la tarea permanentemente."
        onConfirm={() => {
          if (deleteId !== null) {
            deleteMutation.mutate(deleteId)
            setDeleteId(null)
          }
        }}
      />
    </div>
  )
}
