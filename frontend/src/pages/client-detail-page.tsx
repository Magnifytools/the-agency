import { formatCivilDate, timeEntryBusinessDate } from "@/lib/dates"
import { useState } from "react"
import { useParams, Link, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { usePageTitle } from "@/hooks/use-page-title"
import { clientsApi, projectsApi, holdedApi, clientStatusApi, engineApi } from "@/lib/api"
import type { TaskStatus } from "@/lib/types"
import { isEnabled } from "@/lib/hidden-modules"
import { Select } from "@/components/ui/select"
import { ExternalLink, Settings } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Clock } from "lucide-react"
import { Breadcrumb } from "@/components/ui/breadcrumb"
import { Skeleton, SkeletonCard } from "@/components/ui/skeleton"
import { TimerButton } from "@/components/timer/timer-button"
import { TimeLogDialog } from "@/components/timer/time-log-dialog"
import { CommunicationList } from "@/components/communications/communication-list"
import { ContactList } from "@/components/clients/contact-list"
import { ActivityTimeline } from "@/components/clients/activity-timeline"
import { ClientDashboardTab } from "@/components/clients/client-dashboard-tab"
import { ClientAiAdvisor } from "@/components/clients/client-ai-advisor"
import { ClientReportPolicy } from "@/components/clients/client-report-policy"
import { ClientSettingsTab } from "@/components/clients/client-settings-tab"
import { BrandTermsNotice } from "@/components/clients/brand-terms-notice"
import { ClientDigestVersions } from "@/components/clients/client-digest-versions"
import { EngineMetricsWidget } from "@/components/clients/engine-metrics-widget"
import { EngineSeoTab } from "@/components/clients/engine-seo-tab"
import { SeoControlTab } from "@/components/clients/seo-control/seo-control-tab"
import { LocalReportTab } from "@/components/clients/local-report/local-report-tab"
import { FichaTab } from "@/components/clients/ficha-tab"
import { useAuth } from "@/context/auth-context"
import { clientKeys, holdedKeys, projectKeys, timeKeys } from "@/lib/query-keys"
import { formatCurrency } from "@/lib/format"
import { TaskPanel } from "@/components/tasks/task-panel"
import { ClientLifecycleButton, FormerClientNotice } from "@/components/clients/client-lifecycle"
import { ClientOverview } from "@/components/clients/client-overview"
import { ClientCredentialsTab } from "@/components/credentials/client-credentials-tab"
import { WebTab } from "@/components/web/web-tab"
import { ScopeRequestsTab } from "@/components/clients/scope-requests-tab"
import { InvoiceStatusBadge } from "@/components/finance/invoice-status-badge"

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
    finished: { label: "Antiguo", variant: "secondary" },
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

export default function ClientDetailPage() {
  const { user, isAdmin, hasPermission } = useAuth()
  const canReadClient = hasPermission("clients")
  const canReadTasks = hasPermission("tasks") && isEnabled("tasks")
  const canReadTime = canReadTasks && hasPermission("timesheet") && isEnabled("timesheet")
  const canReadFinancialPanel = isAdmin && isEnabled("finance")
  const { id } = useParams<{ id: string }>()
  const clientId = Number(id)
  const [searchParams, setSearchParams] = useSearchParams()
  const [timeLogTaskId, setTimeLogTaskId] = useState<{ id: number; title: string; retired?: boolean } | null>(null)
  const [taskPanelId, setTaskPanelId] = useState<number | null>(null)
  const [creatingTask, setCreatingTask] = useState(false)
  const [whatIfOpen, setWhatIfOpen] = useState(false)

  const validTabs = ["ficha", "contexto", "actividad", "tareas", "proyectos", "resumenes", "comunicaciones", "contactos", "panel", "tiempo", "control_seo", "seo", "ajustes", "facturas", "accesos", "web", "peticiones", "informe_local"] as const
  type Tab = (typeof validTabs)[number]

  // Pestaña -> módulo que la sirve. Si el módulo está oculto, sus endpoints no
  // están registrados, así que la pestaña no puede renderizarse ni aunque
  // llegue en la URL (un enlace guardado con ?tab=comunicaciones, por ejemplo).
  const TAB_MODULE: Partial<Record<Tab, string>> = {
    resumenes: "digests",
    comunicaciones: "communications",
    facturas: "holded",
    web: "web",
  }
  const TAB_PERMISSION: Partial<Record<Tab, string>> = {
    // Control SEO lee /api/clients/{id}/seo: lectura de clientes (la de la ficha).
    control_seo: "clients",
    tareas: "tasks",
    proyectos: "projects",
    resumenes: "digests",
    // Informe SEO local: un entregable al cliente, con los permisos de Resúmenes.
    informe_local: "digests",
    comunicaciones: "communications",
    accesos: "credentials",
    web: "web",
  }
  const isTabVisible = (tab: Tab) => {
    if (tab === "tiempo") return canReadTime
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
    enabled: !!clientId && canReadClient,
  })
  const { data: summary, isLoading } = summaryQuery
  usePageTitle(summary?.client.name)

  const projectsQuery = useQuery({
    queryKey: projectKeys.client(clientId),
    queryFn: () => projectsApi.listAll({ client_id: clientId }),
    enabled: !!clientId && canReadClient && activeTab === "proyectos" && hasPermission("projects"),
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

  // The Engine está congelado (21 oct 2026): sólo se pregunta por él si el
  // cliente sigue vinculado (enlaces "Abrir en Engine" y pestaña Engine).
  const { data: engineConfig } = useQuery({
    queryKey: ["engine-config"],
    queryFn: () => engineApi.getConfig(),
    staleTime: 10 * 60_000,
    enabled: !!summary?.client.engine_project_id,
  })

  const canReadClientHealth = canReadClient
  const healthAccessScope = [
    user?.id ?? "anonymous", isAdmin,
    ...(["tasks", "digests", "timesheet"] as const)
      .map((module) => hasPermission(module) && isEnabled(module)),
  ].join(":")
  const healthQuery = useQuery({
    queryKey: ["client-status", clientId, healthAccessScope],
    queryFn: () => clientStatusApi.get(clientId),
    enabled: !!clientId && canReadClientHealth,
    staleTime: 60_000,
  })
  const health = canReadClientHealth && !healthQuery.isError ? healthQuery.data : undefined

  const recentEntriesQuery = useQuery({
    queryKey: timeKeys.client(clientId),
    queryFn: () => clientsApi.recentTimeEntries(clientId),
    enabled: !!clientId && canReadClient && canReadTime && activeTab === "tiempo",
  })
  const recentEntries = canReadTime ? recentEntriesQuery.data ?? [] : []

  const { data: whatIfData, isLoading: whatIfLoading } = useQuery({
    queryKey: ["client-what-if", clientId],
    queryFn: () => clientsApi.whatIf(clientId),
    enabled: whatIfOpen && !!clientId && canReadClient && canReadFinancialPanel,
  })

  if (!canReadClient) return <p role="alert">No tienes acceso a este cliente.</p>
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

  const { client } = summary
  // The same summary query can remain cached after permissions are refreshed.
  // Gate cached projections with the current permissions before rendering.
  const tasks = canReadTasks ? summary.tasks ?? [] : []
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
          {canReadTime && <TimerButton taskId={t.id} />}
          {canReadTime && <Button
            variant="ghost"
            size="icon"
            aria-label={`Ver horas de ${t.title}`}
            onClick={() => setTimeLogTaskId({ id: t.id, title: t.title, retired: !!t.retired_at })}
          >
            <Clock className="h-4 w-4" />
          </Button>}
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
          <TableHead>Cronómetro</TableHead>
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
        { label: "Inicio", href: "/" },
        { label: "Clientes", href: "/clients" },
        { label: client.name },
      ]} />
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold uppercase tracking-wide">{client.name}</h1>
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
        <div className="flex items-center gap-2">
          <ClientLifecycleButton client={client} />
          {canReadFinancialPanel && activeTab === "panel" && <Button variant="outline" size="sm" onClick={() => setWhatIfOpen(true)}>
            ¿Y si pierdo este cliente?
          </Button>}
          <Button
            variant={activeTab === "ajustes" || activeTab === "facturas" ? "secondary" : "ghost"}
            size="icon"
            aria-label="Ajustes del cliente"
            title="Ajustes del cliente"
            onClick={() => setActiveTab("ajustes")}
          >
            <Settings className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <FormerClientNotice client={client} />
      {activeTab !== "ajustes" && (
        <BrandTermsNotice client={client} onConfigure={() => setSearchParams({ tab: "ajustes", foco: "marca" }, { replace: true })} />
      )}

      {/* Cuatro áreas estables; las URLs ?tab= heredadas siguen seleccionando
          su vista concreta dentro del área correspondiente. */}
      {(() => {
        type TabKey = Tab
        type AreaDef = { key: string; label: string; tabs: TabKey[] }
        const areas = ([
          {
            key: "resumen",
            label: "Vista general",
            tabs: ["ficha", "actividad"],
          },
          {
            key: "trabajo",
            label: "Trabajo",
            tabs: [
              ...(isTabVisible("tareas") ? (["tareas"] as TabKey[]) : []),
              ...(isTabVisible("proyectos") ? (["proyectos"] as TabKey[]) : []),
              ...(canReadTime ? (["tiempo"] as TabKey[]) : []),
              "peticiones",
            ],
          },
          {
            key: "outputs",
            label: "Resultados",
            tabs: [
              ...(isTabVisible("resumenes") ? (["resumenes"] as TabKey[]) : []),
              // Informe SEO local: sale de Search Console, así que pide propiedad.
              ...(client.gsc_url && isTabVisible("informe_local") ? (["informe_local"] as TabKey[]) : []),
              // Control SEO (Search Console propio) con propiedad.
              ...(client.gsc_url ? (["control_seo"] as TabKey[]) : []),
              ...(isTabVisible("web") ? (["web"] as TabKey[]) : []),
              "panel",
              ...(isTabVisible("comunicaciones")
                ? (["comunicaciones"] as TabKey[])
                : []),
            ],
          },
          {
            key: "relacion",
            label: "Relación",
            tabs: [
              "contexto",
              "contactos",
              ...(isTabVisible("accesos") ? (["accesos"] as TabKey[]) : []),
            ],
          },
          {
            // Fuera de la fila de áreas: se abre con el engranaje de la cabecera.
            key: "ajustes",
            label: "Ajustes",
            tabs: [
              ...(holdedEnabled && isTabVisible("facturas")
                ? (["facturas"] as TabKey[])
                : []),
              "ajustes",
              // Engine está congelado: su pestaña (clave ?tab=seo) sale de
              // Resultados y queda junto a la configuración.
              ...(client.engine_project_id ? (["seo"] as TabKey[]) : []),
            ],
          },
        ] satisfies AreaDef[]).filter((area) => area.tabs.length > 0)
        const activeArea =
          areas.find((area) => area.tabs.includes(activeTab)) ?? areas[0]
        const tabLabels: Record<TabKey, string> = {
          ficha: "Vista general",
          contexto: "Contexto",
          actividad: "Actividad",
          panel: "Horas y rentabilidad",
          tareas: "Tareas",
          proyectos: "Proyectos",
          tiempo: "Tiempo",
          peticiones: "Peticiones extra",
          informe_local: "Informe SEO local",
          resumenes: "Resúmenes",
          comunicaciones: "Comunicaciones",
          control_seo: "Control SEO",
          seo: "Engine (congelado)",
          contactos: "Contactos",
          accesos: "Accesos",
          web: "Web",
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
              {areas.filter((area) => area.key !== "ajustes").map((area) => (
                <option key={area.key} value={area.key}>
                  {area.label}
                </option>
              ))}
            </Select>
            <div className="hidden md:flex items-center gap-1 bg-muted/30 p-1 w-fit rounded-lg border border-border">
              {areas.filter((area) => area.key !== "ajustes").map((area) => (
                <Button
                  key={area.key}
                  variant={activeArea.key === area.key ? "default" : "ghost"}
                  size="sm"
                  aria-current={activeArea.key === area.key ? "true" : undefined}
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
                    aria-current={activeTab === tab ? "page" : undefined}
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
      {activeTab === "panel" && <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {canReadTasks && <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Total tareas</p>
            <p className="kpi-value mt-1">{summary.total_tasks ?? "—"}</p>
          </CardContent>
        </Card>}
        {canReadTime && <Card
          className="lg:col-span-2"
          title="Tiempo fichado: suma del cronómetro real del equipo. Estimado: lo previsto al crear la tarea. Declarado: lo que el responsable apuntó al cerrarla."
        >
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              Tiempo fichado
              <span className="text-muted-foreground/60 cursor-help">ⓘ</span>
            </p>
            <p className="kpi-value mt-1">{summary.total_tracked_minutes == null ? "—" : formatMinutes(summary.total_tracked_minutes)}</p>
            <div className="mt-2 flex items-center gap-3 text-[11px] text-muted-foreground">
              <span>
                Estimado: <span className="mono">{summary.total_estimated_minutes == null ? "—" : formatMinutes(summary.total_estimated_minutes)}</span>
              </span>
              <span className="text-muted-foreground/40">·</span>
              <span>
                Declarado: <span className="mono">{summary.total_actual_minutes == null ? "—" : formatMinutes(summary.total_actual_minutes)}</span>
              </span>
            </div>
          </CardContent>
        </Card>}
      </div>}

      {/* Tab: Vista general — estado + Trabajo · Resultados · Relación */}
      {activeTab === "ficha" && (
        <ClientOverview
          client={client}
          status={health}
          statusFailed={canReadClientHealth && healthQuery.isError}
          onRetryStatus={() => void healthQuery.refetch()}
          tasks={canReadTasks ? summary.tasks ?? [] : null}
          canReadDigests={isTabVisible("resumenes")}
          canReadContacts
          onNavigate={(section) => setActiveTab(section)}
        />
      )}

      {/* Tab: Contexto (historia editable + interlocutor) */}
      {activeTab === "contexto" && (
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
                {projects.map((p) => {
                  const hasTaskMetrics = p.progress_percent != null
                    && p.completed_task_count != null
                    && p.task_count != null
                  return (
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
                      {hasTaskMetrics ? <div className="flex items-center gap-2">
                        <div className="w-20 h-2 bg-muted rounded-full overflow-hidden">
                          <div
                            className="h-full bg-brand rounded-full"
                            style={{ width: `${p.progress_percent}%` }}
                          />
                        </div>
                        <span className="text-xs mono">{p.progress_percent}%</span>
                      </div> : <span className="text-sm text-muted-foreground">No disponible</span>}
                    </TableCell>
                    <TableCell className="mono">{hasTaskMetrics ? `${p.completed_task_count}/${p.task_count}` : "No disponible"}</TableCell>
                  </TableRow>
                  )
                })}
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
          {canReadFinancialPanel && canReadTime && <ClientDashboardTab client={client} />}
        </div>
      )}

      {/* Tab: Resúmenes */}
      {activeTab === "resumenes" && (
        <div className="space-y-6">
          <ClientReportPolicy clientId={clientId} clientName={client.name} />
          <ClientDigestVersions clientId={clientId} />
        </div>
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

      {/* Tab: Accesos (sólo los que quien mira puede ver) */}
      {activeTab === "accesos" && <ClientCredentialsTab clientId={clientId} />}

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

      {/* Tab: Control SEO (Search Console por consulta y página) */}
      {activeTab === "control_seo" && client.gsc_url && (
        <SeoControlTab client={client} onOpenSettings={() => setActiveTab("ajustes")} />
      )}

      {/* Tab: Engine (antes "SEO"; la clave ?tab=seo se mantiene) */}
      {activeTab === "seo" && client.engine_project_id && <EngineSeoTab client={client} />}

      {/* Tab: Web (disponibilidad) */}
      {activeTab === "peticiones" && <ScopeRequestsTab clientId={clientId} />}
      {activeTab === "informe_local" && <LocalReportTab clientId={clientId} />}

      {activeTab === "web" && <WebTab clientId={clientId} website={client.website ?? null} />}

      {/* Tab: Ajustes */}
      {activeTab === "ajustes" && (
        <ClientSettingsTab client={client} focus={searchParams.get("foco")} />
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
                      <InvoiceStatusBadge status={inv.status} />
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
      {canReadTime && timeLogTaskId && (
        <TimeLogDialog
          taskId={timeLogTaskId.id}
          taskTitle={timeLogTaskId.title}
          taskRetired={timeLogTaskId.retired}
          open={!!timeLogTaskId}
          onOpenChange={(open) => !open && setTimeLogTaskId(null)}
        />
      )}
      <TaskPanel
        open={canReadTasks && (taskPanelId !== null || creatingTask)}
        taskId={taskPanelId}
        defaults={creatingTask ? { clientId } : undefined}
        onOpenChange={(open) => { if (!open) { setTaskPanelId(null); setCreatingTask(false) } }}
        onOpenTime={(task) => { if (canReadTime) { setTaskPanelId(null); setTimeLogTaskId({ id: task.id, title: task.title, retired: !!task.retired_at }) } }}
      />

      {/* What-If Modal */}
      <Dialog open={canReadFinancialPanel && whatIfOpen} onOpenChange={setWhatIfOpen}>
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
