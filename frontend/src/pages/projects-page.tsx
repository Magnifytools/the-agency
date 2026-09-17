import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { Plus, FolderKanban, Calendar, Trash2, Repeat, FileUp, FileText, UserRound } from "lucide-react"
import { toast } from "sonner"
import { projectsApi, clientsApi, usersApi } from "@/lib/api"
import type { ProjectListItem, ProjectStatus, ProjectDraft, User } from "@/lib/types"
import { projectPeriodBounds } from "@/lib/project-filters"
import { invalidateProjectChange } from "@/lib/query-keys"
import { projectCreateFromDraft } from "@/lib/project-draft"
import { Pagination } from "@/components/ui/pagination"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { EmptyState } from "@/components/ui/empty-state"
import { getErrorMessage } from "@/lib/utils"
import { formatCurrency } from "@/lib/format"


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
  const [searchParams, setSearchParams] = useSearchParams()
  const pageSize = 25
  const rawPage = Number(searchParams.get("page") || 1)
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1
  const statusFilter = searchParams.get("status") || ""
  const typeFilter = searchParams.get("type") || ""
  const periodFilter = searchParams.get("period") || ""
  const setFilter = (key: string, value: string) => setSearchParams((previous) => {
    const next = new URLSearchParams(previous)
    if (value) next.set(key, value)
    else next.delete(key)
    next.delete("page")
    return next
  })
  const setPage = (value: number) => setSearchParams((previous) => {
    const next = new URLSearchParams(previous)
    next.set("page", String(value))
    return next
  })
  const periodBounds = projectPeriodBounds(periodFilter)
  const [showNewDialog, setShowNewDialog] = useState(false)
  const [showTemplateDialog, setShowTemplateDialog] = useState(false)
  const [showImportDialog, setShowImportDialog] = useState(false)
  const [showImportTextDialog, setShowImportTextDialog] = useState(false)
  const [deleteId, setDeleteId] = useState<number | null>(null)

  const { data: projectsData, isLoading, isError, refetch } = useQuery({
    queryKey: ["projects", statusFilter, typeFilter, periodBounds, page, pageSize],
    queryFn: () => projectsApi.list({
      ...(statusFilter ? { status: statusFilter } : {}),
      ...(["recurring", "one_time"].includes(typeFilter) ? { is_recurring: typeFilter === "recurring" } : {}),
      ...periodBounds, page, page_size: pageSize,
    }),
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
  const { data: allUsers = [] } = useQuery({
    queryKey: ["users-all"],
    queryFn: () => usersApi.listAll(),
  })
  const activeUsers = allUsers.filter((user) => user.is_active)

  const deleteMutation = useMutation({
    mutationFn: (id: number) => projectsApi.delete(id),
    onSuccess: (_data, deletedId) => {
      invalidateProjectChange(queryClient, {clientId: projects.find((project) => project.id === deletedId)?.client_id})
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
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Proyectos</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Gestiona proyectos con fases y tareas
          </p>
        </div>
        <Button onClick={() => setShowNewDialog(true)}>
          <Plus className="h-4 w-4 mr-2" /> Nuevo proyecto
        </Button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <Select
          value={statusFilter}
          aria-label="Estado del proyecto"
          onChange={(e) => setFilter("status", e.target.value)}
          className="w-full sm:w-48"
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
          aria-label="Tipo de proyecto"
          onChange={(e) => setFilter("type", e.target.value)}
          className="w-full sm:w-48"
        >
          <option value="">Todos los tipos</option>
          <option value="recurring">Recurrentes</option>
          <option value="one_time">Puntuales</option>
        </Select>
        <Select
          value={periodFilter}
          aria-label="Período del proyecto"
          onChange={(e) => setFilter("period", e.target.value)}
          className="w-full sm:w-48"
        >
          <option value="">Todos los periodos</option>
          <option value="week">Esta semana</option>
          <option value="month">Este mes</option>
          <option value="quarter">Este trimestre</option>
        </Select>
      </div>

      {/* Projects Grid */}
      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="rounded-xl border border-border bg-card p-4 space-y-3">
              <div className="animate-pulse rounded-md bg-muted h-4 w-1/3" />
              <div className="animate-pulse rounded-md bg-muted h-8 w-1/2" />
              <div className="animate-pulse rounded-md bg-muted h-3 w-2/3" />
            </div>
          ))}
        </div>
      ) : isError ? (
        <div role="alert" className="rounded-lg border p-4 space-y-2">
          <p>No se pudieron cargar los proyectos. Vuelve a intentarlo.</p>
          <Button variant="outline" onClick={() => void refetch()}>Reintentar</Button>
        </div>
      ) : projects.length === 0 ? (
        <EmptyState
          icon={FolderKanban}
          title={statusFilter || typeFilter || periodFilter ? "Sin proyectos con estos filtros" : "Sin proyectos todavía"}
          description={statusFilter ? "No hay proyectos con este estado. Prueba a cambiar el filtro o crea uno nuevo." : "Organiza el trabajo en proyectos con fases y tareas. Puedes empezar desde una plantilla o importar una propuesta."}
          actionLabel="Crear un proyecto"
          onAction={() => setShowNewDialog(true)}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
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
        users={activeUsers}
        onTemplate={() => { setShowNewDialog(false); setShowTemplateDialog(true) }}
        onPdf={() => { setShowNewDialog(false); setShowImportDialog(true) }}
        onText={() => { setShowNewDialog(false); setShowImportTextDialog(true) }}
      />

      {/* New Project from Template Dialog */}
      <TemplateDialog
        open={showTemplateDialog}
        onOpenChange={setShowTemplateDialog}
        clients={clients}
        users={activeUsers}
        templates={templates}
      />

      {/* Import from PDF Dialog */}
      <ImportFromPdfDialog
        open={showImportDialog}
        onOpenChange={setShowImportDialog}
        clients={clients}
        users={activeUsers}
      />

      {/* Import from TXT/MD Dialog */}
      <ImportFromTextDialog
        open={showImportTextDialog}
        onOpenChange={setShowImportTextDialog}
        clients={clients}
        users={activeUsers}
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
              <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1"><UserRound className="h-3 w-3" />{project.owner_name || "Sin responsable"}</p>
            </div>
            <button
              aria-label={`Eliminar proyecto ${project.name}`}
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
              {project.progress_percent}% completado
            </span>
          </div>

          {/* Progress bar */}
          <div role="progressbar" aria-label="Tareas completadas" aria-valuenow={project.progress_percent} aria-valuemin={0} aria-valuemax={100} className="h-1.5 bg-secondary rounded-full overflow-hidden">
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
  users,
  onTemplate, onPdf, onText,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  clients: { id: number; name: string }[]
  users: User[]
  onTemplate: () => void
  onPdf: () => void
  onText: () => void
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const emptyForm = {
    name: "",
    client_id: "",
    project_type: "",
    start_date: "",
    target_end_date: "",
    is_recurring: false,
    pricing_model: "",
    monthly_fee: "",
    unit_price: "",
    unit_label: "",
    scope: "",
    budget_amount: "",
    weekly_hours_budget: "",
    monthly_hours_budget: "",
    owner_id: "",
  }
  const [formData, setFormData] = useState(emptyForm)

  const createMutation = useMutation({
    mutationFn: () =>
      projectsApi.create({
        name: formData.name,
        client_id: parseInt(formData.client_id),
        project_type: formData.project_type || undefined,
        start_date: formData.start_date || undefined,
        target_end_date: formData.target_end_date || undefined,
        is_recurring: formData.is_recurring,
        pricing_model: formData.pricing_model || undefined,
        monthly_fee: formData.pricing_model === "monthly" && formData.monthly_fee ? parseFloat(formData.monthly_fee) : undefined,
        unit_price: ["hourly", "per_piece"].includes(formData.pricing_model) && formData.unit_price ? parseFloat(formData.unit_price) : undefined,
        unit_label: ["hourly", "per_piece"].includes(formData.pricing_model) ? formData.unit_label || undefined : undefined,
        scope: formData.scope || undefined,
        budget_amount: formData.budget_amount ? parseFloat(formData.budget_amount) : undefined,
        weekly_hours_budget: formData.weekly_hours_budget ? parseFloat(formData.weekly_hours_budget) : undefined,
        monthly_hours_budget: formData.monthly_hours_budget ? parseFloat(formData.monthly_hours_budget) : undefined,
        owner_id: formData.owner_id ? parseInt(formData.owner_id) : undefined,
      }),
    onSuccess: (project) => {
      invalidateProjectChange(queryClient, {clientId: project.client_id})
      toast.success("Proyecto creado")
      onOpenChange(false)
      setFormData(emptyForm)
      navigate(`/projects/${project.id}?created=1`)
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear proyecto")),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader><DialogTitle>Nuevo proyecto</DialogTitle></DialogHeader>
      <p className="text-sm text-muted-foreground">Empieza con el nombre y el cliente. Podrás concretar el trabajo en su ficha.</p>
      <form onSubmit={(e) => { e.preventDefault(); createMutation.mutate() }} className="space-y-4 mt-4">
        <div className="space-y-2">
          <Label htmlFor="new-project-name">Nombre *</Label>
          <Input id="new-project-name" value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })} placeholder="Ej. Rediseño de la web" required />
        </div>
        <OwnerSelect id="new-project-owner" value={formData.owner_id} users={users} onChange={(owner_id) => setFormData({ ...formData, owner_id })} />
        <div className="space-y-2">
          <Label htmlFor="new-project-client">Cliente *</Label>
          <Select id="new-project-client" value={formData.client_id} onChange={(e) => setFormData({ ...formData, client_id: e.target.value })} required>
            <option value="">Seleccionar cliente</option>
            {clients.map((client) => <option key={client.id} value={client.id}>{client.name}</option>)}
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="new-project-kind">Tipo de trabajo</Label>
          <Select id="new-project-kind" value={formData.is_recurring ? "recurring" : "one_time"} onChange={(e) => setFormData({ ...formData, is_recurring: e.target.value === "recurring", pricing_model: e.target.value !== "recurring" && formData.pricing_model === "monthly" ? "" : formData.pricing_model })}>
            <option value="one_time">Proyecto puntual</option><option value="recurring">Servicio recurrente</option>
          </Select>
          <p className="text-xs text-muted-foreground">{formData.is_recurring ? "Trabajo continuo que se revisa cada mes." : "Trabajo con una entrega final."}</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="new-project-end">{formData.is_recurring ? "Fin del servicio (opcional)" : "Entrega prevista (opcional)"}</Label>
          <Input id="new-project-end" type="date" value={formData.target_end_date} min={formData.start_date || undefined} onChange={(e) => setFormData({ ...formData, target_end_date: e.target.value })} />
        </div>
        {formData.is_recurring && <div className="space-y-2">
          <Label htmlFor="new-project-monthly-hours">Horas acordadas por mes (opcional)</Label>
          <Input id="new-project-monthly-hours" type="number" min="0" step="0.5" value={formData.monthly_hours_budget} onChange={(e) => setFormData({ ...formData, monthly_hours_budget: e.target.value })} />
          <p className="text-xs text-muted-foreground">Si no existe un acuerdo, déjalo vacío. Puedes concretarlo después; no se estiman horas automáticamente.</p>
        </div>}
        <details className="border-t pt-3">
          <summary className="cursor-pointer text-sm font-medium py-2">Alcance, fechas y condiciones económicas</summary>
          <div className="space-y-4 pt-3">
            <div className="space-y-2"><Label htmlFor="new-project-scope">Alcance acordado</Label><textarea id="new-project-scope" className="w-full min-h-20 rounded-md border border-input bg-background p-3 text-sm" value={formData.scope} onChange={(e) => setFormData({ ...formData, scope: e.target.value })} /></div>
            <div className="space-y-2"><Label htmlFor="new-project-start">Fecha de inicio (opcional)</Label><Input id="new-project-start" type="date" max={formData.target_end_date || undefined} value={formData.start_date} onChange={(e) => setFormData({ ...formData, start_date: e.target.value })} /></div>
            <div className="space-y-2"><Label htmlFor="new-project-pricing">Modelo de precio</Label><Select id="new-project-pricing" value={formData.pricing_model} onChange={(e) => setFormData({ ...formData, pricing_model: e.target.value })}><option value="">Sin definir</option>{formData.is_recurring && <option value="monthly">Mensual fijo</option>}<option value="project">Precio cerrado</option><option value="hourly">Por hora</option><option value="per_piece">Por unidad</option></Select></div>
            {formData.pricing_model === "monthly" && <div className="space-y-2"><Label htmlFor="new-project-fee">Tarifa mensual (EUR)</Label><Input id="new-project-fee" type="number" min="0" step="0.01" value={formData.monthly_fee} onChange={(e) => setFormData({ ...formData, monthly_fee: e.target.value })} /></div>}
            {["hourly", "per_piece"].includes(formData.pricing_model) && <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2"><Label htmlFor="new-project-unit-price">Precio por unidad (EUR)</Label><Input id="new-project-unit-price" type="number" min="0" step="0.01" value={formData.unit_price} onChange={(e) => setFormData({ ...formData, unit_price: e.target.value })} /></div>
              <div className="space-y-2"><Label htmlFor="new-project-unit">Unidad</Label><Input id="new-project-unit" value={formData.unit_label} placeholder="hora, artículo…" onChange={(e) => setFormData({ ...formData, unit_label: e.target.value })} /></div>
            </div>}
            <div className="space-y-2"><Label htmlFor="new-project-budget">Presupuesto total (EUR, opcional)</Label><Input id="new-project-budget" type="number" min="0" step="0.01" value={formData.budget_amount} onChange={(e) => setFormData({ ...formData, budget_amount: e.target.value })} /><p className="text-xs text-muted-foreground">Importe total acordado. No se calcula a partir de la tarifa mensual.</p></div>
            {!formData.is_recurring && <div className="space-y-2"><Label htmlFor="new-project-monthly-hours">Límite de horas mensual (opcional)</Label><Input id="new-project-monthly-hours" type="number" min="0" step="0.5" value={formData.monthly_hours_budget} onChange={(e) => setFormData({ ...formData, monthly_hours_budget: e.target.value })} /></div>}
            <div className="space-y-2"><Label htmlFor="new-project-weekly-hours">Referencia de horas por semana (opcional)</Label><Input id="new-project-weekly-hours" type="number" min="0" step="0.5" value={formData.weekly_hours_budget} onChange={(e) => setFormData({ ...formData, weekly_hours_budget: e.target.value })} /></div>
          </div>
        </details>
        {createMutation.isError && <p role="alert" className="text-sm text-destructive">{getErrorMessage(createMutation.error, "No se pudo crear. Tus datos siguen aquí; vuelve a intentarlo.")}</p>}
        <div className="flex justify-end gap-2 pt-2"><Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button><Button type="submit" disabled={createMutation.isPending || !formData.name.trim() || !formData.client_id}>{createMutation.isPending ? "Creando…" : "Crear proyecto"}</Button></div>
      </form>
      <details className="border-t mt-4 pt-3">
        <summary className="cursor-pointer py-2 text-sm">Partir de una plantilla o un documento</summary>
        <div className="flex flex-wrap gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onTemplate}><FolderKanban className="h-4 w-4 mr-2" />Usar plantilla</Button>
          <Button type="button" variant="outline" onClick={onPdf}><FileUp className="h-4 w-4 mr-2" />Importar PDF</Button>
          <Button type="button" variant="outline" onClick={onText}><FileText className="h-4 w-4 mr-2" />Importar TXT/MD</Button>
        </div>
      </details>
    </Dialog>
  )
}

function TemplateDialog({
  open,
  onOpenChange,
  clients,
  templates,
  users,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  clients: { id: number; name: string }[]
  templates: Record<string, { name: string; description?: string | null; phase_count: number; task_count: number; pricing_model?: string | null; monthly_fee?: number | null; is_recurring?: boolean }>
  users: User[]
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [clientId, setClientId] = useState("")
  const [templateKey, setTemplateKey] = useState("")
  const [startDate, setStartDate] = useState("")
  const [ownerId, setOwnerId] = useState("")

  const createMutation = useMutation({
    mutationFn: () =>
      projectsApi.createFromTemplate(parseInt(clientId), templateKey, startDate || undefined, ownerId ? parseInt(ownerId) : undefined),
    onSuccess: (project) => {
      invalidateProjectChange(queryClient, {clientId: project.client_id})
      toast.success("Proyecto creado desde plantilla")
      navigate(`/projects/${project.id}?created=1`)
      onOpenChange(false)
      setClientId("")
      setTemplateKey("")
      setStartDate("")
      setOwnerId("")
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
          <Label htmlFor="projects-page-field-1">Cliente *</Label>
          <Select id="projects-page-field-1" value={clientId} onChange={(e) => setClientId(e.target.value)} required>
            <option value="">Seleccionar cliente</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </div>
        <OwnerSelect id="template-project-owner" value={ownerId} users={users} onChange={setOwnerId} />

        <div className="space-y-2">
          <Label htmlFor="projects-page-field-2">Plantilla *</Label>
          <Select id="projects-page-field-2" value={templateKey} onChange={(e) => setTemplateKey(e.target.value)} required>
            <option value="">Seleccionar plantilla</option>
            {Object.entries(templates).map(([key, t]) => (
              <option key={key} value={key}>
                {t.name}
              </option>
            ))}
          </Select>
        </div>

        {selectedTemplate && (
          <div className="p-3 bg-surface rounded-lg text-sm space-y-1.5">
            {selectedTemplate.description && (
              <p className="text-muted-foreground">{selectedTemplate.description}</p>
            )}
            <div className="flex flex-wrap gap-3 text-muted-foreground">
              <span>
                <span className="text-foreground font-medium">{selectedTemplate.phase_count}</span> fases
              </span>
              <span>
                <span className="text-foreground font-medium">{selectedTemplate.task_count}</span> tareas
              </span>
              {selectedTemplate.is_recurring && (
                <span className="flex items-center gap-1">
                  <Repeat className="h-3.5 w-3.5" /> Recurrente
                </span>
              )}
            </div>
            {(selectedTemplate.pricing_model || selectedTemplate.monthly_fee != null) && (
              <div className="flex gap-3 text-muted-foreground">
                {selectedTemplate.pricing_model && (
                  <span>Modelo: <span className="text-foreground font-medium">{selectedTemplate.pricing_model}</span></span>
                )}
                {selectedTemplate.monthly_fee != null && (
                  <span>Fee: <span className="text-foreground font-medium">{formatCurrency(selectedTemplate.monthly_fee)}</span></span>
                )}
              </div>
            )}
          </div>
        )}

        <div className="space-y-2">
          <Label htmlFor="projects-page-field-3">Fecha de inicio</Label>
          <Input id="projects-page-field-3"
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

function ImportFromPdfDialog({
  open,
  onOpenChange,
  clients,
  users,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  clients: { id: number; name: string }[]
  users: User[]
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [step, setStep] = useState<"upload" | "review">("upload")
  const [pdfFile, setPdfFile] = useState<File | null>(null)
  const [clientId, setClientId] = useState("")
  const [ownerId, setOwnerId] = useState("")
  const [formData, setFormData] = useState<Partial<ProjectDraft>>({})

  const extractMutation = useMutation({
    mutationFn: () => {
      if (!pdfFile) throw new Error("No file selected")
      return projectsApi.extractFromPdf(pdfFile)
    },
    onSuccess: (data) => {
      setFormData(data)
      setStep("review")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al analizar el PDF")),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      projectsApi.create(projectCreateFromDraft({ ...formData, owner_id: ownerId ? parseInt(ownerId) : null }, parseInt(clientId))),
    onSuccess: (project) => {
      invalidateProjectChange(queryClient, {clientId: project.client_id})
      toast.success("Proyecto creado")
      navigate(`/projects/${project.id}?created=1`)
      handleClose()
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear proyecto")),
  })

  const handleClose = () => {
    onOpenChange(false)
    setStep("upload")
    setPdfFile(null)
    setClientId("")
    setOwnerId("")
    setFormData({})
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) handleClose() }}>
      <DialogHeader>
        <DialogTitle>
          {step === "upload" ? "Importar desde PDF" : "Revisar datos extraídos"}
        </DialogTitle>
      </DialogHeader>

      {step === "upload" ? (
        <div className="space-y-4 mt-4">
          <div className="space-y-2">
            <Label htmlFor="projects-page-field-4">Propuesta PDF *</Label>
            <Input id="projects-page-field-4"
              type="file"
              accept=".pdf"
              onChange={(e) => setPdfFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <OwnerSelect id="pdf-project-owner" value={ownerId} users={users} onChange={setOwnerId} />
          <div className="space-y-2">
            <Label htmlFor="projects-page-field-5">Cliente *</Label>
            <Select id="projects-page-field-5" value={clientId} onChange={(e) => setClientId(e.target.value)} required>
              <option value="">Seleccionar cliente</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </Select>
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={handleClose}>
              Cancelar
            </Button>
            <Button
              onClick={() => extractMutation.mutate()}
              disabled={!pdfFile || !clientId || extractMutation.isPending}
            >
              {extractMutation.isPending ? "Analizando..." : "Analizar propuesta"}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4 mt-4">
          <div className="space-y-2">
            <Label htmlFor="projects-page-field-6">Nombre del proyecto *</Label>
            <Input id="projects-page-field-6"
              value={formData.name ?? ""}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="projects-page-field-7">Descripción</Label>
            <Input id="projects-page-field-7"
              value={formData.description ?? ""}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="projects-page-field-8">Tipo</Label>
              <Select id="projects-page-field-8"
                value={formData.project_type ?? ""}
                onChange={(e) => setFormData({ ...formData, project_type: e.target.value })}
              >
                <option value="">Sin tipo</option>
                <option value="seo_audit">Auditoría SEO</option>
                <option value="content_strategy">Estrategia de contenido</option>
                <option value="linkbuilding">Link building</option>
                <option value="technical_seo">SEO técnico</option>
                <option value="custom">Personalizado</option>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="projects-page-field-9">Presupuesto total (EUR)</Label>
              <Input id="projects-page-field-9"
                type="number"
                value={formData.budget_amount ?? ""}
                onChange={(e) => setFormData({ ...formData, budget_amount: e.target.value ? parseFloat(e.target.value) : undefined })}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="projects-page-field-10">Tarifa mensual (EUR)</Label>
            <Input id="projects-page-field-10"
              type="number"
              step="0.01"
              value={formData.monthly_fee ?? ""}
              onChange={(e) => setFormData({ ...formData, monthly_fee: e.target.value ? parseFloat(e.target.value) : undefined })}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="projects-page-field-11">Fecha inicio</Label>
              <Input id="projects-page-field-11"
                type="date"
                value={formData.start_date ?? ""}
                onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="projects-page-field-12">Fecha fin objetivo</Label>
              <Input id="projects-page-field-12"
                type="date"
                value={formData.target_end_date ?? ""}
                onChange={(e) => setFormData({ ...formData, target_end_date: e.target.value })}
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input
              id="is_recurring_import"
              type="checkbox"
              checked={formData.is_recurring ?? false}
              onChange={(e) => setFormData({ ...formData, is_recurring: e.target.checked })}
              className="h-4 w-4"
            />
            <Label htmlFor="is_recurring_import">Servicio recurrente (retención mensual)</Label>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="projects-page-field-13">Modelo de precio</Label>
              <Select id="projects-page-field-13"
                value={formData.pricing_model ?? ""}
                onChange={(e) => setFormData({ ...formData, pricing_model: e.target.value || undefined })}
              >
                <option value="">Sin definir</option>
                <option value="monthly">Mensual fijo</option>
                <option value="per_piece">Por pieza/unidad</option>
                <option value="hourly">Por hora</option>
                <option value="project">Precio cerrado</option>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="projects-page-field-14">Precio unitario (EUR)</Label>
              <Input id="projects-page-field-14"
                type="number"
                step="0.01"
                value={formData.unit_price ?? ""}
                onChange={(e) => setFormData({ ...formData, unit_price: e.target.value ? parseFloat(e.target.value) : undefined })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="projects-page-field-15">Unidad</Label>
              <Input id="projects-page-field-15"
                value={formData.unit_label ?? ""}
                onChange={(e) => setFormData({ ...formData, unit_label: e.target.value || undefined })}
                placeholder="pieza, hora, mes..."
              />
            </div>
          </div>
          {formData.scope && (
            <div className="space-y-2">
              <Label htmlFor="projects-page-field-16">Scope / Alcance</Label>
              <textarea id="projects-page-field-16"
                className="w-full min-h-[60px] text-sm bg-background border border-input rounded-md p-3 resize-y focus:outline-none focus:ring-2 focus:ring-ring"
                value={formData.scope ?? ""}
                onChange={(e) => setFormData({ ...formData, scope: e.target.value || undefined })}
              />
            </div>
          )}
          <div className="p-3 bg-muted/50 rounded-lg text-sm text-muted-foreground">
            Cliente: <span className="text-foreground font-medium">{clients.find(c => c.id === parseInt(clientId))?.name}</span>
            {formData.client_name && formData.client_name !== clients.find(c => c.id === parseInt(clientId))?.name && (
              <span> · Detectado en PDF: {formData.client_name}</span>
            )}
          </div>
          <div className="flex justify-between gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setStep("upload")}>
              ← Volver
            </Button>
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={handleClose}>
                Cancelar
              </Button>
              <Button
                onClick={() => createMutation.mutate()}
                disabled={!formData.name || createMutation.isPending}
              >
                {createMutation.isPending ? "Creando..." : "Crear proyecto"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </Dialog>
  )
}

function ImportFromTextDialog({
  open,
  onOpenChange,
  clients,
  users,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  clients: { id: number; name: string }[]
  users: User[]
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [step, setStep] = useState<"upload" | "review">("upload")
  const [textFile, setTextFile] = useState<File | null>(null)
  const [clientId, setClientId] = useState("")
  const [ownerId, setOwnerId] = useState("")
  const [formData, setFormData] = useState<Partial<ProjectDraft>>({})

  const extractMutation = useMutation({
    mutationFn: () => {
      if (!textFile) throw new Error("No file selected")
      return projectsApi.extractFromText(textFile)
    },
    onSuccess: (data) => {
      setFormData(data)
      setStep("review")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al analizar el archivo")),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      projectsApi.create(projectCreateFromDraft({ ...formData, owner_id: ownerId ? parseInt(ownerId) : null }, parseInt(clientId))),
    onSuccess: (project) => {
      invalidateProjectChange(queryClient, {clientId: project.client_id})
      toast.success("Proyecto creado")
      navigate(`/projects/${project.id}?created=1`)
      handleClose()
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear proyecto")),
  })

  const handleClose = () => {
    onOpenChange(false)
    setStep("upload")
    setTextFile(null)
    setClientId("")
    setOwnerId("")
    setFormData({})
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) handleClose() }}>
      <DialogHeader>
        <DialogTitle>
          {step === "upload" ? "Importar desde TXT/MD" : "Revisar datos extraídos"}
        </DialogTitle>
      </DialogHeader>

      {step === "upload" ? (
        <div className="space-y-4 mt-4">
          <div className="space-y-2">
            <Label htmlFor="projects-page-field-17">Archivo de contexto (.txt o .md) *</Label>
            <Input id="projects-page-field-17"
              type="file"
              accept=".txt,.md"
              onChange={(e) => setTextFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <OwnerSelect id="text-project-owner" value={ownerId} users={users} onChange={setOwnerId} />
          <div className="space-y-2">
            <Label htmlFor="projects-page-field-18">Cliente *</Label>
            <Select id="projects-page-field-18" value={clientId} onChange={(e) => setClientId(e.target.value)} required>
              <option value="">Seleccionar cliente</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </Select>
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={handleClose}>
              Cancelar
            </Button>
            <Button
              onClick={() => extractMutation.mutate()}
              disabled={!textFile || !clientId || extractMutation.isPending}
            >
              {extractMutation.isPending ? "Analizando..." : "Analizar documento"}
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4 mt-4">
          <div className="space-y-2">
            <Label htmlFor="projects-page-field-19">Nombre del proyecto *</Label>
            <Input id="projects-page-field-19"
              value={formData.name ?? ""}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="projects-page-field-20">Descripción</Label>
            <Input id="projects-page-field-20"
              value={formData.description ?? ""}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="projects-page-field-21">Tipo</Label>
              <Select id="projects-page-field-21"
                value={formData.project_type ?? ""}
                onChange={(e) => setFormData({ ...formData, project_type: e.target.value })}
              >
                <option value="">Sin tipo</option>
                <option value="seo_audit">Auditoría SEO</option>
                <option value="content_strategy">Estrategia de contenido</option>
                <option value="linkbuilding">Link building</option>
                <option value="technical_seo">SEO técnico</option>
                <option value="custom">Personalizado</option>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="projects-page-field-22">Presupuesto total (EUR)</Label>
              <Input id="projects-page-field-22"
                type="number"
                value={formData.budget_amount ?? ""}
                onChange={(e) => setFormData({ ...formData, budget_amount: e.target.value ? parseFloat(e.target.value) : undefined })}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="projects-page-field-23">Tarifa mensual (EUR)</Label>
            <Input id="projects-page-field-23"
              type="number"
              step="0.01"
              value={formData.monthly_fee ?? ""}
              onChange={(e) => setFormData({ ...formData, monthly_fee: e.target.value ? parseFloat(e.target.value) : undefined })}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="projects-page-field-24">Fecha inicio</Label>
              <Input id="projects-page-field-24"
                type="date"
                value={formData.start_date ?? ""}
                onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="projects-page-field-25">Fecha fin objetivo</Label>
              <Input id="projects-page-field-25"
                type="date"
                value={formData.target_end_date ?? ""}
                onChange={(e) => setFormData({ ...formData, target_end_date: e.target.value })}
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input
              id="is_recurring_text"
              type="checkbox"
              checked={formData.is_recurring ?? false}
              onChange={(e) => setFormData({ ...formData, is_recurring: e.target.checked })}
              className="h-4 w-4"
            />
            <Label htmlFor="is_recurring_text">Servicio recurrente</Label>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="projects-page-field-26">Modelo de precio</Label>
              <Select id="projects-page-field-26"
                value={formData.pricing_model ?? ""}
                onChange={(e) => setFormData({ ...formData, pricing_model: e.target.value || undefined })}
              >
                <option value="">Sin definir</option>
                <option value="monthly">Mensual fijo</option>
                <option value="per_piece">Por pieza/unidad</option>
                <option value="hourly">Por hora</option>
                <option value="project">Precio cerrado</option>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="projects-page-field-27">Precio unitario (EUR)</Label>
              <Input id="projects-page-field-27"
                type="number"
                step="0.01"
                value={formData.unit_price ?? ""}
                onChange={(e) => setFormData({ ...formData, unit_price: e.target.value ? parseFloat(e.target.value) : undefined })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="projects-page-field-28">Unidad</Label>
              <Input id="projects-page-field-28"
                value={formData.unit_label ?? ""}
                onChange={(e) => setFormData({ ...formData, unit_label: e.target.value || undefined })}
                placeholder="pieza, hora, mes..."
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="projects-page-field-29">Scope / Alcance</Label>
            <textarea id="projects-page-field-29"
              className="w-full min-h-[80px] text-sm bg-background border border-input rounded-md p-3 resize-y focus:outline-none focus:ring-2 focus:ring-ring"
              value={formData.scope ?? ""}
              onChange={(e) => setFormData({ ...formData, scope: e.target.value || undefined })}
            />
          </div>
          <div className="p-3 bg-muted/50 rounded-lg text-sm text-muted-foreground">
            Cliente: <span className="text-foreground font-medium">{clients.find(c => c.id === parseInt(clientId))?.name}</span>
            {formData.client_name && formData.client_name !== clients.find(c => c.id === parseInt(clientId))?.name && (
              <span> · Detectado en archivo: {formData.client_name}</span>
            )}
          </div>
          <div className="flex justify-between gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setStep("upload")}>
              ← Volver
            </Button>
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={handleClose}>
                Cancelar
              </Button>
              <Button
                onClick={() => createMutation.mutate()}
                disabled={!formData.name || createMutation.isPending}
              >
                {createMutation.isPending ? "Creando..." : "Crear proyecto"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </Dialog>
  )
}

function OwnerSelect({ id, value, users, onChange }: { id: string; value: string; users: User[]; onChange: (value: string) => void }) {
  return <div className="space-y-2">
    <Label htmlFor={id}>Responsable (opcional)</Label>
    <Select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="">Sin responsable</option>
      {users.map((user) => <option key={user.id} value={user.id}>{user.full_name}</option>)}
    </Select>
    <p className="text-xs text-muted-foreground">Se guarda solo la persona elegida aquí.</p>
  </div>
}
