import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { Plus, FolderKanban, Calendar, Trash2, Repeat, FileUp, FileText } from "lucide-react"
import { toast } from "sonner"
import { projectsApi, clientsApi } from "@/lib/api"
import type { ProjectListItem, ProjectStatus, ProjectDraft } from "@/lib/types"
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
  const { page, pageSize, setPage, reset } = usePagination(25)
  const [statusFilter, setStatusFilter] = useState<string>("")
  const [typeFilter, setTypeFilter] = useState<string>("")
  const [periodFilter, setPeriodFilter] = useState<string>("")
  const [showNewDialog, setShowNewDialog] = useState(false)
  const [showTemplateDialog, setShowTemplateDialog] = useState(false)
  const [showImportDialog, setShowImportDialog] = useState(false)
  const [showImportTextDialog, setShowImportTextDialog] = useState(false)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [showNewMenu, setShowNewMenu] = useState(false)

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

  const filterByPeriod = (p: ProjectListItem) => {
    if (!periodFilter) return true
    const now = new Date()
    const endDate = p.target_end_date ? new Date(p.target_end_date) : null
    const startDate = p.start_date ? new Date(p.start_date) : null

    // Project overlaps with the selected period if it started before period end AND ends after period start
    let periodStart: Date
    let periodEnd: Date

    if (periodFilter === "week") {
      const day = now.getDay()
      periodStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() - (day === 0 ? 6 : day - 1))
      periodEnd = new Date(periodStart)
      periodEnd.setDate(periodEnd.getDate() + 6)
    } else if (periodFilter === "month") {
      periodStart = new Date(now.getFullYear(), now.getMonth(), 1)
      periodEnd = new Date(now.getFullYear(), now.getMonth() + 1, 0)
    } else if (periodFilter === "quarter") {
      const q = Math.floor(now.getMonth() / 3)
      periodStart = new Date(now.getFullYear(), q * 3, 1)
      periodEnd = new Date(now.getFullYear(), q * 3 + 3, 0)
    } else {
      return true
    }

    const pStart = startDate ?? new Date(0)
    const pEnd = endDate ?? new Date(9999, 11, 31)
    return pStart <= periodEnd && pEnd >= periodStart
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
        {/* Desktop: 3 buttons */}
        <div className="hidden sm:flex gap-2">
          <Button variant="outline" onClick={() => setShowImportTextDialog(true)}>
            <FileText className="h-4 w-4 mr-2" />
            Importar TXT/MD
          </Button>
          <Button variant="outline" onClick={() => setShowImportDialog(true)}>
            <FileUp className="h-4 w-4 mr-2" />
            Importar PDF
          </Button>
          <Button variant="outline" onClick={() => setShowNewDialog(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Nuevo vacío
          </Button>
          <Button onClick={() => setShowTemplateDialog(true)}>
            <FolderKanban className="h-4 w-4 mr-2" />
            Desde plantilla
          </Button>
        </div>
        {/* Mobile: single dropdown */}
        <div className="sm:hidden relative">
          <Button onClick={() => setShowNewMenu(!showNewMenu)}>
            <Plus className="h-4 w-4 mr-2" /> Nuevo
          </Button>
          {showNewMenu && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowNewMenu(false)} />
              <div className="absolute right-0 top-full z-50 mt-1 w-52 rounded-md border bg-card shadow-md py-1">
                <button className="w-full flex items-center gap-2 px-3 py-2.5 text-sm hover:bg-muted" onClick={() => { setShowNewMenu(false); setShowNewDialog(true) }}>
                  <Plus className="h-4 w-4" /> Nuevo vacío
                </button>
                <button className="w-full flex items-center gap-2 px-3 py-2.5 text-sm hover:bg-muted" onClick={() => { setShowNewMenu(false); setShowTemplateDialog(true) }}>
                  <FolderKanban className="h-4 w-4" /> Desde plantilla
                </button>
                <button className="w-full flex items-center gap-2 px-3 py-2.5 text-sm hover:bg-muted" onClick={() => { setShowNewMenu(false); setShowImportDialog(true) }}>
                  <FileUp className="h-4 w-4" /> Importar PDF
                </button>
                <button className="w-full flex items-center gap-2 px-3 py-2.5 text-sm hover:bg-muted" onClick={() => { setShowNewMenu(false); setShowImportTextDialog(true) }}>
                  <FileText className="h-4 w-4" /> Importar TXT/MD
                </button>
              </div>
            </>
          )}
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
        <Select
          value={periodFilter}
          onChange={(e) => setPeriodFilter(e.target.value)}
          className="w-48"
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
      ) : (projects.filter(p => {
          if (typeFilter && (typeFilter === "recurring" ? !p.is_recurring : p.is_recurring)) return false
          if (!filterByPeriod(p)) return false
          return true
        })).length === 0 ? (
        <EmptyState
          icon={FolderKanban}
          title="Sin proyectos todavia"
          description={statusFilter ? "No hay proyectos con este estado. Prueba a cambiar el filtro o crea uno nuevo." : "Organiza el trabajo en proyectos con fases y tareas. Puedes empezar desde una plantilla o importar una propuesta."}
          actionLabel="Crear desde plantilla"
          onAction={() => setShowTemplateDialog(true)}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {projects.filter(p => {
            if (typeFilter && (typeFilter === "recurring" ? !p.is_recurring : p.is_recurring)) return false
            if (!filterByPeriod(p)) return false
            return true
          }).map((project) => (
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

      {/* Import from PDF Dialog */}
      <ImportFromPdfDialog
        open={showImportDialog}
        onOpenChange={setShowImportDialog}
        clients={clients}
      />

      {/* Import from TXT/MD Dialog */}
      <ImportFromTextDialog
        open={showImportTextDialog}
        onOpenChange={setShowImportTextDialog}
        clients={clients}
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
        monthly_fee: formData.monthly_fee ? parseFloat(formData.monthly_fee) : undefined,
        unit_price: formData.unit_price ? parseFloat(formData.unit_price) : undefined,
        unit_label: formData.unit_label || undefined,
        scope: formData.scope || undefined,
        budget_amount: formData.budget_amount ? parseFloat(formData.budget_amount) : undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] })
      toast.success("Proyecto creado")
      onOpenChange(false)
      setFormData(emptyForm)
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
        <div className="flex items-center gap-2">
          <input
            id="is_recurring_new"
            type="checkbox"
            checked={formData.is_recurring}
            onChange={(e) => setFormData({ ...formData, is_recurring: e.target.checked })}
            className="h-4 w-4"
          />
          <Label htmlFor="is_recurring_new">Servicio recurrente</Label>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>Modelo de precio</Label>
            <Select
              value={formData.pricing_model}
              onChange={(e) => setFormData({ ...formData, pricing_model: e.target.value })}
            >
              <option value="">Sin definir</option>
              <option value="monthly">Mensual fijo</option>
              <option value="per_piece">Por pieza/unidad</option>
              <option value="hourly">Por hora</option>
              <option value="project">Precio cerrado</option>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Fee mensual (EUR)</Label>
            <Input
              type="number"
              step="0.01"
              value={formData.monthly_fee}
              onChange={(e) => setFormData({ ...formData, monthly_fee: e.target.value })}
              placeholder="Retainer mensual"
            />
          </div>
        </div>
        <div className="grid grid-cols-3 gap-4">
          <div className="space-y-2">
            <Label>Precio unitario (EUR)</Label>
            <Input
              type="number"
              step="0.01"
              value={formData.unit_price}
              onChange={(e) => setFormData({ ...formData, unit_price: e.target.value })}
              placeholder="200"
            />
          </div>
          <div className="space-y-2">
            <Label>Unidad</Label>
            <Input
              value={formData.unit_label}
              onChange={(e) => setFormData({ ...formData, unit_label: e.target.value })}
              placeholder="pieza, hora, mes..."
            />
          </div>
          <div className="space-y-2">
            <Label>Presupuesto total (EUR)</Label>
            <Input
              type="number"
              step="0.01"
              value={formData.budget_amount}
              onChange={(e) => setFormData({ ...formData, budget_amount: e.target.value })}
              placeholder="Opcional"
            />
          </div>
        </div>
        <div className="space-y-2">
          <Label>Scope / Alcance</Label>
          <textarea
            className="w-full min-h-[80px] text-sm bg-background border border-input rounded-md p-3 resize-y focus:outline-none focus:ring-2 focus:ring-ring"
            value={formData.scope}
            onChange={(e) => setFormData({ ...formData, scope: e.target.value })}
            placeholder="Descripcion del alcance aprobado..."
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

function TemplateDialog({
  open,
  onOpenChange,
  clients,
  templates,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  clients: { id: number; name: string }[]
  templates: Record<string, { name: string; description?: string | null; phase_count: number; task_count: number; pricing_model?: string | null; monthly_fee?: number | null; is_recurring?: boolean }>
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
            {(selectedTemplate.pricing_model || selectedTemplate.monthly_fee) && (
              <div className="flex gap-3 text-muted-foreground">
                {selectedTemplate.pricing_model && (
                  <span>Modelo: <span className="text-foreground font-medium">{selectedTemplate.pricing_model}</span></span>
                )}
                {selectedTemplate.monthly_fee && (
                  <span>Fee: <span className="text-foreground font-medium">{formatCurrency(selectedTemplate.monthly_fee)}</span></span>
                )}
              </div>
            )}
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

function ImportFromPdfDialog({
  open,
  onOpenChange,
  clients,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  clients: { id: number; name: string }[]
}) {
  const queryClient = useQueryClient()
  const [step, setStep] = useState<"upload" | "review">("upload")
  const [pdfFile, setPdfFile] = useState<File | null>(null)
  const [clientId, setClientId] = useState("")
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
      projectsApi.create({
        name: formData.name ?? "",
        client_id: parseInt(clientId),
        description: formData.description ?? undefined,
        project_type: formData.project_type ?? undefined,
        is_recurring: formData.is_recurring ?? false,
        budget_amount: formData.budget_amount ?? undefined,
        start_date: formData.start_date ?? undefined,
        target_end_date: formData.target_end_date ?? undefined,
        pricing_model: formData.pricing_model ?? undefined,
        unit_price: formData.unit_price ?? undefined,
        unit_label: formData.unit_label ?? undefined,
        scope: formData.scope ?? undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] })
      toast.success("Proyecto creado")
      handleClose()
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear proyecto")),
  })

  const handleClose = () => {
    onOpenChange(false)
    setStep("upload")
    setPdfFile(null)
    setClientId("")
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
            <Label>Propuesta PDF *</Label>
            <Input
              type="file"
              accept=".pdf"
              onChange={(e) => setPdfFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <div className="space-y-2">
            <Label>Cliente *</Label>
            <Select value={clientId} onChange={(e) => setClientId(e.target.value)} required>
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
            <Label>Nombre del proyecto *</Label>
            <Input
              value={formData.name ?? ""}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              required
            />
          </div>
          <div className="space-y-2">
            <Label>Descripción</Label>
            <Input
              value={formData.description ?? ""}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Tipo</Label>
              <Select
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
              <Label>Presupuesto (€)</Label>
              <Input
                type="number"
                value={formData.budget_amount ?? ""}
                onChange={(e) => setFormData({ ...formData, budget_amount: e.target.value ? parseFloat(e.target.value) : undefined })}
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Fecha inicio</Label>
              <Input
                type="date"
                value={formData.start_date ?? ""}
                onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Fecha fin objetivo</Label>
              <Input
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
              <Label>Modelo de precio</Label>
              <Select
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
              <Label>Precio unitario (EUR)</Label>
              <Input
                type="number"
                step="0.01"
                value={formData.unit_price ?? ""}
                onChange={(e) => setFormData({ ...formData, unit_price: e.target.value ? parseFloat(e.target.value) : undefined })}
              />
            </div>
            <div className="space-y-2">
              <Label>Unidad</Label>
              <Input
                value={formData.unit_label ?? ""}
                onChange={(e) => setFormData({ ...formData, unit_label: e.target.value || undefined })}
                placeholder="pieza, hora, mes..."
              />
            </div>
          </div>
          {formData.scope && (
            <div className="space-y-2">
              <Label>Scope / Alcance</Label>
              <textarea
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
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  clients: { id: number; name: string }[]
}) {
  const queryClient = useQueryClient()
  const [step, setStep] = useState<"upload" | "review">("upload")
  const [textFile, setTextFile] = useState<File | null>(null)
  const [clientId, setClientId] = useState("")
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
      projectsApi.create({
        name: formData.name ?? "",
        client_id: parseInt(clientId),
        description: formData.description ?? undefined,
        project_type: formData.project_type ?? undefined,
        is_recurring: formData.is_recurring ?? false,
        budget_amount: formData.budget_amount ?? undefined,
        start_date: formData.start_date ?? undefined,
        target_end_date: formData.target_end_date ?? undefined,
        pricing_model: formData.pricing_model ?? undefined,
        unit_price: formData.unit_price ?? undefined,
        unit_label: formData.unit_label ?? undefined,
        scope: formData.scope ?? undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] })
      toast.success("Proyecto creado")
      handleClose()
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear proyecto")),
  })

  const handleClose = () => {
    onOpenChange(false)
    setStep("upload")
    setTextFile(null)
    setClientId("")
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
            <Label>Archivo de contexto (.txt o .md) *</Label>
            <Input
              type="file"
              accept=".txt,.md"
              onChange={(e) => setTextFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <div className="space-y-2">
            <Label>Cliente *</Label>
            <Select value={clientId} onChange={(e) => setClientId(e.target.value)} required>
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
            <Label>Nombre del proyecto *</Label>
            <Input
              value={formData.name ?? ""}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              required
            />
          </div>
          <div className="space-y-2">
            <Label>Descripción</Label>
            <Input
              value={formData.description ?? ""}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Tipo</Label>
              <Select
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
              <Label>Presupuesto (EUR)</Label>
              <Input
                type="number"
                value={formData.budget_amount ?? ""}
                onChange={(e) => setFormData({ ...formData, budget_amount: e.target.value ? parseFloat(e.target.value) : undefined })}
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Fecha inicio</Label>
              <Input
                type="date"
                value={formData.start_date ?? ""}
                onChange={(e) => setFormData({ ...formData, start_date: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Fecha fin objetivo</Label>
              <Input
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
              <Label>Modelo de precio</Label>
              <Select
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
              <Label>Precio unitario (EUR)</Label>
              <Input
                type="number"
                step="0.01"
                value={formData.unit_price ?? ""}
                onChange={(e) => setFormData({ ...formData, unit_price: e.target.value ? parseFloat(e.target.value) : undefined })}
              />
            </div>
            <div className="space-y-2">
              <Label>Unidad</Label>
              <Input
                value={formData.unit_label ?? ""}
                onChange={(e) => setFormData({ ...formData, unit_label: e.target.value || undefined })}
                placeholder="pieza, hora, mes..."
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label>Scope / Alcance</Label>
            <textarea
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
