import { useState } from "react"
import { useParams, Link } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  ArrowLeft,
  Calendar,
  CheckCircle2,
  Circle,
  Clock,
  Edit2,
  Plus,
  PlayCircle,
} from "lucide-react"
import { toast } from "sonner"
import { projectsApi, tasksApi } from "@/lib/api"
import type { Project, ProjectStatus, PhaseStatus, TaskStatus } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { getErrorMessage } from "@/lib/utils"

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

  if (isLoading) {
    return <div className="text-muted-foreground">Cargando...</div>
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
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-4">
          <Link
            to="/projects"
            className="mt-1 p-2 rounded-lg hover:bg-card text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
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

      {/* Phases and Tasks */}
      <div className="space-y-4">
        <h2 className="text-lg font-semibold">Fases y Tareas</h2>

        {tasksData?.phases?.map((phaseGroup: any) => {
          const phase = phaseGroup.phase
          const tasks = phaseGroup.tasks
          const PhaseIcon = PHASE_STATUS_ICONS[phase.status as PhaseStatus] || Circle
          const completedTasks = tasks.filter((t: any) => t.status === "completed").length

          return (
            <Card key={phase.id}>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <PhaseIcon
                      className={`h - 5 w - 5 ${phase.status === "completed"
                        ? "text-success"
                        : phase.status === "in_progress"
                          ? "text-brand"
                          : "text-muted-foreground"
                        } `}
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
                    {tasks.map((task: any) => (
                      <TaskRow
                        key={task.id}
                        task={task}
                        onStatusChange={(status) =>
                          updateTaskMutation.mutate({ taskId: task.id, status })
                        }
                      />
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })}

        {/* Unassigned Tasks */}
        {tasksData?.unassigned_tasks?.length > 0 && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold text-foreground">
                Tareas sin fase asignada
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1">
                {tasksData.unassigned_tasks.map((task: any) => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    onStatusChange={(status) =>
                      updateTaskMutation.mutate({ taskId: task.id, status })
                    }
                  />
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Edit Dialog */}
      {project && (
        <EditProjectDialog
          open={showEditDialog}
          onOpenChange={setShowEditDialog}
          project={project}
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
    </div>
  )
}

function TaskRow({
  task,
  onStatusChange,
}: {
  task: { id: number; title: string; status: TaskStatus; due_date: string | null; assigned_to: string | null }
  onStatusChange: (status: TaskStatus) => void
}) {
  const isCompleted = task.status === "completed"

  return (
    <div className="flex items-center gap-3 py-2 px-2 rounded-lg hover:bg-card/50 group">
      <button
        onClick={() => onStatusChange(isCompleted ? "pending" : "completed")}
        className={`flex - shrink - 0 ${isCompleted ? "text-success" : "text-muted-foreground hover:text-brand"} `}
      >
        {isCompleted ? (
          <CheckCircle2 className="h-5 w-5" />
        ) : (
          <Circle className="h-5 w-5" />
        )}
      </button>
      <div className="flex-1 min-w-0">
        <p className={`text - sm ${isCompleted ? "line-through text-muted-foreground" : ""} `}>
          {task.title}
        </p>
      </div>
      {task.assigned_to && (
        <span className="text-xs text-muted-foreground">{task.assigned_to}</span>
      )}
      <Link
        to={`/ tasks ? id = ${task.id} `}
        className="text-xs text-muted-foreground hover:text-brand opacity-0 group-hover:opacity-100"
      >
        Ver
      </Link>
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
        <div className="grid grid-cols-2 gap-4">
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
