import { ProjectWorkSummary } from "@/components/projects/project-work-summary"
import type { ProjectTaskItem, ProjectTaskGroup } from "@/lib/project-work"
import { useBusinessDate } from "@/hooks/use-business-date"
import { businessDateString, formatCivilDate, parseApiInstant } from "@/lib/dates"
import { useCallback, useMemo, useState } from "react"
import { format, parseISO } from "date-fns"
import { es } from "date-fns/locale"
import { useAuth } from "@/context/auth-context"
import { ProjectTaskList } from "@/components/projects/project-task-list"
import { useParams, Link, useNavigate, useSearchParams } from "react-router-dom"
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
  Search,
  Copy,
  AlertTriangle,
} from "lucide-react"
import { toast } from "sonner"
import { projectsApi, tasksApi, usersApi } from "@/lib/api"
import type { Project, ProjectStatus, PhaseStatus, TaskStatus, ProjectClosingStatus, ProjectMonthlyCycle } from "@/lib/types"
import { isEnabled } from "@/lib/hidden-modules"
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
import { ProjectBillingTab } from "@/components/projects/project-billing-tab"
import { ProjectIdeasTab } from "@/components/projects/project-ideas-tab"
import { Breadcrumb } from "@/components/ui/breadcrumb"
import { Skeleton, SkeletonCard } from "@/components/ui/skeleton"
import { invalidateProjectChange, invalidateTaskChange, projectKeys, taskKeys } from "@/lib/query-keys"
import { TaskPanel } from "@/components/tasks/task-panel"
import { TimeLogDialog } from "@/components/timer/time-log-dialog"

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

function errorStatus(error: unknown) {
  return (error as { response?: { status?: number } })?.response?.status
}

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { hasPermission, user, isAdmin } = useAuth()
  const [showEditDialog, setShowEditDialog] = useState(false)
  const [showAddTaskDialog, setShowAddTaskDialog] = useState<number | null>(null)
  const [showSaveTemplateDialog, setShowSaveTemplateDialog] = useState(false)
  const [viewMode, setViewMode] = useState<"list" | "gantt" | "kanban">("list")
  const [activeTab, setActiveTab] = useState<"tasks" | "ideas" | "evidence" | "billing">("tasks")
  const [previewTaskId, setPreviewTaskId] = useState<number | null>(null)
  const [showMetrics, setShowMetrics] = useState(false)
  const [timeLogTask, setTimeLogTask] = useState<{ id: number; title: string; retired?: boolean } | null>(null)
  const [filterStatus, setFilterStatus] = useState<TaskStatus | "all">("all")
  const [filterSearch, setFilterSearch] = useState("")
  const [searchParams] = useSearchParams()

  const businessToday = useBusinessDate()
  const currentMonth = businessToday.slice(0, 7)
  const [selectedCycleMonth, setSelectedCycleMonth] = useState<string | null>(null)
  const cycleMonth = selectedCycleMonth ?? currentMonth
  const projectId = id ? parseInt(id) : NaN
  const validId = !isNaN(projectId)

  const { data: project, isLoading, isError: projectError, error: projectLoadError, refetch: retryProject } = useQuery({
    queryKey: projectKeys.detail(projectId),
    queryFn: () => projectsApi.get(projectId),
    enabled: validId,
  })

  const { data: tasksData, isLoading: tasksLoading, isError: tasksError, refetch: retryTasks } = useQuery({
    queryKey: taskKeys.project(projectId),
    queryFn: () => projectsApi.tasks(projectId),
    enabled: validId,
  })

  const burndownQuery = useQuery({
    queryKey: projectKeys.burndown(projectId),
    queryFn: () => projectsApi.burndown(projectId),
    enabled: validId && showMetrics && project?.is_recurring === false,
  })

  const burndown = burndownQuery.isError ? undefined : burndownQuery.data

  const cycleQuery = useQuery({
    queryKey: ["projects", projectId, "monthly-cycle", cycleMonth],
    queryFn: () => projectsApi.monthlyCycle(projectId, cycleMonth),
    enabled: validId && project?.is_recurring === true,
  })

  const updateStatusMutation = useMutation({
    mutationFn: (status: string) => projectsApi.update(projectId, { status }),
    onSuccess: () => {
      invalidateProjectChange(queryClient, { clientId: project?.client_id })
      toast.success("Estado actualizado")
    },
    onError: () => toast.error("Error al actualizar estado"),
  })

  const updatePhaseMutation = useMutation({
    mutationFn: ({ phaseId, status }: { phaseId: number; status: string }) =>
      projectsApi.updatePhase(phaseId, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
      queryClient.invalidateQueries({ queryKey: taskKeys.project(projectId) })
      toast.success("Fase actualizada")
    },
    onError: () => toast.error("Error al actualizar fase"),
  })

  const updateTaskMutation = useMutation({
    mutationFn: ({ taskId, status }: { taskId: number; status: TaskStatus }) =>
      tasksApi.update(taskId, { status }),
    onSuccess: () => {
      invalidateTaskChange(queryClient, { projectId, clientId: project?.client_id })
    },
    onError: () => toast.error("Error al actualizar tarea"),
  })

  const filterTask = useCallback((t: ProjectTaskItem) => {
    if (t.is_recurring) return false
    if (filterStatus !== "all" && t.status !== filterStatus) return false
    if (filterSearch && !t.title.toLowerCase().includes(filterSearch.toLowerCase())) return false
    return true
  }, [filterSearch, filterStatus])

  const filteredPhases = useMemo(() => {
    if (!tasksData?.phases) return []
    return tasksData.phases
      .map((pg: ProjectTaskGroup) => ({
        ...pg,
        tasks: pg.tasks.filter(filterTask),
      }))
      .filter((pg: ProjectTaskGroup) => pg.tasks.length > 0)
  }, [tasksData, filterTask])

  const filteredUnassigned = useMemo(() => {
    if (!tasksData?.unassigned_tasks) return []
    return tasksData.unassigned_tasks.filter(filterTask)
  }, [tasksData, filterTask])

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

  const projectErrorStatus = errorStatus(projectLoadError)
  if (projectError && (projectErrorStatus === 403 || projectErrorStatus === 404 || projectErrorStatus === 410)) {
    const inaccessible = projectErrorStatus === 403
    return (
      <div role="alert" className="mx-auto max-w-xl space-y-4 rounded-lg border border-border p-6">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold">
            {inaccessible ? "Ya no tienes acceso a este proyecto" : "Este proyecto ya no existe"}
          </h1>
          <p className="text-sm text-muted-foreground">
            {inaccessible
              ? "Tus permisos han cambiado. Vuelve al listado para continuar con los proyectos disponibles."
              : "Puede haberse eliminado o haberse deshecho su creación."}
          </p>
        </div>
        <Button onClick={() => navigate("/projects")}>Volver a proyectos</Button>
      </div>
    )
  }

  if (projectError && !project) {
    return <div role="alert" className="space-y-3"><p>{getErrorMessage(projectLoadError, "No se pudo cargar el proyecto.")}</p><Button variant="outline" onClick={() => retryProject()}>Reintentar</Button></div>
  }
  if (!project) return <div className="text-muted-foreground">Proyecto no encontrado</div>

  const primaryHoursUsed = project.is_recurring ? (project.hours_used_month ?? 0) : (project.hours_used ?? 0)
  const primaryHoursBudget = project.is_recurring ? project.effective_monthly_hours_budget : project.budget_hours

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
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
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
          <p className="mt-1 text-sm text-muted-foreground">Responsable: {project.owner_name || "Sin responsable"}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {hasPermission("tasks", true) && <Button onClick={() => setShowAddTaskDialog(0)}><Plus className="h-4 w-4 mr-2" />Añadir tarea</Button>}
          <Select
            aria-label="Estado del proyecto"
            value={project.status}
            onChange={(e) => updateStatusMutation.mutate(e.target.value)}
            disabled={!hasPermission("projects", true) || updateStatusMutation.isPending}
            className="w-40"
          >
            <option value="planning">Planificación</option>
            <option value="active">Activo</option>
            <option value="on_hold">Pausado</option>
            <option value="completed">Completado</option>
            <option value="cancelled">Cancelado</option>
          </Select>
          <Button variant="outline" disabled={!hasPermission("projects", true)} onClick={() => setShowSaveTemplateDialog(true)}>
            <Copy className="h-4 w-4 mr-2" />
            Guardar plantilla
          </Button>
          <Button variant="outline" disabled={!hasPermission("projects", true)} onClick={() => setShowEditDialog(true)}>
            <Edit2 className="h-4 w-4 mr-2" />
            Editar
          </Button>
        </div>
      </div>

      {searchParams.get("created") === "1" && <div role="status" className="border-l-2 border-brand pl-4 py-2"><p className="font-medium">Proyecto creado</p><p className="text-sm text-muted-foreground">{project.task_count ? "Revisa las tareas y concreta el próximo paso." : "Añade la primera tarea para concretar el próximo paso."}</p></div>}
      {projectError && <div role="alert" className="text-sm">No se pudo actualizar. Se muestran los últimos datos recibidos. <Button variant="ghost" onClick={() => retryProject()}>Reintentar</Button></div>}
      {tasksData && !tasksError && <ProjectWorkSummary
        tasks={[...tasksData.phases.flatMap(group => group.tasks), ...tasksData.unassigned_tasks]}
        today={businessToday}
        canWrite={hasPermission("tasks", true)}
        onOpen={setPreviewTaskId}
        onAdd={() => setShowAddTaskDialog(0)}
      />}

      {project.is_recurring && <MonthlyCycleCard
        cycle={cycleQuery.data}
        month={cycleMonth}
        currentMonth={currentMonth}
        loading={cycleQuery.isLoading}
        error={cycleQuery.isError}
        onMonthChange={(month) => setSelectedCycleMonth(month === currentMonth ? null : month)}
        onRetry={() => void cycleQuery.refetch()}
        canOpenTasks={isEnabled("tasks") && hasPermission("tasks")}
      />}

      <details onToggle={event => setShowMetrics(event.currentTarget.open)} className="border-y border-border py-1">
        <summary className="cursor-pointer py-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded">
          Plazos, horas y progreso{project.target_end_date ? ` · Entrega prevista: ${formatDate(project.target_end_date)}` : " · Sin fecha de entrega"}
        </summary>
        {showMetrics && <div className="space-y-4 pb-4">
      {/* Stats Cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
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

      {/* Hours Consumption — tiempo tracked desde timesheet de tareas vinculadas */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-medium">{project.is_recurring ? "Tiempo registrado este mes" : "Tiempo registrado"}</span>
              <span
                className="text-muted-foreground/60 cursor-help text-xs"
                title={`Suma del tiempo real registrado para tareas de este proyecto${project.is_recurring ? " durante el mes civil actual" : ""}. No incluye tareas del cliente sin proyecto asignado.`}
              >
                ⓘ
              </span>
            </div>
            <span className="text-sm text-muted-foreground">
              {primaryHoursUsed}h
              {primaryHoursBudget != null && primaryHoursBudget > 0 ? ` / ${primaryHoursBudget}h` : " · sin presupuesto"}
            </span>
          </div>
          {primaryHoursBudget != null && primaryHoursBudget > 0 ? (
            <div className="h-2 bg-secondary rounded-full overflow-hidden">
              <div
                className={`h-full transition-all ${
                  primaryHoursUsed / primaryHoursBudget > 0.9
                    ? "bg-red-500"
                    : primaryHoursUsed / primaryHoursBudget > 0.7
                    ? "bg-amber-500"
                    : "bg-brand"
                }`}
                style={{ width: `${Math.min(100, (primaryHoursUsed / primaryHoursBudget) * 100)}%` }}
              />
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">Configura las horas presupuestadas en la edición del proyecto para ver el consumo.</p>
          )}
        </CardContent>
      </Card>

      {/* Alerta de presupuesto de horas — semanal (guía) + mensual (techo que dispara la notificación).
          Usa los techos EFECTIVOS: en retainers mensuales cae a budget_hours ("Presupuesto horas/mes"). */}
      {((project.effective_weekly_hours_budget ?? 0) > 0 || (project.effective_monthly_hours_budget ?? 0) > 0) && (
        <HoursBudgetCard
          weeklyBudget={project.effective_weekly_hours_budget}
          monthlyBudget={project.effective_monthly_hours_budget}
          usedWeek={project.hours_used_week ?? 0}
          usedMonth={project.hours_used_month ?? 0}
        />
      )}

      {/* Aviso de cierre para proyectos puntuales (fecha final + horas vs tiempo restante) */}
      {project.closing_status && (
        <ProjectClosingCard closing={project.closing_status} />
      )}

      {/* Burndown Chart — solo en proyectos no-recurrentes. En recurrentes el
          concepto no aplica porque las tareas se reinician cada ciclo. */}
      {!project.is_recurring && burndownQuery.isLoading && <p role="status" className="text-sm text-muted-foreground">Cargando progreso de tareas…</p>}
      {!project.is_recurring && burndownQuery.isError && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border p-3">
          <p role="alert" className="text-sm">No se pudo actualizar el progreso de tareas.</p>
          <Button variant="outline" size="sm" disabled={burndownQuery.isFetching} onClick={() => void burndownQuery.refetch()}>Reintentar progreso</Button>
        </div>
      )}
      {!project.is_recurring && burndown && burndown.total_tasks > 0 && burndown.points.length <= 1 && (
        <p className="text-sm text-muted-foreground">Aún no hay suficientes días para mostrar la evolución de tareas.</p>
      )}
      {!project.is_recurring && burndown && burndown.total_tasks === 0 && (
        <Card>
          <CardContent className="p-4 text-center text-sm text-muted-foreground">
            Añade tareas al proyecto para ver el burndown.
          </CardContent>
        </Card>
      )}
      {!project.is_recurring && burndown && burndown.total_tasks > 0 && burndown.points.length > 1 && (
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

        </div>}
      </details>

      {/* Tab Toggle: Tasks / Evidence */}
      {(isEnabled("growth") || isEnabled("evidence") || isEnabled("billing")) && <div className="flex flex-wrap items-center gap-1 bg-muted/30 p-1 w-fit rounded-lg border border-border">
        <Button
          variant={activeTab === "tasks" ? "default" : "ghost"}
          size="sm"
          onClick={() => setActiveTab("tasks")}
        >
          Fases y Tareas
        </Button>
        {/* Buffer, Documentos y Facturación pertenecen a módulos ocultos: sus
            endpoints ya no están registrados, así que la pestaña tampoco. */}
        {isEnabled("growth") && (
          <Button
            variant={activeTab === "ideas" ? "default" : "ghost"}
            size="sm"
            onClick={() => setActiveTab("ideas")}
          >
            Buffer
          </Button>
        )}
        {isEnabled("evidence") && (
          <Button
            variant={activeTab === "evidence" ? "default" : "ghost"}
            size="sm"
            onClick={() => setActiveTab("evidence")}
          >
            Documentos
          </Button>
        )}
        {isEnabled("billing") && (
          <Button
            variant={activeTab === "billing" ? "default" : "ghost"}
            size="sm"
            onClick={() => setActiveTab("billing")}
          >
            Facturación
          </Button>
        )}
      </div>}

      {/* Ideas Tab */}
      {activeTab === "ideas" && project && isEnabled("growth") && (
        <ProjectIdeasTab projectId={project.id} />
      )}

      {/* Evidence Tab */}
      {activeTab === "evidence" && project && isEnabled("evidence") && (
        <EvidenceList projectId={project.id} phases={project.phases} />
      )}

      {/* Billing Tab */}
      {activeTab === "billing" && project && isEnabled("billing") && (
        <ProjectBillingTab projectId={project.id} project={project} />
      )}

      {/* View Toggle + Phases and Tasks */}
      {activeTab === "tasks" && <div className="space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Trabajo del proyecto</h2>
            {hasPermission("tasks") && <Link className="text-sm text-primary hover:underline" to="/tasks?view=recurring">Ver plantillas recurrentes</Link>}
          </div>
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
                aria-label="Buscar tarea en el proyecto"
                placeholder="Buscar tarea..."
                value={filterSearch}
                onChange={(e) => setFilterSearch(e.target.value)}
                className="h-8 w-48 pl-8 text-sm"
              />
            </div>
            <Select
              aria-label="Estado de las tareas del proyecto"
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
              <option value="advanced">Avanzada (sigo mañana)</option>
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

        {tasksLoading && <p role="status" className="text-sm text-muted-foreground">Cargando tareas…</p>}
        {tasksError && <div role="alert" className="text-sm space-y-2">
          <p>{tasksData ? "No se pudieron actualizar las tareas. Se muestran los últimos datos recibidos." : "No se pudieron cargar las tareas del proyecto."}</p>
          <Button variant="outline" onClick={() => retryTasks()}>Reintentar tareas</Button>
        </div>}
        {tasksData && !tasksError && !hasActiveFilters && !filteredPhases.some((group: ProjectTaskGroup) => group.tasks.length) && !filteredUnassigned.length && <p className="text-sm text-muted-foreground">Aún no hay tareas. Añade la primera cuando tengas claro el próximo paso.</p>}
        {tasksData && hasActiveFilters && filteredPhases.length === 0 && filteredUnassigned.length === 0 && <p className="text-sm text-muted-foreground">No hay tareas que coincidan con estos filtros.</p>}

        {viewMode === "gantt" && project && tasksData && (
          <GanttChart project={project} tasksData={{
            ...tasksData,
            phases: filteredPhases,
            unassigned_tasks: filteredUnassigned,
          }} />
        )}

        {viewMode === "kanban" && tasksData && (
          <ProjectPhaseKanban
            phases={filteredPhases}
            onPhaseStatusChange={(phaseId, newStatus) =>
              updatePhaseMutation.mutate({ phaseId, status: newStatus })
            }
          />
        )}

        {viewMode === "list" && filteredPhases.map((phaseGroup: ProjectTaskGroup) => {
          const phase = phaseGroup.phase
          const tasks = phaseGroup.tasks
          const PhaseIcon = PHASE_STATUS_ICONS[phase.status as PhaseStatus] || Circle
          const completedTasks = tasks.filter((t) => t.status === "completed").length

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
                      aria-label={`Estado de la fase ${phase.name}`}
                      disabled={!hasPermission("projects", true) || updatePhaseMutation.isPending}
                      className="w-32 h-8 text-xs"
                    >
                      <option value="pending">Pendiente</option>
                      <option value="in_progress">En curso</option>
                      <option value="completed">Completada</option>
                    </Select>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Añadir tarea a ${phase.name}`}
                      disabled={!hasPermission("tasks", true)}
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
                  <ProjectTaskList tasks={tasks} showCompleted={hasActiveFilters}
                    canWrite={hasPermission("tasks", true)}
                    requiresReview={!!project?.requires_task_review}
                    canCompleteReviewedTask={!!(isAdmin || (user?.id && project?.owner_id === user.id))}
                    pendingTaskId={updateTaskMutation.isPending ? updateTaskMutation.variables.taskId : undefined}
                    onStatusChange={(taskId, status) => updateTaskMutation.mutate({ taskId, status })}
                    onOpen={setPreviewTaskId} />
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
                  <ProjectTaskList tasks={filteredUnassigned} showCompleted={hasActiveFilters}
                    canWrite={hasPermission("tasks", true)}
                    requiresReview={!!project?.requires_task_review}
                    canCompleteReviewedTask={!!(isAdmin || (user?.id && project?.owner_id === user.id))}
                    pendingTaskId={updateTaskMutation.isPending ? updateTaskMutation.variables.taskId : undefined}
                onStatusChange={(taskId, status) => updateTaskMutation.mutate({ taskId, status })}
                onOpen={setPreviewTaskId} />
            </CardContent>
          </Card>
        )}
      </div>}

      {/* Edit Dialog */}
      {project && (
        <EditProjectDialog
          key={project.id}
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
      {showAddTaskDialog !== null && project && (
        <TaskPanel
          open={showAddTaskDialog !== null}
          onOpenChange={(open) => !open && setShowAddTaskDialog(null)}
          defaults={{ projectId, phaseId: showAddTaskDialog || null, clientId: project.client_id }}
        />
      )}

      {/* Task Preview Dialog */}
      {previewTaskId && (
        <TaskPanel
          taskId={previewTaskId}
          open={previewTaskId !== null}
          onOpenChange={(open) => !open && setPreviewTaskId(null)}
          onOpenTime={(task) => { setPreviewTaskId(null); setTimeLogTask({ id: task.id, title: task.title, retired: !!task.retired_at }) }}
        />
      )}
      {timeLogTask && <TimeLogDialog taskId={timeLogTask.id} taskTitle={timeLogTask.title} taskRetired={timeLogTask.retired} open onOpenChange={(open) => !open && setTimeLogTask(null)} />}
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
    owner_id: project.owner_id?.toString() || "",
    requires_task_review: project.requires_task_review,
    description: project.description || "",
    start_date: project.start_date?.split("T")[0] || "",
    target_end_date: project.target_end_date?.split("T")[0] || "",
    is_ongoing: !project.target_end_date,
    pricing_model: project.pricing_model || "",
    unit_price: project.unit_price?.toString() || "",
    unit_label: project.unit_label || "",
    budget_hours: project.budget_hours?.toString() || "",
    weekly_hours_budget: project.weekly_hours_budget?.toString() || "",
    monthly_hours_budget: project.monthly_hours_budget?.toString() || "",
    budget_amount: project.budget_amount?.toString() || "",
    monthly_fee: project.monthly_fee?.toString() || "",
    billing_day: project.billing_day?.toString() || "",
    billing_amount: project.billing_amount?.toString() || "",
    next_billing_date: project.next_billing_date || "",
    scope: project.scope || "",
    gsc_url: project.gsc_url || "",
    ga4_property_id: project.ga4_property_id || "",
  })

  const { data: projectOwners = [], isError: ownersError } = useQuery({
    queryKey: ["users-all"], queryFn: () => usersApi.listAll(), enabled: open,
  })
  const updateMutation = useMutation({
    mutationFn: () =>
      projectsApi.update(project.id, {
        ...(formData.owner_id !== (project.owner_id?.toString() || "") ? { owner_id: formData.owner_id ? Number(formData.owner_id) : null } : {}),
        requires_task_review: formData.requires_task_review,
        name: formData.name,
        description: formData.description || undefined,
        start_date: formData.start_date || undefined,
        target_end_date: formData.is_ongoing ? null : (formData.target_end_date || undefined),
        pricing_model: formData.pricing_model || null,
        unit_price: formData.unit_price ? parseFloat(formData.unit_price) : null,
        unit_label: formData.unit_label || null,
        budget_hours: formData.budget_hours ? parseFloat(formData.budget_hours) : undefined,
        weekly_hours_budget: formData.weekly_hours_budget ? parseFloat(formData.weekly_hours_budget) : null,
        monthly_hours_budget: formData.monthly_hours_budget ? parseFloat(formData.monthly_hours_budget) : null,
        budget_amount: formData.budget_amount ? parseFloat(formData.budget_amount) : undefined,
        monthly_fee: formData.monthly_fee ? parseFloat(formData.monthly_fee) : undefined,
        billing_day: formData.billing_day ? parseInt(formData.billing_day) : undefined,
        billing_amount: formData.billing_amount ? parseFloat(formData.billing_amount) : undefined,
        next_billing_date: formData.next_billing_date || undefined,
        scope: formData.scope || null,
        gsc_url: formData.gsc_url || undefined,
        ga4_property_id: formData.ga4_property_id || undefined,
      }),
    onSuccess: () => {
      invalidateProjectChange(queryClient, { clientId: project.client_id })
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
          <Label htmlFor="project-detail-page-field-1">Nombre</Label>
          <Input id="project-detail-page-field-1"
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="project-owner">Responsable del proyecto</Label>
          <Select id="project-owner" value={formData.owner_id} onChange={(event) => setFormData({ ...formData, owner_id: event.target.value })} disabled={ownersError}>
            <option value="">Sin responsable</option>
            {project.owner_id && !projectOwners.some(owner => owner.id === project.owner_id && owner.is_active) && <option value={project.owner_id}>{project.owner_name || "Responsable actual"} (conservado)</option>}
            {projectOwners.filter(owner => owner.is_active).map(owner => <option key={owner.id} value={owner.id}>{owner.full_name}</option>)}
          </Select>
          {ownersError && <p role="alert" className="text-xs text-muted-foreground">No se pudo cargar el equipo. Se conserva el responsable actual.</p>}
        </div>
        <label className="flex items-start gap-2 rounded-md border p-3 text-sm">
          <input
            type="checkbox"
            checked={formData.requires_task_review}
            onChange={(event) => setFormData({ ...formData, requires_task_review: event.target.checked })}
            disabled={!formData.owner_id || ownersError}
          />
          <span>
            <span className="font-medium">Revisar tareas antes de darlas por hechas</span>
            <span className="block text-xs text-muted-foreground">El responsable del proyecto o una persona administradora podrá completarlas.</span>
            {!formData.owner_id && <span className="block text-xs text-destructive">Selecciona un responsable activo para activar esta revisión.</span>}
          </span>
        </label>
        <div className="space-y-2">
          <Label htmlFor="project-detail-page-field-2">Descripción</Label>
          <Input id="project-detail-page-field-2"
            value={formData.description}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="project-detail-page-field-3">Fecha inicio</Label>
            <Input id="project-detail-page-field-3"
              type="date"
              value={formData.start_date}
              onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label>Fecha fin</Label>
            {formData.is_ongoing ? (
              <div className="flex items-center gap-2 h-10">
                <span className="text-sm text-green-400 font-medium">En curso</span>
                <button
                  type="button"
                  className="text-xs text-muted-foreground hover:text-foreground underline"
                  onClick={() => setFormData({ ...formData, is_ongoing: false })}
                >
                  Poner fecha fin
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <Input
                  type="date"
                  value={formData.target_end_date}
                  min={formData.start_date || undefined}
                  onChange={(e) => setFormData({ ...formData, target_end_date: e.target.value })}
                  className="flex-1"
                  required={!formData.is_ongoing}
                />
                <button
                  type="button"
                  className="text-xs text-muted-foreground hover:text-foreground underline whitespace-nowrap"
                  onClick={() => setFormData({ ...formData, is_ongoing: true, target_end_date: "" })}
                >
                  En curso
                </button>
              </div>
            )}
          </div>
        </div>
        {/* --- Techos de horas (mes dispara alerta, semana = guía visual) --- */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="project-detail-page-field-4">Horas/mes (techo de alerta)</Label>
            <Input id="project-detail-page-field-4"
              type="number"
              step="0.5"
              min="0"
              value={formData.monthly_hours_budget}
              onChange={(e) => setFormData({ ...formData, monthly_hours_budget: e.target.value })}
              placeholder="Ej: 24"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="project-detail-page-field-5">Horas/semana (guía visual)</Label>
            <Input id="project-detail-page-field-5"
              type="number"
              step="0.5"
              min="0"
              value={formData.weekly_hours_budget}
              onChange={(e) => setFormData({ ...formData, weekly_hours_budget: e.target.value })}
              placeholder="Ej: 6"
            />
          </div>
        </div>
        <p className="text-xs text-muted-foreground -mt-2">
          La alerta usa el techo mensual (aviso al 80%, alerta al pasarse). El semanal es solo referencia visual; se permite compensar entre semanas.
        </p>

        {/* --- Pricing model --- */}
        <div className="space-y-2">
          <Label>Modelo de precio</Label>
          <select
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            value={formData.pricing_model}
            onChange={(e) => setFormData({ ...formData, pricing_model: e.target.value })}
          >
            <option value="">Sin definir</option>
            <option value="monthly">Mensual fijo (retainer)</option>
            <option value="per_piece">Por pieza/unidad</option>
            <option value="hourly">Por hora</option>
            <option value="project">Precio cerrado</option>
          </select>
        </div>

        {/* monthly → fee mensual */}
        {formData.pricing_model === "monthly" && (
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="project-detail-page-field-6">Fee mensual (EUR)</Label>
              <Input id="project-detail-page-field-6" type="number" step="0.01" value={formData.monthly_fee} onChange={(e) => setFormData({ ...formData, monthly_fee: e.target.value })} placeholder="950" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-detail-page-field-7">Presupuesto horas/mes</Label>
              <Input id="project-detail-page-field-7" type="number" value={formData.budget_hours} onChange={(e) => setFormData({ ...formData, budget_hours: e.target.value })} placeholder="40" />
            </div>
          </div>
        )}

        {/* per_piece → precio unitario + unidad */}
        {formData.pricing_model === "per_piece" && (
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="project-detail-page-field-8">Precio por unidad (EUR)</Label>
              <Input id="project-detail-page-field-8" type="number" step="0.01" value={formData.unit_price} onChange={(e) => setFormData({ ...formData, unit_price: e.target.value })} placeholder="200" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-detail-page-field-9">Unidad</Label>
              <Input id="project-detail-page-field-9" value={formData.unit_label} onChange={(e) => setFormData({ ...formData, unit_label: e.target.value })} placeholder="briefing review, pieza, articulo..." />
            </div>
          </div>
        )}

        {/* hourly → tarifa/hora */}
        {formData.pricing_model === "hourly" && (
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="project-detail-page-field-10">Tarifa/hora (EUR)</Label>
              <Input id="project-detail-page-field-10" type="number" step="0.01" value={formData.unit_price} onChange={(e) => setFormData({ ...formData, unit_price: e.target.value })} placeholder="50" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-detail-page-field-11">Presupuesto horas</Label>
              <Input id="project-detail-page-field-11" type="number" value={formData.budget_hours} onChange={(e) => setFormData({ ...formData, budget_hours: e.target.value })} placeholder="40" />
            </div>
          </div>
        )}

        {/* project → precio cerrado */}
        {formData.pricing_model === "project" && (
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="project-detail-page-field-12">Precio total proyecto (EUR)</Label>
              <Input id="project-detail-page-field-12" type="number" step="0.01" value={formData.budget_amount} onChange={(e) => setFormData({ ...formData, budget_amount: e.target.value })} placeholder="5000" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="project-detail-page-field-13">Presupuesto horas</Label>
              <Input id="project-detail-page-field-13" type="number" value={formData.budget_hours} onChange={(e) => setFormData({ ...formData, budget_hours: e.target.value })} placeholder="80" />
            </div>
          </div>
        )}
        {/* --- Propuesta / Scope --- */}
        <div className="space-y-2">
          <Label htmlFor="project-detail-page-field-14">Propuesta / Condiciones</Label>
          <textarea id="project-detail-page-field-14"
            className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring resize-y"
            value={formData.scope}
            onChange={(e) => setFormData({ ...formData, scope: e.target.value })}
            placeholder="Describe las condiciones del proyecto, alcance acordado, entregables..."
            rows={3}
          />
          <p className="text-xs text-muted-foreground">Para adjuntar la propuesta en PDF, usa la pestaña Documentos con tipo &ldquo;Propuesta&rdquo;</p>
        </div>

        {/* --- Facturación --- */}
        <div className="grid grid-cols-3 gap-4">
          <div className="space-y-2">
            <Label htmlFor="project-detail-page-field-15">Día factura (1-28)</Label>
            <Input id="project-detail-page-field-15"
              type="number"
              min="1"
              max="28"
              value={formData.billing_day}
              onChange={(e) => setFormData({ ...formData, billing_day: e.target.value })}
              placeholder="Día del mes"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="project-detail-page-field-16">Importe factura (€)</Label>
            <Input id="project-detail-page-field-16"
              type="number"
              step="0.01"
              value={formData.billing_amount}
              onChange={(e) => setFormData({ ...formData, billing_amount: e.target.value })}
              placeholder="0.00"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="project-detail-page-field-17">Próxima factura</Label>
            <Input id="project-detail-page-field-17"
              type="date"
              value={formData.next_billing_date}
              onChange={(e) => setFormData({ ...formData, next_billing_date: e.target.value })}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="project-detail-page-field-18">Google Search Console URL</Label>
            <Input id="project-detail-page-field-18"
              type="url"
              placeholder="https://ejemplo.com"
              value={formData.gsc_url}
              onChange={(e) => setFormData({ ...formData, gsc_url: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="project-detail-page-field-19">GA4 Property ID</Label>
            <Input id="project-detail-page-field-19"
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
          <Label htmlFor="project-detail-page-field-25">Nombre de la plantilla *</Label>
          <Input id="project-detail-page-field-25"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ej: SEO Mensual Completo"
            required
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="project-detail-page-field-26">Descripción</Label>
          <Input id="project-detail-page-field-26"
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

// ---------------------------------------------------------------------------
// Alerta de presupuesto de horas (semanal informativo + mensual = techo de alerta)
// ---------------------------------------------------------------------------

type BudgetStatus = "ok" | "warning" | "over"

function budgetStatus(used: number, budget: number | null | undefined): BudgetStatus | null {
  if (!budget || budget <= 0) return null
  const pct = used / budget
  if (pct >= 1) return "over"
  if (pct >= 0.8) return "warning"
  return "ok"
}

const STATUS_STYLES: Record<BudgetStatus, { bar: string; text: string }> = {
  ok: { bar: "bg-brand", text: "text-muted-foreground" },
  warning: { bar: "bg-amber-500", text: "text-amber-600" },
  over: { bar: "bg-red-500", text: "text-red-600" },
}

function BudgetRow({
  label,
  used,
  budget,
  note,
}: {
  label: string
  used: number
  budget: number | null | undefined
  note: string
}) {
  if (!budget || budget <= 0) return null
  const status = budgetStatus(used, budget) ?? "ok"
  const style = STATUS_STYLES[status]
  const remaining = budget - used
  const pct = Math.min(100, (used / budget) * 100)
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-sm">
        <span className="flex items-center gap-1.5 font-medium">
          {status !== "ok" && <AlertTriangle className="w-3.5 h-3.5" />}
          {label}
        </span>
        <span className={`mono ${style.text}`}>
          {used.toFixed(1)}h / {budget}h
          {" · "}
          {remaining >= 0 ? `quedan ${remaining.toFixed(1)}h` : `pasado ${Math.abs(remaining).toFixed(1)}h`}
        </span>
      </div>
      <div className="h-2 bg-secondary rounded-full overflow-hidden">
        <div className={`h-full transition-all ${style.bar}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-muted-foreground">{note}</p>
    </div>
  )
}

function MonthlyCycleCard({ cycle, month, currentMonth, loading, error, onMonthChange, onRetry, canOpenTasks }: {
  cycle?: ProjectMonthlyCycle
  month: string
  currentMonth: string
  loading: boolean
  error: boolean
  onMonthChange: (month: string) => void
  onRetry: () => void
  canOpenTasks: boolean
}) {
  const label = format(parseISO(`${month}-01T12:00:00`), "MMMM yyyy", { locale: es })
  return <Card>
    <CardHeader className="pb-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><CardTitle className="text-base">Ciclo de {label}</CardTitle><p className="mt-1 text-xs text-muted-foreground">Actividad real de este proyecto recurrente durante el mes civil.</p></div>
        {month !== currentMonth && <Button size="sm" variant="outline" onClick={() => onMonthChange(currentMonth)}>Volver al mes actual</Button>}
      </div>
    </CardHeader>
    <CardContent className="space-y-4">
      {loading ? <p role="status" className="text-sm text-muted-foreground">Cargando ciclo mensual…</p>
        : error ? <div role="alert" className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm">No se pudo cargar este ciclo.</p><Button size="sm" variant="outline" onClick={onRetry}>Reintentar</Button></div>
        : cycle && <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <CycleMetric label="Planificadas en el mes" value={String(cycle.planned_count)} />
            <CycleMetric label="Finalizadas en el mes" value={String(cycle.completed_in_month_count)} />
            <CycleMetric label="Horas reales del mes" value={`${cycle.used_hours.toFixed(1)}h`} />
            <CycleMetric label={month === currentMonth ? "Horas restantes" : "Diferencia con presupuesto actual"} value={cycle.remaining_hours == null ? "Sin presupuesto" : `${cycle.remaining_hours.toFixed(1)}h`} />
          </div>
          {cycle.budget_hours != null && <HoursBudgetCard weeklyBudget={null} monthlyBudget={cycle.budget_hours} usedWeek={0} usedMonth={cycle.used_hours} showWeekly={false} monthLabel={month === currentMonth ? "Este mes" : "Presupuesto actual de referencia"} />}
          <div>
            <p className="mb-2 text-sm font-medium">Tareas planificadas o finalizadas en el mes</p>
            {cycle.tasks.length ? <ul className="max-h-72 divide-y overflow-y-auto rounded-lg border">
              {cycle.tasks.map(task => <li key={task.id} className="flex flex-col gap-1 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between">
                {canOpenTasks ? <Link className="min-w-0 break-words text-primary hover:underline" to={`/tasks?task=${task.id}`}>{task.title}</Link> : <span className="min-w-0 break-words">{task.title}</span>}
                <span className="shrink-0 text-xs text-muted-foreground">{task.scheduled_date ? `Planificada ${format(parseISO(`${task.scheduled_date}T12:00:00`), "d MMM", { locale: es })}` : "Sin fecha planificada"}{task.completed_at ? ` · finalizada ${formatCivilDate(businessDateString(parseApiInstant(task.completed_at)), { day: "numeric", month: "short" })}` : ""}</span>
              </li>)}
            </ul> : <p className="text-sm text-muted-foreground">No hay instancias planificadas ni finalizadas en este mes.</p>}
          </div>
        </>}
      <details className="border-t pt-3">
        <summary className="cursor-pointer text-sm text-muted-foreground">Consultar otro mes</summary>
        <label className="mt-3 block text-sm font-medium">Mes del historial <input aria-label="Mes del ciclo" type="month" value={month} max={currentMonth} onChange={event => event.target.value && onMonthChange(event.target.value)} className="ml-2 rounded-md border border-border bg-background px-2 py-1.5" /></label>
      </details>
    </CardContent>
  </Card>
}

function CycleMetric({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0 rounded-lg bg-muted/40 p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 break-words text-lg font-semibold">{value}</p></div>
}

function HoursBudgetCard({
  weeklyBudget,
  monthlyBudget,
  usedWeek,
  usedMonth,
  showWeekly = true,
  monthLabel = "Este mes",
}: {
  weeklyBudget: number | null
  monthlyBudget: number | null
  usedWeek: number
  usedMonth: number
  showWeekly?: boolean
  monthLabel?: string
}) {
  const monthStatus = budgetStatus(usedMonth, monthlyBudget)
  const alert = monthStatus === "warning" || monthStatus === "over"
  return (
    <Card className={alert ? "border-amber-400/60" : undefined}>
      <CardContent className="p-4 space-y-4">
        <div className="flex items-center gap-1.5">
          <Clock className="w-4 h-4" />
          <span className="text-sm font-medium">Presupuesto de horas</span>
        </div>
        {showWeekly && <BudgetRow
          label="Esta semana"
          used={usedWeek}
          budget={weeklyBudget}
          note="Guía visual de carga semanal. Se puede compensar entre semanas."
        />}
        <BudgetRow
          label={monthLabel}
          used={usedMonth}
          budget={monthlyBudget}
          note="Aviso al llegar al 80 % del presupuesto mensual."
        />
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Aviso de cierre para proyectos puntuales (fecha final + horas vs tiempo restante)
// ---------------------------------------------------------------------------

function ProjectClosingCard({ closing }: { closing: ProjectClosingStatus }) {
  const style = STATUS_STYLES[closing.status]
  const endDate = new Date(closing.target_end_date).toLocaleDateString("es-ES", {
    day: "numeric",
    month: "short",
    year: "numeric",
  })

  let when: string
  if (closing.overdue) {
    when = `Vencido hace ${Math.abs(closing.days_left)}d`
  } else if (closing.days_left === 0) {
    when = "Cierra hoy"
  } else {
    when = `Cierra en ${closing.days_left}d`
  }

  const hasHours = closing.budget_hours != null && closing.budget_hours > 0
  const pct = hasHours ? Math.min(100, (closing.hours_pct ?? 0) * 100) : 0

  return (
    <Card className={closing.status !== "ok" ? "border-amber-400/60" : undefined}>
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-sm font-medium">
            <Calendar className="w-4 h-4" />
            Cierre del proyecto
          </span>
          <span className={`text-sm font-medium ${style.text}`}>
            {closing.status !== "ok" && <AlertTriangle className="inline w-3.5 h-3.5 mr-1" />}
            {when}
          </span>
        </div>
        <p className="text-xs text-muted-foreground">Fecha final: {endDate}</p>

        {hasHours && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Horas vs presupuesto</span>
              <span className={`mono ${style.text}`}>
                {closing.used_hours.toFixed(1)}h / {closing.budget_hours}h
                {closing.remaining_hours != null &&
                  ` · ${closing.remaining_hours >= 0
                    ? `quedan ${closing.remaining_hours.toFixed(1)}h`
                    : `pasado ${Math.abs(closing.remaining_hours).toFixed(1)}h`}`}
              </span>
            </div>
            <div className="h-2 bg-secondary rounded-full overflow-hidden">
              <div className={`h-full transition-all ${style.bar}`} style={{ width: `${pct}%` }} />
            </div>
            {closing.pace_risk && (
              <p className="text-xs text-amber-600">
                Ritmo de horas por delante del plazo: riesgo de agotar el presupuesto antes de cerrar.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
