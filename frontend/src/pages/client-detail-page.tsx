import { formatCivilDate, timeEntryBusinessDate } from "@/lib/dates"
import { useState } from "react"
import { useParams, Link, useSearchParams } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { clientsApi, projectsApi, holdedApi, clientHealthApi, engineApi } from "@/lib/api"
import type { TaskStatus, Client } from "@/lib/types"
import { isEnabled } from "@/lib/hidden-modules"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Pencil, Check, X, ExternalLink } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Clock, Heart } from "lucide-react"
import { Breadcrumb } from "@/components/ui/breadcrumb"
import { Skeleton, SkeletonCard } from "@/components/ui/skeleton"
import { TimerButton } from "@/components/timer/timer-button"
import { TimeLogDialog } from "@/components/timer/time-log-dialog"
import { CommunicationList } from "@/components/communications/communication-list"
import { ContactList } from "@/components/clients/contact-list"
import { ActivityTimeline } from "@/components/clients/activity-timeline"
import { ResourceList } from "@/components/clients/resource-list"
import { BillingTab } from "@/components/clients/billing-tab"
import { ClientDashboardTab } from "@/components/clients/client-dashboard-tab"
import { ClientAiAdvisor } from "@/components/clients/client-ai-advisor"
import { ClientReportsTab } from "@/components/clients/client-reports-tab"
import { ClientReportPolicy } from "@/components/clients/client-report-policy"
import { ClientSettingsTab } from "@/components/clients/client-settings-tab"
import { EngineMetricsWidget } from "@/components/clients/engine-metrics-widget"
import { EngineSeoTab } from "@/components/clients/engine-seo-tab"
// CoreUpdatesTab removed — analysis only available in Engine
import { FichaTab } from "@/components/clients/ficha-tab"
import { useAuth } from "@/context/auth-context"
import { clientKeys, holdedKeys, invalidateClientChange, projectKeys, timeKeys } from "@/lib/query-keys"
import { formatCurrency } from "@/lib/format"
import { TaskPanel } from "@/components/tasks/task-panel"
import { clientHealthPresentation } from "@/components/dashboard/client-health-presentation"

function formatMinutes(m: number): string {
  const h = Math.floor(m / 60)
  const mins = m % 60
  if (h && mins) return `${h}h ${mins}m`
  if (h) return `${h}h`
  return `${mins}m`
}

const statusBadge = (status: string) => {
  const map: Record<string, { label: string; variant: "success" | "warning" | "secondary" }> = {
    active: { label: "Activo", variant: "success" },
    paused: { label: "Pausado", variant: "warning" },
    finished: { label: "Finalizado", variant: "secondary" },
  }
  const { label, variant } = map[status] || { label: status, variant: "secondary" }
  return <Badge variant={variant}>{label}</Badge>
}

const taskStatusBadge = (status: TaskStatus) => {
  const map: Record<TaskStatus, { label: string; variant: "secondary" | "warning" | "success" | "outline" }> = {
    backlog: { label: "Backlog", variant: "outline" },
    pending: { label: "Pendiente", variant: "secondary" },
    in_progress: { label: "En curso", variant: "warning" },
    waiting: { label: "En espera", variant: "secondary" },
    in_review: { label: "En revisión", variant: "warning" },
    advanced: { label: "Avanzada", variant: "warning" },
    completed: { label: "Completada", variant: "success" },
  }
  const { label, variant } = map[status]
  return <Badge variant={variant}>{label}</Badge>
}

function RevenueIntelligenceCard({ client }: { client: Client }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState({
    business_model: client.business_model || "",
    aov: client.aov ?? "",
    conversion_rate: client.conversion_rate ?? "",
    ltv: client.ltv ?? "",
    seo_maturity_level: client.seo_maturity_level || "",
  })

  const updateMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => clientsApi.update(client.id, data),
    onSuccess: () => {
      void invalidateClientChange(queryClient, [client.id])
      setEditing(false)
    },
    onError: () => toast.error("Error al guardar los datos del cliente"),
  })

  const handleSave = () => {
    updateMutation.mutate({
      business_model: form.business_model || null,
      aov: form.aov !== "" ? Number(form.aov) : null,
      conversion_rate: form.conversion_rate !== "" ? Number(form.conversion_rate) : null,
      ltv: form.ltv !== "" ? Number(form.ltv) : null,
      seo_maturity_level: form.seo_maturity_level || null,
    })
  }

  const businessModelLabels: Record<string, string> = {
    ecommerce: "E-commerce",
    saas: "SaaS",
    lead_gen: "Lead Generation",
    media: "Media / Publisher",
  }
  const maturityLabels: Record<string, string> = {
    none: "Sin SEO",
    basic: "Básico",
    intermediate: "Intermedio",
    advanced: "Avanzado",
  }

  const hasData = client.business_model || client.aov || client.conversion_rate || client.ltv || client.seo_maturity_level

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">Inteligencia de Negocio</CardTitle>
        {!editing ? (
          <Button variant="ghost" size="sm" aria-label="Editar inteligencia de negocio" onClick={() => {
            setForm({
              business_model: client.business_model || "",
              aov: client.aov ?? "",
              conversion_rate: client.conversion_rate ?? "",
              ltv: client.ltv ?? "",
              seo_maturity_level: client.seo_maturity_level || "",
            })
            setEditing(true)
          }}>
            <Pencil className="w-4 h-4" />
          </Button>
        ) : (
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" aria-label="Guardar inteligencia de negocio" onClick={handleSave} disabled={updateMutation.isPending}>
              <Check className="w-4 h-4" />
            </Button>
            <Button variant="ghost" size="sm" aria-label="Cancelar edición de inteligencia de negocio" onClick={() => setEditing(false)}>
              <X className="w-4 h-4" />
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent>
        {editing ? (
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="business-model" className="text-xs text-muted-foreground">Modelo de negocio</label>
              <Select id="business-model" value={form.business_model} onChange={e => setForm(f => ({ ...f, business_model: e.target.value }))}>
                <option value="">Seleccionar...</option>
                <option value="ecommerce">E-commerce</option>
                <option value="saas">SaaS</option>
                <option value="lead_gen">Lead Generation</option>
                <option value="media">Media / Publisher</option>
              </Select>
            </div>
            <div>
              <label htmlFor="business-aov" className="text-xs text-muted-foreground">AOV (€)</label>
              <Input id="business-aov" type="number" value={form.aov} onChange={e => setForm(f => ({ ...f, aov: e.target.value }))} placeholder="0" />
            </div>
            <div>
              <label htmlFor="business-conversion" className="text-xs text-muted-foreground">Conversión (%)</label>
              <Input id="business-conversion" type="number" step="0.1" value={form.conversion_rate} onChange={e => setForm(f => ({ ...f, conversion_rate: e.target.value }))} placeholder="0" />
            </div>
            <div>
              <label htmlFor="business-ltv" className="text-xs text-muted-foreground">LTV (€)</label>
              <Input id="business-ltv" type="number" value={form.ltv} onChange={e => setForm(f => ({ ...f, ltv: e.target.value }))} placeholder="0" />
            </div>
            <div className="col-span-2">
              <label htmlFor="business-seo-maturity" className="text-xs text-muted-foreground">Madurez SEO</label>
              <Select id="business-seo-maturity" value={form.seo_maturity_level} onChange={e => setForm(f => ({ ...f, seo_maturity_level: e.target.value }))}>
                <option value="">Seleccionar...</option>
                <option value="none">Sin SEO</option>
                <option value="basic">Básico</option>
                <option value="intermediate">Intermedio</option>
                <option value="advanced">Avanzado</option>
              </Select>
            </div>
          </div>
        ) : hasData ? (
          <div className="grid grid-cols-2 gap-4 text-sm">
            {client.business_model && (
              <div>
                <p className="text-xs text-muted-foreground">Modelo</p>
                <p className="font-medium">{businessModelLabels[client.business_model] || client.business_model}</p>
              </div>
            )}
            {client.aov != null && (
              <div>
                <p className="text-xs text-muted-foreground">AOV</p>
                <p className="font-medium">{formatCurrency(client.aov)}</p>
              </div>
            )}
            {client.conversion_rate != null && (
              <div>
                <p className="text-xs text-muted-foreground">Conversión</p>
                <p className="font-medium">{client.conversion_rate}%</p>
              </div>
            )}
            {client.ltv != null && (
              <div>
                <p className="text-xs text-muted-foreground">LTV</p>
                <p className="font-medium">{formatCurrency(client.ltv)}</p>
              </div>
            )}
            {client.seo_maturity_level && (
              <div>
                <p className="text-xs text-muted-foreground">Madurez SEO</p>
                <p className="font-medium">{maturityLabels[client.seo_maturity_level] || client.seo_maturity_level}</p>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Sin datos de negocio. Haz clic en el lápiz para añadir.</p>
        )}
      </CardContent>
    </Card>
  )
}

export default function ClientDetailPage() {
  const { isAdmin, hasPermission } = useAuth()
  const { id } = useParams<{ id: string }>()
  const clientId = Number(id)
  const [searchParams, setSearchParams] = useSearchParams()
  const [timeLogTaskId, setTimeLogTaskId] = useState<{ id: number; title: string; retired?: boolean } | null>(null)
  const [taskPanelId, setTaskPanelId] = useState<number | null>(null)
  const [creatingTask, setCreatingTask] = useState(false)
  const [whatIfOpen, setWhatIfOpen] = useState(false)

  const validTabs = ["ficha", "actividad", "tareas", "proyectos", "resumenes", "comunicaciones", "contactos", "panel", "tiempo", "facturacion", "recursos", "seo", "informes", "ajustes", "facturas"] as const
  type Tab = (typeof validTabs)[number]

  // Pestaña -> módulo que la sirve. Si el módulo está oculto, sus endpoints no
  // están registrados, así que la pestaña no puede renderizarse ni aunque
  // llegue en la URL (un enlace guardado con ?tab=comunicaciones, por ejemplo).
  const TAB_MODULE: Partial<Record<Tab, string>> = {
    resumenes: "digests",
    comunicaciones: "communications",
    facturacion: "billing",
    facturas: "holded",
    informes: "reports",
    recursos: "resources",
  }
  const TAB_PERMISSION: Partial<Record<Tab, string>> = {
    tareas: "tasks",
    proyectos: "projects",
    resumenes: "digests",
    comunicaciones: "communications",
    facturacion: "billing",
    facturas: "billing",
    informes: "reports",
  }
  const isTabVisible = (tab: Tab) => {
    const mod = TAB_MODULE[tab]
    const permission = TAB_PERMISSION[tab]
    return (!mod || isEnabled(mod)) && (!permission || hasPermission(permission))
  }

  const tabParam = searchParams.get("tab") as Tab
  const activeTab =
    validTabs.includes(tabParam) && isTabVisible(tabParam) ? tabParam : "ficha"
  const setActiveTab = (tab: Tab) => setSearchParams({ tab }, { replace: true })

  const summaryQuery = useQuery({
    queryKey: clientKeys.summary(clientId),
    queryFn: () => clientsApi.summary(clientId),
    enabled: !!clientId,
  })
  const { data: summary, isLoading } = summaryQuery

  const projectsQuery = useQuery({
    queryKey: projectKeys.client(clientId),
    queryFn: () => projectsApi.listAll({ client_id: clientId }),
    enabled: !!clientId && activeTab === "proyectos" && hasPermission("projects"),
  })
  const projects = projectsQuery.data ?? []

  const { data: holdedConfig } = useQuery({
    queryKey: holdedKeys.config(),
    queryFn: holdedApi.config,
    staleTime: 5 * 60_000,
    retry: false,
    // Con holded oculto su router no existe: sin este corte la ficha de cada
    // cliente dispararía un 404 en cada carga.
    enabled: isAdmin && isEnabled("holded"),
  })
  const holdedEnabled = isAdmin && isEnabled("holded") && (holdedConfig?.api_key_configured ?? false)

  const { data: clientInvoices = [] } = useQuery({
    queryKey: holdedKeys.clientInvoices(clientId),
    queryFn: () => holdedApi.clientInvoices(clientId),
    enabled: !!clientId && holdedEnabled,
  })

  const { data: engineConfig } = useQuery({
    queryKey: ["engine-config"],
    queryFn: () => engineApi.getConfig(),
    staleTime: 10 * 60_000,
  })

  const canReadClientHealth = hasPermission("clients")
  const healthQuery = useQuery({
    queryKey: ["client-health", clientId],
    queryFn: () => clientHealthApi.get(clientId),
    enabled: !!clientId && canReadClientHealth,
    staleTime: 60_000,
  })
  const health = canReadClientHealth && !healthQuery.isError ? healthQuery.data : undefined

  const recentEntriesQuery = useQuery({
    queryKey: timeKeys.client(clientId),
    queryFn: () => clientsApi.recentTimeEntries(clientId),
    enabled: !!clientId && activeTab === "tiempo",
  })
  const recentEntries = recentEntriesQuery.data ?? []

  const { data: whatIfData, isLoading: whatIfLoading } = useQuery({
    queryKey: ["client-what-if", clientId],
    queryFn: () => clientsApi.whatIf(clientId),
    enabled: whatIfOpen && !!clientId,
  })

  if (isLoading) return (
    <div className="space-y-6">
      <Skeleton className="h-5 w-48" />
      <div className="flex items-center gap-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-6 w-20" />
      </div>
      <div className="grid grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
      </div>
    </div>
  )
  if (summaryQuery.isError) return (
    <div role="alert" className="space-y-3">
      <p>No se pudo cargar la ficha del cliente.</p>
      <Button variant="outline" onClick={() => summaryQuery.refetch()}>Reintentar</Button>
    </div>
  )
  if (!summary) return <p className="text-muted-foreground">Cliente no encontrado</p>

  const { client, tasks } = summary
  const activeTasks = tasks.filter((task) => task.status !== "completed")
  const completedTasks = tasks.filter((task) => task.status === "completed")

  const taskRows = (rows: typeof tasks) => rows.map((t) => (
    <TableRow key={t.id} role="row" className="grid grid-cols-2 items-center gap-x-2 py-3 md:table-row md:py-0">
      <TableCell role="cell" className="col-span-2 block px-0 py-1 md:table-cell md:px-4 md:py-3"><button type="button" className="font-medium text-left rounded hover:text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand" onClick={() => setTaskPanelId(t.id)}>{t.title}</button></TableCell>
      <TableCell role="cell" className="block px-0 py-1 md:table-cell md:px-4 md:py-3">{taskStatusBadge(t.status)}</TableCell>
      <TableCell role="cell" className="mono row-start-3 block px-0 py-1 text-xs md:table-cell md:px-4 md:py-3 md:text-sm"><span className="md:hidden">Estimado: </span>{t.estimated_minutes ? formatMinutes(t.estimated_minutes) : "-"}</TableCell>
      <TableCell role="cell" className="mono row-start-3 block px-0 py-1 text-xs md:table-cell md:px-4 md:py-3 md:text-sm"><span className="md:hidden">Registrado: </span>{t.actual_minutes ? formatMinutes(t.actual_minutes) : "-"}</TableCell>
      <TableCell role="cell" className="col-start-2 row-start-2 block px-0 py-1 md:table-cell md:px-4 md:py-3">
        <div className="flex justify-end gap-1 md:justify-start">
          <TimerButton taskId={t.id} />
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Ver horas de ${t.title}`}
            onClick={() => setTimeLogTaskId({ id: t.id, title: t.title, retired: !!t.retired_at })}
          >
            <Clock className="h-4 w-4" />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  ))

  const taskTable = (rows: typeof tasks, label: string) => (
    <Table role="table" aria-label={label} className="block md:table">
      <TableHeader className="sr-only md:not-sr-only md:table-header-group">
        <TableRow>
          <TableHead>Título</TableHead>
          <TableHead>Estado</TableHead>
          <TableHead>Est.</TableHead>
          <TableHead>Real</TableHead>
          <TableHead>Timer</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody role="rowgroup" className="block md:table-row-group">
        {taskRows(rows)}
      </TableBody>
    </Table>
  )

  return (
    <div className="space-y-6">
      {/* Breadcrumb + Header */}
      <Breadcrumb items={[
        { label: "Inicio", href: "/dashboard" },
        { label: "Clientes", href: "/clients" },
        { label: client.name },
      ]} />
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold uppercase tracking-wide">{client.name}</h2>
            {statusBadge(client.status)}
            {client.is_internal && <Badge variant="outline" className="border-purple-500/50 text-purple-400">Interno</Badge>}
            {client.engine_project_id && engineConfig?.engine_frontend_url && (
              <a
                href={`${engineConfig.engine_frontend_url}/p/${client.engine_project_id}/dashboard`}
                target="_blank"
                rel="noopener noreferrer"
                title="Abrir en Engine"
              >
                <Button variant="ghost" size="icon" aria-label="Abrir en Engine" className="h-7 w-7">
                  <ExternalLink className="h-4 w-4" />
                </Button>
              </a>
            )}
          </div>
          {client.company && <p className="text-muted-foreground">{client.company}</p>}
        </div>
        {(activeTab === "ficha" || activeTab === "panel") && <Button variant="outline" size="sm" onClick={() => setWhatIfOpen(true)}>
          ¿Y si pierdo este cliente?
        </Button>}
      </div>

      {/* Cuatro áreas estables; las URLs ?tab= heredadas siguen seleccionando
          su vista concreta dentro del área correspondiente. */}
      {(() => {
        type TabKey = Tab
        type AreaDef = { key: string; label: string; tabs: TabKey[] }
        const areas = ([
          {
            key: "resumen",
            label: "Resumen",
            tabs: ["ficha", "actividad", "panel"],
          },
          {
            key: "trabajo",
            label: "Trabajo",
            tabs: [
              ...(isTabVisible("tareas") ? (["tareas"] as TabKey[]) : []),
              ...(isTabVisible("proyectos") ? (["proyectos"] as TabKey[]) : []),
              "tiempo",
            ],
          },
          {
            key: "outputs",
            label: "Resúmenes y archivos",
            tabs: [
              ...(isTabVisible("resumenes") ? (["resumenes"] as TabKey[]) : []),
              ...(isTabVisible("informes") ? (["informes"] as TabKey[]) : []),
              ...(isTabVisible("comunicaciones")
                ? (["comunicaciones"] as TabKey[])
                : []),
              ...(isTabVisible("recursos") ? (["recursos"] as TabKey[]) : []),
              ...(client.engine_project_id ? (["seo"] as TabKey[]) : []),
            ],
          },
          {
            key: "ajustes",
            label: "Ajustes",
            tabs: [
              "contactos",
              ...(isTabVisible("facturacion") ? (["facturacion"] as TabKey[]) : []),
              ...(holdedEnabled && isTabVisible("facturas")
                ? (["facturas"] as TabKey[])
                : []),
              "ajustes",
            ],
          },
        ] satisfies AreaDef[]).filter((area) => area.tabs.length > 0)
        const activeArea =
          areas.find((area) => area.tabs.includes(activeTab)) ?? areas[0]
        const tabLabels: Record<TabKey, string> = {
          ficha: "Ficha",
          actividad: "Actividad",
          panel: "Panel",
          tareas: "Tareas",
          proyectos: "Proyectos",
          tiempo: "Tiempo",
          resumenes: "Resúmenes",
          informes: "Informes",
          comunicaciones: "Comunicaciones",
          recursos: "Archivos",
          seo: "SEO",
          contactos: "Contactos",
          facturacion: "Comercial",
          facturas: "Facturas",
          ajustes: "Configuración",
        }
        return (
          <nav className="space-y-2" aria-label="Áreas del cliente">
            <Select
              className="md:hidden"
              aria-label="Área del cliente"
              value={activeArea.key}
              onChange={(event) => {
                const area = areas.find(
                  (item) => item.key === event.target.value,
                )
                if (area?.tabs[0]) setActiveTab(area.tabs[0])
              }}
            >
              {areas.map((area) => (
                <option key={area.key} value={area.key}>
                  {area.label}
                </option>
              ))}
            </Select>
            <div className="hidden md:flex items-center gap-1 bg-muted/30 p-1 w-fit rounded-lg border border-border">
              {areas.map((area) => (
                <Button
                  key={area.key}
                  variant={activeArea.key === area.key ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setActiveTab(area.tabs[0])}
                >
                  {area.label}
                </Button>
              ))}
            </div>
            {activeArea.tabs.length > 1 && (
              <Select
                className="md:hidden"
                aria-label="Sección del área"
                value={activeTab}
                onChange={(event) => setActiveTab(event.target.value as Tab)}
              >
                {activeArea.tabs.map((tab) => (
                  <option key={tab} value={tab}>
                    {tabLabels[tab]}
                  </option>
                ))}
              </Select>
            )}
            {activeArea.tabs.length > 1 && (
              <div className="hidden md:flex items-center gap-1 pl-2 flex-wrap">
                {activeArea.tabs.map((tab) => (
                  <Button
                    key={tab}
                    variant={activeTab === tab ? "secondary" : "ghost"}
                    size="sm"
                    className="text-xs h-7"
                    onClick={() => setActiveTab(tab)}
                  >
                    {tabLabels[tab]}
                  </Button>
                ))}
              </div>
            )}
          </nav>
        )
      })()}

      {/* Summary Cards — Tracked es la métrica canónica.
          Estimado/Real quedan como subtexto secundario (datos declarados vs fichados). */}
      {(activeTab === "ficha" || activeTab === "panel") && <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Total tareas</p>
            <p className="kpi-value mt-1">{summary.total_tasks}</p>
          </CardContent>
        </Card>
        <Card
          className="lg:col-span-2"
          title="Tiempo tracked: suma del timer real del equipo. Estimado: lo previsto al crear la tarea. Declarado: lo que el responsable apuntó al cerrarla."
        >
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              Tiempo tracked
              <span className="text-muted-foreground/60 cursor-help">ⓘ</span>
            </p>
            <p className="kpi-value mt-1">{formatMinutes(summary.total_tracked_minutes)}</p>
            <div className="mt-2 flex items-center gap-3 text-[11px] text-muted-foreground">
              <span>
                Estimado: <span className="mono">{formatMinutes(summary.total_estimated_minutes)}</span>
              </span>
              <span className="text-muted-foreground/40">·</span>
              <span>
                Declarado: <span className="mono">{formatMinutes(summary.total_actual_minutes)}</span>
              </span>
            </div>
          </CardContent>
        </Card>
        {canReadClientHealth && healthQuery.isError && (
          <Card>
            <CardContent className="flex h-full flex-col items-start justify-center gap-2 p-4" role="alert">
              <p className="text-sm">No se pudo cargar la salud del cliente.</p>
              <Button variant="outline" size="sm" disabled={healthQuery.isFetching} onClick={() => void healthQuery.refetch()}>Reintentar salud</Button>
            </CardContent>
          </Card>
        )}
        {health && (() => {
          const presentation = clientHealthPresentation(health)
          const measuredFactors = (Object.keys(health.factors) as Array<keyof typeof health.factors>).filter((factor) => health.factors[factor] != null)
          const unavailableFactors = (Object.keys(health.factors) as Array<keyof typeof health.factors>).filter((factor) => health.factors[factor] == null)
          return <Card className={health.risk_signals.length ? "border-red-500/40" : ""}>
            <CardContent className="p-4">
              <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                <Heart className="h-3 w-3 flex-shrink-0" /> <span className="truncate">Salud</span>
              </p>
              <Badge variant={presentation.variant} className="mt-2">{presentation.label}</Badge>
              <p className="mt-1 text-xs text-muted-foreground">
                {presentation.detail}. {health.available_source_count} fuentes disponibles.
              </p>
              <div className="mt-3 space-y-1 text-xs text-muted-foreground">
                {health.risk_signals.map((signal) => <p key={signal} className="font-medium text-red-600">{signal}</p>)}
                {measuredFactors.map((factor) => (
                    <p key={factor}>
                      {health.observations[factor]}
                      {factor === "tasks" && <> · <Link className="text-brand hover:underline" to={`/clients/${clientId}?tab=tareas`}>Ver tareas</Link></>}
                      {factor === "profitability" && <> · <Link className="text-brand hover:underline" to={`/clients/${clientId}?tab=panel`}>Ver consumo</Link></>}
                    </p>
                  ))}
                {unavailableFactors.length > 0 && <div className="mt-2 border-t pt-2"><p className="font-medium">Información incompleta</p>{unavailableFactors.map((factor) => <p key={factor}>{health.observations[factor]}</p>)}</div>}
                {health.score != null && <details className="mt-2"><summary className="cursor-pointer">Ver índice orientativo legado</summary><p className="mt-1">{health.score} puntos; no sustituye las condiciones anteriores.</p></details>}
              </div>
            </CardContent>
          </Card>
        })()}
      </div>}

      {/* Tab: Ficha */}
      {activeTab === "ficha" && (
        <FichaTab client={client} onNavigateToContacts={() => setActiveTab("contactos")} />
      )}

      {/* Tab: Actividad (Timeline + AI Advisor) */}
      {activeTab === "actividad" && (
        <div className="space-y-6">
          <Card>
            <CardContent className="p-6">
              <ClientAiAdvisor clientId={clientId} />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-6">
              <ActivityTimeline clientId={clientId} />
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tab: Tareas */}
      {activeTab === "tareas" && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between"><CardTitle>Tareas</CardTitle>{hasPermission("tasks", true) && <Button size="sm" onClick={() => setCreatingTask(true)}>Nueva tarea</Button>}</div>
          </CardHeader>
          <CardContent className="space-y-3 pt-4">
            {activeTasks.length > 0 ? taskTable(activeTasks, "Trabajo activo") : (
              <p className="py-4 text-center text-sm text-muted-foreground">
                {tasks.length === 0 ? "No hay tareas" : "No hay trabajo activo"}
              </p>
            )}
            {completedTasks.length > 0 && (
              <details className="border-t border-border pt-2">
                <summary className="min-h-10 cursor-pointer rounded py-2 text-sm text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
                  Completadas ({completedTasks.length})
                </summary>
                <div className="mt-1">
                  {taskTable(completedTasks, "Tareas completadas")}
                </div>
              </details>
            )}
          </CardContent>
        </Card>
      )}

      {/* Tab: Proyectos */}
      {activeTab === "proyectos" && (
        <Card>
          <CardHeader>
            <CardTitle>Proyectos</CardTitle>
          </CardHeader>
          <CardContent className="pt-4">
            {projectsQuery.isPending ? (
              <p role="status" className="py-8 text-center text-sm text-muted-foreground">Cargando proyectos…</p>
            ) : projectsQuery.isError ? (
              <div role="alert" className="flex items-center justify-between gap-3 py-4 text-sm">
                <span>No se pudieron cargar los proyectos.</span>
                <Button size="sm" variant="outline" onClick={() => projectsQuery.refetch()}>Reintentar</Button>
              </div>
            ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nombre</TableHead>
                  <TableHead>Tipo</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Progreso</TableHead>
                  <TableHead>Tareas</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {projects.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium">
                      <Link to={`/projects/${p.id}`} className="text-brand hover:underline">
                        {p.name}
                      </Link>
                    </TableCell>
                    <TableCell>{p.project_type || "-"}</TableCell>
                    <TableCell>
                      <Badge variant={p.status === "active" ? "success" : p.status === "completed" ? "secondary" : "warning"}>
                        {{ planning: "Planificación", active: "Activo", on_hold: "Pausado", completed: "Completado", cancelled: "Cancelado" }[p.status]}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <div className="w-20 h-2 bg-muted rounded-full overflow-hidden">
                          <div
                            className="h-full bg-brand rounded-full"
                            style={{ width: `${p.progress_percent}%` }}
                          />
                        </div>
                        <span className="text-xs mono">{p.progress_percent}%</span>
                      </div>
                    </TableCell>
                    <TableCell className="mono">{p.completed_task_count}/{p.task_count}</TableCell>
                  </TableRow>
                ))}
                {projects.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                      No hay proyectos
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
            )}
          </CardContent>
        </Card>
      )}

      {/* Tab: Panel */}
      {activeTab === "panel" && (
        <div className="space-y-6">
          <EngineMetricsWidget client={client} />
          <RevenueIntelligenceCard client={client} />
          <ClientDashboardTab client={client} />
        </div>
      )}

      {/* Tab: Resúmenes */}
      {activeTab === "resumenes" && (
        <ClientReportPolicy clientId={clientId} clientName={client.name} />
      )}

      {/* Tab: Comunicaciones */}
      {activeTab === "comunicaciones" && (
        <Card>
          <CardContent className="p-6">
            <CommunicationList clientId={clientId} />
          </CardContent>
        </Card>
      )}

      {/* Tab: Contactos */}
      {activeTab === "contactos" && (
        <Card>
          <CardContent className="p-6">
            <ContactList clientId={clientId} />
          </CardContent>
        </Card>
      )}

      {/* Tab: Tiempo */}
      {activeTab === "tiempo" && (
        <Card>
          <CardHeader>
            <CardTitle>Entradas de tiempo recientes</CardTitle>
          </CardHeader>
          <CardContent className="pt-4">
            {recentEntriesQuery.isPending ? (
              <p role="status" className="py-8 text-center text-sm text-muted-foreground">Cargando tiempo…</p>
            ) : recentEntriesQuery.isError ? (
              <div role="alert" className="flex items-center justify-between gap-3 py-4 text-sm">
                <span>No se pudo cargar el tiempo registrado.</span>
                <Button size="sm" variant="outline" onClick={() => recentEntriesQuery.refetch()}>Reintentar</Button>
              </div>
            ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Fecha</TableHead>
                  <TableHead>Tarea</TableHead>
                  <TableHead>Duracion</TableHead>
                  <TableHead>Notas</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentEntries.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="mono">{formatCivilDate(timeEntryBusinessDate(e))}</TableCell>
                    <TableCell>{e.task_title || "-"}</TableCell>
                    <TableCell className="mono">{e.minutes ? formatMinutes(e.minutes) : "-"}</TableCell>
                    <TableCell className="max-w-[200px] truncate">{e.notes || "-"}</TableCell>
                  </TableRow>
                ))}
                {recentEntries.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-foreground py-8">
                      No hay entradas de tiempo
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
            )}
          </CardContent>
        </Card>
      )}

      {/* Tab: SEO */}
      {activeTab === "seo" && client.engine_project_id && <EngineSeoTab client={client} />}

      {/* Tab: Core Updates */}
      {/* CoreUpdatesTab removed — analysis only available in Engine */}

      {/* Tab: Recursos */}
      {activeTab === "recursos" && (
        <Card>
          <CardContent className="p-6">
            <ResourceList clientId={clientId} />
          </CardContent>
        </Card>
      )}

      {/* Tab: Facturacion */}
      {activeTab === "facturacion" && (
        <BillingTab client={client} />
      )}

      {/* Tab: Informes */}
      {activeTab === "informes" && (
        <Card>
          <CardContent className="p-6">
            <ClientReportsTab clientId={clientId} clientName={client.name} engineProjectId={client.engine_project_id} />
          </CardContent>
        </Card>
      )}

      {/* Tab: Ajustes */}
      {activeTab === "ajustes" && (
        <ClientSettingsTab client={client} />
      )}

      {/* Tab: Facturas (Holded) */}
      {activeTab === "facturas" && holdedEnabled && (
        <Card>
          <CardHeader>
            <CardTitle>Facturas (Holded)</CardTitle>
          </CardHeader>
          <CardContent className="pt-4">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nº Factura</TableHead>
                  <TableHead>Fecha</TableHead>
                  <TableHead>Vencimiento</TableHead>
                  <TableHead>Total</TableHead>
                  <TableHead>Estado</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {clientInvoices.map((inv) => (
                  <TableRow key={inv.holded_id}>
                    <TableCell className="font-medium">{inv.invoice_number || "-"}</TableCell>
                    <TableCell className="mono">{inv.date ? new Date(inv.date).toLocaleDateString("es-ES") : "-"}</TableCell>
                    <TableCell className="mono">{inv.due_date ? new Date(inv.due_date).toLocaleDateString("es-ES") : "-"}</TableCell>
                    <TableCell className="mono font-semibold">{formatCurrency(inv.total, inv.currency || "EUR")}</TableCell>
                    <TableCell>
                      <Badge variant={inv.status === "paid" ? "success" : inv.status === "overdue" ? "destructive" : "warning"}>
                        {inv.status === "paid" ? "Pagada" : inv.status === "overdue" ? "Vencida" : "Pendiente"}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
                {clientInvoices.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                      No hay facturas de Holded para este cliente
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Time Log Dialog */}
      {timeLogTaskId && (
        <TimeLogDialog
          taskId={timeLogTaskId.id}
          taskTitle={timeLogTaskId.title}
          taskRetired={timeLogTaskId.retired}
          open={!!timeLogTaskId}
          onOpenChange={(open) => !open && setTimeLogTaskId(null)}
        />
      )}
      <TaskPanel
        open={taskPanelId !== null || creatingTask}
        taskId={taskPanelId}
        defaults={creatingTask ? { clientId } : undefined}
        onOpenChange={(open) => { if (!open) { setTaskPanelId(null); setCreatingTask(false) } }}
        onOpenTime={(task) => { setTaskPanelId(null); setTimeLogTaskId({ id: task.id, title: task.title, retired: !!task.retired_at }) }}
      />

      {/* What-If Modal */}
      <Dialog open={whatIfOpen} onOpenChange={setWhatIfOpen}>
        <DialogHeader>
          <DialogTitle>Impacto financiero — {client?.name}</DialogTitle>
        </DialogHeader>
        {whatIfLoading && <p className="p-4 text-muted-foreground">Calculando...</p>}
        {whatIfData && (
          <div className="p-4 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">Ingreso mensual medio</p>
                <p className="text-2xl font-bold">{formatCurrency(whatIfData.avg_monthly_revenue)}</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">% del total de ingresos</p>
                <p className="text-2xl font-bold">{whatIfData.pct_of_total_revenue}%</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">Ingreso anual estimado</p>
                <p className="text-xl font-bold">{formatCurrency(whatIfData.annual_revenue_estimate)}</p>
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-xs text-muted-foreground">Runway sin este cliente</p>
                <p className={`text-xl font-bold ${whatIfData.runway_without_client != null && whatIfData.runway_without_client < 6 ? "text-red-500" : "text-green-500"}`}>
                  {whatIfData.runway_without_client != null ? `${whatIfData.runway_without_client} meses` : "∞"}
                </p>
              </div>
            </div>
            {whatIfData.pct_of_total_revenue > 30 && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-400">
                Este cliente representa mas del 30% de tus ingresos. Alta concentracion de riesgo.
              </div>
            )}
          </div>
        )}
      </Dialog>
    </div>
  )
}
