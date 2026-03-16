import { useMemo, useState } from "react"
import { useParams, Link, useNavigate } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts"
import {
  Calendar,
  CheckCircle2,
  Circle,
  Clock,
  Edit2,
  Plus,
  PlayCircle,
  List,
  GanttChartSquare,
  Columns,
  ExternalLink,
  Search,
  User,
  Copy,
} from "lucide-react"
import { toast } from "sonner"
import { projectsApi, tasksApi } from "@/lib/api"
import type { Project, ProjectPhase, ProjectStatus, PhaseStatus, Task, TaskStatus } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { getErrorMessage } from "@/lib/utils"
import { GanttChart } from "@/components/gantt/gantt-chart"
import { ProjectPhaseKanban } from "@/components/projects/project-phase-kanban"
import { EvidenceList } from "@/components/projects/evidence-list"
import { Breadcrumb } from "@/components/ui/breadcrumb"
import { Skeleton, SkeletonCard } from "@/components/ui/skeleton"

const STATUS_LABELS: Record<ProjectStatus, string> = {
  planning: "Planificación",
  active: "Activo",
  on_hold: "Pausado",
  completed: "Completado",
  cancelled: "Cancelado",
}

const STATUS_VARIANTS: Record<ProjectStatus, "default" | "success" | "warning" | "secondary" | "destructive"> = {
  planning: "default",
  active: "success",
  on_hold: "warning",
  completed: "secondary",
  cancelled: "destructive",
}

const PHASE_STATUS_ICONS: Record<PhaseStatus, typeof Circle> = {
  pending: Circle,
  in_progress: PlayCircle,
  completed: CheckCircle2,
}

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const [showEditDialog, setShowEditDialog] = useState(false)
  const [showAddTaskDialog, setShowAddTaskDialog] = useState<number | null>(null)
  const [showSaveTemplateDialog, setShowSaveTemplateDialog] = useState(false)
  const [viewMode, setViewMode] = useState<"list" | "gantt" | "kanban">("list")
  const [activeTab, setActiveTab] = useState<"tasks" | "evidence">("tasks")
  const [previewTaskId, setPreviewTaskId] = useState<number | null>(null)
  const [filterStatus, setFilterStatus] = useState<TaskStatus | "all">("all")
  const [filterSearch, setFilterSearch] = useState("")
  const navigate = useNavigate()

  const { data: project, isLoading } = useQuery({
    queryKey: ["project", id],
    queryFn: () => projectsApi.get(parseInt(id!)),
    enabled: !!id,
  })

  const { data: tasksData } = useQuery({
    queryKey: ["project-tasks", id],
    queryFn: () => projectsApi.tasks(parseInt(id!)),
    enabled: !!id,
  })

  const { data: burndown } = useQuery({
    queryKey: ["project-burndown", id],
    queryFn: () => projectsApi.burndown(parseInt(id!)),
    enabled: !!id,
  })

  const updateStatusMutation = useMutation({
    mutationFn: (status: string) => projectsApi.update(parseInt(id!), { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", id] })
      toast.success("Estado actualizado")
    },
  })

  const updatePhaseMutation = useMutation({
    mutationFn: ({ phaseId, status }: { phaseId: number; status: string }) =>
      projectsApi.updatePhase(phaseId, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", id] })
      queryClient.invalidateQueries({ queryKey: ["project-tasks", id] })
      toast.success("Fase actualizada")
    },
  })

  const updateTaskMutation = useMutation({
    mutationFn: ({ taskId, status }: { taskId: number; status: TaskStatus }) =>
      tasksApi.update(taskId, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", id] })
      queryClient.invalidateQueries({ queryKey: ["project-tasks", id] })
    },
  })

  const filterTask = (t: Task) => {
    if (filterStatus !== "all" && t.status !== filterStatus) return false
    if (filterSearch && !t.title.toLowerCase().includes(filterSearch.toLowerCase())) return false
    return true
  }

  const filteredPhases = useMemo(() => {
    if (!tasksData?.phases) return []
    if (filterStatus === "all" && !filterSearch) return tasksData.phases
    return tasksData.phases
      .map((pg: { phase: ProjectPhase; tasks: Task[] }) => ({
        ...pg,
        tasks: pg.tasks.filter(filterTask),
      }))
      .filter((pg: { phase: ProjectPhase; tasks: Task[] }) => pg.tasks.length > 0)
  }, [tasksData, filterStatus, filterSearch])

  const filteredUnassigned = useMemo(() => {
    if (!tasksData?.unassigned_tasks) return []
    if (filterStatus === "all" && !filterSearch) return tasksData.unassigned_tasks
    return tasksData.unassigned_tasks.filter(filterTask)
  }, [tasksData, filterStatus, filterSearch])

  const hasActiveFilters = filterStatus !== "all" || filterSearch !== ""

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-5 w-48" />
        <div className="flex items-center gap-4">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-6 w-20" />
        </div>
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (!project) {
    return <div className="text-muted-foreground">Proyecto no encontrado</div>
  }

  const formatDate = (date: string | null) => {
    if (!date) return "—"
    return new Date(date).toLocaleDateString("es-ES", {
      day: "numeric",
      month: "short",
      year: "numeric",
    })
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb + Header */}
      <Breadcrumb items={[
        { label: "Inicio", href: "/dashboard" },
        { label: "Proyectos", href: "/projects" },
        { label: project.name },
      ]} />
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">{project.name}</h1>
            <Badge variant={STATUS_VARIANTS[project.status]}>
              {STATUS_LABELS[project.status]}
            </Badge>
          </div>
          <p className="text-muted-foreground mt-1">
            <Link to={`/clients/${project.client_id}`} className="hover:text-brand">
              {project.client_name}
            </Link>
          </p>
        </div>
        <div className="flex gap-2">
          <Select
            value={project.status}
            onChange={(e) => updateStatusMutation.mutate(e.target.value)}
            className="w-40"
          >
            <option value="planning">Planificación</option>
            <option value="active">Activo</option>
            <option value="on_hold">Pausado</option>
            <option value="completed">Completado</option>
            <option value="cancelled">Cancelado</option>
          </Select>
          <Button variant="outline" onClick={() => setShowSaveTemplateDialog(true)}>
            <Copy className="h-4 w-4 mr-2" />
            Guardar plantilla
          </Button>
          <Button variant="outline" onClick={() => setShowEditDialog(true)}>
            <Edit2 className="h-4 w-4 mr-2" />
            Editar
          </Button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-brand/10">
                <Calendar className="h-5 w-5 text-brand" />
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Fecha inicio</p>
                <p className="font-semibold">{formatDate(project.start_date)}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-warning/10">
                <Calendar className="h-5 w-5 text-warning" />
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Fecha objetivo</p>
                <p className="font-semibold">{formatDate(project.target_end_date)}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-success/10">
                <CheckCircle2 className="h-5 w-5 text-success" />
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Progreso</p>
                <p className="font-semibold">{project.progress_percent}%</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-secondary">
                <Clock className="h-5 w-5 text-muted-foreground" />
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Tareas</p>
                <p className="font-semibold">
                  {project.completed_task_count}/{project.task_count}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Progress Bar */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">Progreso general</span>
            <span className="text-sm text-muted-foreground">{project.progress_percent}%</span>
          </div>
          <div className="h-2 bg-secondary rounded-full overflow-hidden">
            <div
              className="h-full bg-brand transition-all"
              style={{ width: `${project.progress_percent}% ` }}
            />
          </div>
        </CardContent>
      </Card>

      {/* Hours Consumption */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">Horas consumidas</span>
            <span className="text-sm text-muted-foreground">
              {project.hours_used ?? 0}h
              {project.budget_hours != null && project.budget_hours > 0 ? ` / ${project.budget_hours}h` : " · sin presupuesto"}
            </span>
          </div>
          {project.budget_hours != null && project.budget_hours > 0 ? (
            <div className="h-2 bg-secondary rounded-full overflow-hidden">
              <div
                className={`h-full transition-all ${
                  (project.hours_used ?? 0) / project.budget_hours > 0.9
                    ? "bg-red-500"
                    : (project.hours_used ?? 0) / project.budget_hours > 0.7
                    ? "bg-amber-500"
                    : "bg-brand"
                }`}
                style={{ width: `${Math.min(100, ((project.hours_used ?? 0) / project.budget_hours) * 100)}%` }}
              />
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">Configura las horas presupuestadas en la edición del proyecto para ver el consumo.</p>
          )}
        </CardContent>
      </Card>

      {/* Burndown Chart */}
      {burndown && burndown.total_tasks === 0 && (
        <Card>
          <CardContent className="p-4 text-center text-sm text-muted-foreground">
            Añade tareas al proyecto para ver el burndown.
          </CardContent>
        </Card>
      )}
      {burndown && burndown.total_tasks > 0 && burndown.points.length > 1 && (
        <Card>
          <CardContent className="p-4">
            <p className="text-sm font-medium mb-3">Burndown de tareas</p>
            <ResponsiveContainer width="100%" height={160}>
              <LineChart
                data={burndown.points.filter((_: unknown, i: number) => i % Math.max(1, Math.floor(burndown.points.length / 30)) === 0)}
                margin={{ top: 4, right: 8, left: -20, bottom: 0 }}
              >
                <XAxis dataKey="date" fontSize={9} tick={{ fill: "#8a8a80" }}
                  tickFormatter={(v: string) => { const d = new Date(v + "T12:00:00"); return `${d.getDate()}/${d.getMonth()+1}` }} />
                <YAxis fontSize={9} tick={{ fill: "#8a8a80" }} />
                <Tooltip
                  formatter={(value: number | string | undefined, name) => [value ?? 0, name === "remaining" ? "Restantes" : "Ideal"]}
                  labelFormatter={(v) => new Date(String(v) + "T12:00:00").toLocaleDateString("es-ES")}
                  contentStyle={{ backgroundColor: "#2a2a28", border: "1px solid rgba(254,230,48,0.3)", color: "#f5f5f0", fontSize: 11, borderRadius: 8 }}
                />
                <Line type="monotone" dataKey="remaining" stroke="#FEE630" dot={false} strokeWidth={2} name="remaining" />
                <Line type="monotone" dataKey="ideal" stroke="#6b7280" dot={false} strokeWidth={1} strokeDasharray="4 2" name="ideal" />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* Tab Toggle: Tasks / Evidence */}
      <div className="flex items-center space-x-1 bg-muted/30 p-1 w-fit rounded-lg border border-border">
        <Button
          variant={activeTab === "tasks" ? "default" : "ghost"}
          size="sm"
          onClick={() => setActiveTab("tasks")}
        >
          Fases y Tareas
        </Button>
        <Button
          variant={activeTab === "evidence" ? "default" : "ghost"}
          size="sm"
          onClick={() => setActiveTab("evidence")}
        >
          Evidencia
        </Button>
      </div>

      {/* Evidence Tab */}
      {activeTab === "evidence" && project && (
        <EvidenceList projectId={project.id} phases={project.phases} />
      )}

      {/* View Toggle + Phases and Tasks */}
      {activeTab === "tasks" && <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Fases y Tareas</h2>
          <div className="flex items-center gap-1">
            <Button
              variant={viewMode === "list" ? "default" : "outline"}
              size="sm"
              onClick={() => setViewMode("list")}
              className="h-8"
            >
              <List className="h-4 w-4 mr-1.5" />
              Lista
            </Button>
            <Button
              variant={viewMode === "gantt" ? "default" : "outline"}
              size="sm"
              onClick={() => setViewMode("gantt")}
              className="h-8"
            >
              <GanttChartSquare className="h-4 w-4 mr-1.5" />
              Gantt
            </Button>
            <Button
              variant={viewMode === "kanban" ? "default" : "outline"}
              size="sm"
              onClick={() => setViewMode("kanban")}
              className="h-8"
            >
              <Columns className="h-4 w-4 mr-1.5" />
              Kanban
            </Button>
          </div>
        </div>

        {(viewMode === "list" || viewMode === "gantt") && (
          <div className="flex items-center gap-2 flex-wrap">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                placeholder="Buscar tarea..."
                value={filterSearch}
                onChange={(e) => setFilterSearch(e.target.value)}
                className="h-8 w-48 pl-8 text-sm"
              />
            </div>
            <Select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value as TaskStatus | "all")}
              className="h-8 w-36 text-xs"
            >
              <option value="all">Todos los estados</option>
              <option value="backlog">Backlog</option>
              <option value="pending">Pendiente</option>
              <option value="in_progress">En curso</option>
              <option value="waiting">En espera</option>
              <option value="in_review">En revisión</option>
              <option value="completed">Completada</option>
            </Select>
            {hasActiveFilters && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 text-xs text-muted-foreground"
                onClick={() => { setFilterStatus("all"); setFilterSearch("") }}
              >
                Limpiar filtros
              </Button>
            )}
          </div>
        )}

        {viewMode === "gantt" && project && tasksData && (
          <GanttChart project={project} tasksData={{
            ...tasksData,
            phases: filteredPhases,
            unassigned_tasks: filteredUnassigned,
          }} />
        )}

        {viewMode === "kanban" && tasksData && (
          <ProjectPhaseKanban
            phases={tasksData.phases}
            onPhaseStatusChange={(phaseId, newStatus) =>
              updatePhaseMutation.mutate({ phaseId, status: newStatus })
            }
          />
        )}

        {viewMode === "list" && filteredPhases.map((phaseGroup: { phase: ProjectPhase; tasks: Task[] }) => {
          const phase = phaseGroup.phase
          const tasks = phaseGroup.tasks
          const PhaseIcon = PHASE_STATUS_ICONS[phase.status as PhaseStatus] || Circle
          const completedTasks = tasks.filter((t: Task) => t.status === "completed").length

          return (
            <Card key={phase.id}>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <PhaseIcon
                      className={`h-5 w-5 ${phase.status === "completed"
                        ? "text-success"
                        : phase.status === "in_progress"
                          ? "text-brand"
                          : "text-muted-foreground"
                        }`}
                    />
                    <div>
                      <CardTitle className="text-base font-semibold text-foreground">
                        {phase.name}
                      </CardTitle>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {completedTasks}/{tasks.length} tareas · Vence {formatDate(phase.due_date)}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Select
                      value={phase.status}
                      onChange={(e) =>
                        updatePhaseMutation.mutate({ phaseId: phase.id, status: e.target.value })
                      }
                      className="w-32 h-8 text-xs"
                    >
                      <option value="pending">Pendiente</option>
                      <option value="in_progress">En curso</option>
                      <option value="completed">Completada</option>
                    </Select>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowAddTaskDialog(phase.id)}
                    >
                      <Plus className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {tasks.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-2">Sin tareas en esta fase</p>
                ) : (
                  <div className="space-y-1">
                    {tasks.map((task: Task) => (
                      <TaskRow
                        key={task.id}
                        task={task}
                        onStatusChange={(status) =>
                          updateTaskMutation.mutate({ taskId: task.id, status })
                        }
                        onPreview={(taskId) => setPreviewTaskId(taskId)}
                      />
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })}

        {/* Unassigned Tasks */}
        {viewMode === "list" && filteredUnassigned.length > 0 && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold text-foreground">
                Tareas sin fase asignada
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1">
                {filteredUnassigned.map((task: Task) => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    onStatusChange={(status) =>
                      updateTaskMutation.mutate({ taskId: task.id, status })
                    }
                    onPreview={(taskId) => setPreviewTaskId(taskId)}
                  />
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>}

      {/* Edit Dialog */}
      {project && (
        <EditProjectDialog
          open={showEditDialog}
          onOpenChange={setShowEditDialog}
          project={project}
        />
      )}

      {/* Save as Template Dialog */}
      {project && (
        <SaveTemplateDialog
          open={showSaveTemplateDialog}
          onOpenChange={setShowSaveTemplateDialog}
          projectId={project.id}
          projectName={project.name}
        />
      )}

      {/* Add Task Dialog */}
      {showAddTaskDialog && project && (
        <AddTaskDialog
          open={showAddTaskDialog !== null}
          onOpenChange={(open) => !open && setShowAddTaskDialog(null)}
          projectId={parseInt(id!)}
          phaseId={showAddTaskDialog}
          clientId={project.client_id}
        />
      )}

      {/* Task Preview Dialog */}
      {previewTaskId && (
        <TaskPreviewDialog
          taskId={previewTaskId}
          open={previewTaskId !== null}
          onOpenChange={(open) => !open && setPreviewTaskId(null)}
          onEditFull={(taskId) => {
            setPreviewTaskId(null)
            navigate(`/tasks?edit=${taskId}`)
          }}
        />
      )}
    </div>
  )
}

function TaskRow({
  task,
  onStatusChange,
  onPreview,
}: {
  task: { id: number; title: string; status: TaskStatus; due_date: string | null; assigned_to: number | string | null }
  onStatusChange: (status: TaskStatus) => void
  onPreview?: (taskId: number) => void
}) {
  const isCompleted = task.status === "completed"

  return (
    <div className="flex items-center gap-3 py-2 px-2 rounded-lg hover:bg-card/50 group">
      <button
        onClick={() => onStatusChange(isCompleted ? "pending" : "completed")}
        className={`flex-shrink-0 ${isCompleted ? "text-success" : "text-muted-foreground hover:text-brand"}`}
      >
        {isCompleted ? (
          <CheckCircle2 className="h-5 w-5" />
        ) : (
          <Circle className="h-5 w-5" />
        )}
      </button>
      <div className="flex-1 min-w-0">
        <p className={`text-sm ${isCompleted ? "line-through text-muted-foreground" : ""}`}>
          {task.title}
        </p>
      </div>
      {task.assigned_to && (
        <span className="text-xs text-muted-foreground">{task.assigned_to}</span>
      )}
      <button
        onClick={() => onPreview?.(task.id)}
        className="text-xs text-muted-foreground hover:text-brand opacity-0 group-hover:opacity-100"
      >
        Ver
      </button>
    </div>
  )
}

function EditProjectDialog({
  open,
  onOpenChange,
  project,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  project: Project
}) {
  const queryClient = useQueryClient()
  const [formData, setFormData] = useState({
    name: project.name,
    description: project.description || "",
    start_date: project.start_date?.split("T")[0] || "",
    target_end_date: project.target_end_date?.split("T")[0] || "",
    budget_hours: project.budget_hours?.toString() || "",
    budget_amount: project.budget_amount?.toString() || "",
    monthly_fee: project.monthly_fee?.toString() || "",
    gsc_url: project.gsc_url || "",
    ga4_property_id: project.ga4_property_id || "",
  })

  const updateMutation = useMutation({
    mutationFn: () =>
      projectsApi.update(project.id, {
        name: formData.name,
        description: formData.description || undefined,
        start_date: formData.start_date || undefined,
        target_end_date: formData.target_end_date || undefined,
        budget_hours: formData.budget_hours ? parseFloat(formData.budget_hours) : undefined,
        budget_amount: formData.budget_amount ? parseFloat(formData.budget_amount) : undefined,
        monthly_fee: formData.monthly_fee ? parseFloat(formData.monthly_fee) : undefined,
        gsc_url: formData.gsc_url || undefined,
        ga4_property_id: formData.ga4_property_id || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project", project.id.toString()] })
      toast.success("Proyecto actualizado")
      onOpenChange(false)
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar")),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Editar proyecto</DialogTitle>
      </DialogHeader>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          updateMutation.mutate()
        }}
        className="space-y-4 mt-4"
      >
        <div className="space-y-2">
          <Label>Nombre</Label>
          <Input
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            required
          />
        </div>
        <div className="space-y-2">
          <Label>Descripción</Label>
          <Input
            value={formData.description}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>Fecha inicio</Label>
            <Input
              type="date"
              value={formData.start_date}
              onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label>Fecha objetivo</Label>
            <Input
              type="date"
              value={formData.target_end_date}
              onChange={(e) => setFormData({ ...formData, target_end_date: e.target.value })}
            />
          </div>
        </div>
        <div className="grid grid-cols-3 gap-4">
          <div className="space-y-2">
            <Label>Fee mensual (EUR)</Label>
            <Input
              type="number"
              step="0.01"
              value={formData.monthly_fee}
              onChange={(e) => setFormData({ ...formData, monthly_fee: e.target.value })}
              placeholder="Retainer"
            />
          </div>
          <div className="space-y-2">
            <Label>Presupuesto horas</Label>
            <Input
              type="number"
              value={formData.budget_hours}
              onChange={(e) => setFormData({ ...formData, budget_hours: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label>Presupuesto €</Label>
            <Input
              type="number"
              value={formData.budget_amount}
              onChange={(e) => setFormData({ ...formData, budget_amount: e.target.value })}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>Google Search Console URL</Label>
            <Input
              type="url"
              placeholder="https://ejemplo.com"
              value={formData.gsc_url}
              onChange={(e) => setFormData({ ...formData, gsc_url: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label>GA4 Property ID</Label>
            <Input
              type="text"
              placeholder="123456789"
              value={formData.ga4_property_id}
              onChange={(e) => setFormData({ ...formData, ga4_property_id: e.target.value })}
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-4">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button type="submit" disabled={updateMutation.isPending}>
            Guardar
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

function AddTaskDialog({
  open,
  onOpenChange,
  projectId,
  phaseId,
  clientId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId: number
  phaseId: number
  clientId: number
}) {
  const queryClient = useQueryClient()
  const [title, setTitle] = useState("")
  const [estimatedMinutes, setEstimatedMinutes] = useState("")

  const createMutation = useMutation({
    mutationFn: () =>
      tasksApi.create({
        title,
        client_id: clientId,
        project_id: projectId,
        phase_id: phaseId,
        estimated_minutes: estimatedMinutes ? parseInt(estimatedMinutes) : undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-tasks", projectId.toString()] })
      queryClient.invalidateQueries({ queryKey: ["project", projectId.toString()] })
      toast.success("Tarea añadida")
      onOpenChange(false)
      setTitle("")
      setEstimatedMinutes("")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear tarea")),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Añadir tarea a la fase</DialogTitle>
      </DialogHeader>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          createMutation.mutate()
        }}
        className="space-y-4 mt-4"
      >
        <div className="space-y-2">
          <Label>Título *</Label>
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Nombre de la tarea"
            required
          />
        </div>
        <div className="space-y-2">
          <Label>Tiempo estimado (minutos)</Label>
          <Input
            type="number"
            value={estimatedMinutes}
            onChange={(e) => setEstimatedMinutes(e.target.value)}
            placeholder="60"
          />
        </div>
        <div className="flex justify-end gap-2 pt-4">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button type="submit" disabled={createMutation.isPending}>
            Añadir
          </Button>
        </div>
      </form>
    </Dialog>
  )
}


// --- Task Preview Dialog (lightweight view from project) ---

const TASK_STATUS_LABELS: Record<string, string> = {
  backlog: "Backlog",
  pending: "Pendiente",
  in_progress: "En curso",
  waiting: "En espera",
  in_review: "En revisión",
  completed: "Completada",
}

const TASK_PRIORITY_LABELS: Record<string, string> = {
  urgent: "Urgente",
  high: "Alta",
  medium: "Media",
  low: "Baja",
}

function TaskPreviewDialog({
  taskId,
  open,
  onOpenChange,
  onEditFull,
}: {
  taskId: number
  open: boolean
  onOpenChange: (open: boolean) => void
  onEditFull: (taskId: number) => void
}) {
  const { data: task, isLoading } = useQuery({
    queryKey: ["task-preview", taskId],
    queryFn: () => tasksApi.get(taskId),
    enabled: open,
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Detalle de tarea</DialogTitle>
      </DialogHeader>
      {isLoading ? (
        <div className="py-8 text-center text-sm text-muted-foreground">Cargando...</div>
      ) : task ? (
        <div className="space-y-4 mt-2">
          <h3 className="text-base font-semibold">{task.title}</h3>
          {task.description && (
            <p className="text-sm text-muted-foreground whitespace-pre-wrap">{task.description}</p>
          )}
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-xs text-muted-foreground block">Estado</span>
              <Badge variant="outline">{TASK_STATUS_LABELS[task.status] ?? task.status}</Badge>
            </div>
            <div>
              <span className="text-xs text-muted-foreground block">Prioridad</span>
              <Badge variant="outline">{TASK_PRIORITY_LABELS[task.priority] ?? task.priority}</Badge>
            </div>
            {task.assigned_user_name && (
              <div>
                <span className="text-xs text-muted-foreground block">Responsable</span>
                <span className="flex items-center gap-1"><User className="w-3 h-3" />{task.assigned_user_name}</span>
              </div>
            )}
            {task.client_name && (
              <div>
                <span className="text-xs text-muted-foreground block">Cliente</span>
                <span>{task.client_name}</span>
              </div>
            )}
            {task.due_date && (
              <div>
                <span className="text-xs text-muted-foreground block">Fecha límite</span>
                <span className="flex items-center gap-1"><Calendar className="w-3 h-3" />{new Date(task.due_date).toLocaleDateString("es-ES")}</span>
              </div>
            )}
            {task.estimated_minutes && (
              <div>
                <span className="text-xs text-muted-foreground block">Estimado</span>
                <span className="flex items-center gap-1"><Clock className="w-3 h-3" />{task.estimated_minutes}min</span>
              </div>
            )}
          </div>
          <div className="flex justify-end gap-2 pt-2 border-t border-border">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>Cerrar</Button>
            <Button onClick={() => onEditFull(taskId)} className="gap-1.5">
              <ExternalLink className="w-3.5 h-3.5" />
              Editar completa
            </Button>
          </div>
        </div>
      ) : (
        <div className="py-8 text-center text-sm text-muted-foreground">No se encontró la tarea</div>
      )}
    </Dialog>
  )
}

function SaveTemplateDialog({
  open,
  onOpenChange,
  projectId,
  projectName,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId: number
  projectName: string
}) {
  const [name, setName] = useState(projectName)
  const [description, setDescription] = useState("")

  const saveMutation = useMutation({
    mutationFn: () =>
      projectsApi.saveAsTemplate(projectId, { name, description: description || undefined }),
    onSuccess: () => {
      toast.success("Plantilla guardada correctamente")
      onOpenChange(false)
      setName(projectName)
      setDescription("")
    },
    onError: (err: unknown) => toast.error(getErrorMessage(err, "Error al guardar plantilla")),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Guardar como plantilla</DialogTitle>
      </DialogHeader>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          saveMutation.mutate()
        }}
        className="space-y-4 mt-4"
      >
        <p className="text-sm text-muted-foreground">
          Se guardará la estructura actual del proyecto (fases y tareas) como plantilla reutilizable.
        </p>

        <div className="space-y-2">
          <Label>Nombre de la plantilla *</Label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ej: SEO Mensual Completo"
            required
          />
        </div>

        <div className="space-y-2">
          <Label>Descripción</Label>
          <Input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Breve descripción de qué incluye"
          />
        </div>

        <div className="flex justify-end gap-2 pt-4">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button type="submit" disabled={saveMutation.isPending}>
            {saveMutation.isPending ? "Guardando..." : "Guardar plantilla"}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
