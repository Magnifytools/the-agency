import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { Plus, FolderKanban, Calendar, Trash2, Repeat } from "lucide-react"
import { toast } from "sonner"
import { projectsApi, clientsApi } from "@/lib/api"
import type { ProjectListItem, ProjectStatus } from "@/lib/types"
import { usePagination } from "@/hooks/use-pagination"
import { Pagination } from "@/components/ui/pagination"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
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

export default function ProjectsPage() {
  const queryClient = useQueryClient()
  const { page, pageSize, setPage, reset } = usePagination(25)
  const [statusFilter, setStatusFilter] = useState<string>("")
  const [typeFilter, setTypeFilter] = useState<string>("")
  const [showNewDialog, setShowNewDialog] = useState(false)
  const [showTemplateDialog, setShowTemplateDialog] = useState(false)
  const [deleteId, setDeleteId] = useState<number | null>(null)

  const { data: projectsData, isLoading } = useQuery({
    queryKey: ["projects", statusFilter, page, pageSize],
    queryFn: () => projectsApi.list({ ...(statusFilter ? { status: statusFilter } : {}), page, page_size: pageSize }),
  })
  const projects = projectsData?.items ?? []

  const { data: clients = [] } = useQuery({
    queryKey: ["clients-all-active"],
    queryFn: () => clientsApi.listAll("active"),
  })

  const { data: templates = {} } = useQuery({
    queryKey: ["project-templates"],
    queryFn: () => projectsApi.templates(),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => projectsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] })
      toast.success("Proyecto eliminado")
      setDeleteId(null)
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar proyecto")),
  })

  const formatDate = (date: string | null) => {
    if (!date) return "—"
    return new Date(date).toLocaleDateString("es-ES", { day: "numeric", month: "short" })
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Proyectos</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Gestiona proyectos con fases y tareas
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setShowNewDialog(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Nuevo vacío
          </Button>
          <Button onClick={() => setShowTemplateDialog(true)}>
            <FolderKanban className="h-4 w-4 mr-2" />
            Desde plantilla
          </Button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-4">
        <Select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); reset() }}
          className="w-48"
        >
          <option value="">Todos los estados</option>
          <option value="planning">Planificación</option>
          <option value="active">Activo</option>
          <option value="on_hold">Pausado</option>
          <option value="completed">Completado</option>
          <option value="cancelled">Cancelado</option>
        </Select>
        <Select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="w-48"
        >
          <option value="">Todos los tipos</option>
          <option value="recurring">Recurrentes</option>
          <option value="one_time">Puntuales</option>
        </Select>
      </div>

      {/* Projects Grid */}
      {isLoading ? (
        <div className="text-muted-foreground">Cargando...</div>
      ) : (typeFilter ? projects.filter(p => typeFilter === "recurring" ? p.is_recurring : !p.is_recurring) : projects).length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <FolderKanban className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
            <p className="text-muted-foreground">No hay proyectos</p>
            <Button className="mt-4" onClick={() => setShowTemplateDialog(true)}>
              Crear primer proyecto
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {(typeFilter ? projects.filter(p => typeFilter === "recurring" ? p.is_recurring : !p.is_recurring) : projects).map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              onDelete={() => setDeleteId(project.id)}
              formatDate={formatDate}
            />
          ))}
        </div>
      )}

      <Pagination page={page} pageSize={pageSize} total={projectsData?.total ?? 0} onPageChange={setPage} />

      {/* New Empty Project Dialog */}
      <NewProjectDialog
        open={showNewDialog}
        onOpenChange={setShowNewDialog}
        clients={clients}
      />

      {/* New Project from Template Dialog */}
      <TemplateDialog
        open={showTemplateDialog}
        onOpenChange={setShowTemplateDialog}
        clients={clients}
        templates={templates}
      />

      {/* Delete Confirmation */}
      <ConfirmDialog
        open={deleteId !== null}
        onOpenChange={(open) => !open && setDeleteId(null)}
        title="Eliminar proyecto"
        description="¿Seguro que quieres eliminar este proyecto? Las tareas no se eliminarán, solo se desvincularán."
        onConfirm={() => deleteId && deleteMutation.mutate(deleteId)}
      />
    </div>
  )
}

function ProjectCard({
  project,
  onDelete,
  formatDate,
}: {
  project: ProjectListItem
  onDelete: () => void
  formatDate: (d: string | null) => string
}) {
  return (
    <Link to={`/projects/${project.id}`}>
      <Card className="hover:border-brand/40 transition-colors cursor-pointer group">
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between">
            <div className="flex-1 min-w-0">
              <CardTitle className="text-base font-semibold text-foreground truncate">
                {project.name}
              </CardTitle>
              <p className="text-sm text-muted-foreground mt-1">{project.client_name}</p>
            </div>
            <button
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                onDelete()
              }}
              className="p-1.5 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Badge variant={STATUS_VARIANTS[project.status]}>
                {STATUS_LABELS[project.status]}
              </Badge>
              {project.is_recurring && (
                <Badge variant="secondary" className="gap-1">
                  <Repeat className="h-3 w-3" />Recurrente
                </Badge>
              )}
            </div>
            <span className="text-sm text-muted-foreground">
              {project.progress_percent}%
            </span>
          </div>

          {/* Progress bar */}
          <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
            <div
              className="h-full bg-brand transition-all"
              style={{ width: `${project.progress_percent}%` }}
            />
          </div>

          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <div className="flex items-center gap-1">
              <Calendar className="h-3.5 w-3.5" />
              {formatDate(project.target_end_date)}
            </div>
            <div>
              {project.completed_task_count}/{project.task_count} tareas
            </div>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

function NewProjectDialog({
  open,
  onOpenChange,
  clients,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  clients: { id: number; name: string }[]
}) {
  const queryClient = useQueryClient()
  const [formData, setFormData] = useState({
    name: "",
    client_id: "",
    project_type: "",
    start_date: "",
    target_end_date: "",
  })

  const createMutation = useMutation({
    mutationFn: () =>
      projectsApi.create({
        name: formData.name,
        client_id: parseInt(formData.client_id),
        project_type: formData.project_type || undefined,
        start_date: formData.start_date || undefined,
        target_end_date: formData.target_end_date || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] })
      toast.success("Proyecto creado")
      onOpenChange(false)
      setFormData({ name: "", client_id: "", project_type: "", start_date: "", target_end_date: "" })
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear proyecto")),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Nuevo proyecto</DialogTitle>
      </DialogHeader>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          createMutation.mutate()
        }}
        className="space-y-4 mt-4"
      >
        <div className="space-y-2">
          <Label>Nombre *</Label>
          <Input
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="Auditoría SEO Q1"
            required
          />
        </div>
        <div className="space-y-2">
          <Label>Cliente *</Label>
          <Select
            value={formData.client_id}
            onChange={(e) => setFormData({ ...formData, client_id: e.target.value })}
            required
          >
            <option value="">Seleccionar cliente</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
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
            <Label>Fecha fin objetivo</Label>
            <Input
              type="date"
              value={formData.target_end_date}
              onChange={(e) => setFormData({ ...formData, target_end_date: e.target.value })}
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-4">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button type="submit" disabled={createMutation.isPending}>
            {createMutation.isPending ? "Creando..." : "Crear proyecto"}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

function TemplateDialog({
  open,
  onOpenChange,
  clients,
  templates,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  clients: { id: number; name: string }[]
  templates: Record<string, { name: string; phase_count: number; task_count: number }>
}) {
  const queryClient = useQueryClient()
  const [clientId, setClientId] = useState("")
  const [templateKey, setTemplateKey] = useState("")
  const [startDate, setStartDate] = useState("")

  const createMutation = useMutation({
    mutationFn: () =>
      projectsApi.createFromTemplate(parseInt(clientId), templateKey, startDate || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] })
      toast.success("Proyecto creado desde plantilla")
      onOpenChange(false)
      setClientId("")
      setTemplateKey("")
      setStartDate("")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear proyecto")),
  })

  const selectedTemplate = templateKey ? templates[templateKey] : null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Crear desde plantilla</DialogTitle>
      </DialogHeader>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          createMutation.mutate()
        }}
        className="space-y-4 mt-4"
      >
        <div className="space-y-2">
          <Label>Cliente *</Label>
          <Select value={clientId} onChange={(e) => setClientId(e.target.value)} required>
            <option value="">Seleccionar cliente</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-2">
          <Label>Plantilla *</Label>
          <Select value={templateKey} onChange={(e) => setTemplateKey(e.target.value)} required>
            <option value="">Seleccionar plantilla</option>
            {Object.entries(templates).map(([key, t]) => (
              <option key={key} value={key}>
                {t.name}
              </option>
            ))}
          </Select>
        </div>

        {selectedTemplate && (
          <div className="p-3 bg-surface rounded-lg text-sm">
            <p className="text-muted-foreground">
              Esta plantilla creará <span className="text-foreground font-medium">{selectedTemplate.phase_count} fases</span> y{" "}
              <span className="text-foreground font-medium">{selectedTemplate.task_count} tareas</span>
            </p>
          </div>
        )}

        <div className="space-y-2">
          <Label>Fecha de inicio</Label>
          <Input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            placeholder="Hoy si se deja vacío"
          />
        </div>

        <div className="flex justify-end gap-2 pt-4">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button type="submit" disabled={createMutation.isPending}>
            {createMutation.isPending ? "Creando..." : "Crear proyecto"}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
