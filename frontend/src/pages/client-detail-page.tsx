import { useState } from "react"
import { useParams, Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { clientsApi, timeEntriesApi, projectsApi, holdedApi, clientHealthApi } from "@/lib/api"
import type { TaskStatus } from "@/lib/types"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { ArrowLeft, Clock, Heart } from "lucide-react"
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
import { ClientSettingsTab } from "@/components/clients/client-settings-tab"

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
  const map: Record<TaskStatus, { label: string; variant: "secondary" | "warning" | "success" }> = {
    pending: { label: "Pendiente", variant: "secondary" },
    in_progress: { label: "En curso", variant: "warning" },
    completed: { label: "Completada", variant: "success" },
  }
  const { label, variant } = map[status]
  return <Badge variant={variant}>{label}</Badge>
}

export default function ClientDetailPage() {
  const { id } = useParams<{ id: string }>()
  const clientId = Number(id)
  const [timeLogTaskId, setTimeLogTaskId] = useState<{ id: number; title: string } | null>(null)
  const [activeTab, setActiveTab] = useState<"actividad" | "tareas" | "proyectos" | "comunicaciones" | "contactos" | "panel" | "tiempo" | "facturacion" | "recursos" | "informes" | "ajustes" | "facturas">("actividad")

  const { data: summary, isLoading } = useQuery({
    queryKey: ["client-summary", clientId],
    queryFn: () => clientsApi.summary(clientId),
    enabled: !!clientId,
  })

  const { data: projects = [] } = useQuery({
    queryKey: ["client-projects", clientId],
    queryFn: () => projectsApi.listAll({ client_id: clientId }),
    enabled: !!clientId,
  })

  const { data: holdedConfig } = useQuery({
    queryKey: ["holded-config"],
    queryFn: holdedApi.config,
    staleTime: 5 * 60_000,
    retry: false,
  })
  const holdedEnabled = holdedConfig?.api_key_configured ?? false

  const { data: clientInvoices = [] } = useQuery({
    queryKey: ["holded-client-invoices", clientId],
    queryFn: () => holdedApi.clientInvoices(clientId),
    enabled: !!clientId && holdedEnabled,
  })

  const { data: health } = useQuery({
    queryKey: ["client-health", clientId],
    queryFn: () => clientHealthApi.get(clientId),
    enabled: !!clientId,
    staleTime: 60_000,
  })

  const { data: recentEntries = [] } = useQuery({
    queryKey: ["time-entries-client", clientId],
    queryFn: async () => {
      if (!summary?.tasks.length) return []
      const allEntries = await Promise.all(
        summary.tasks.slice(0, 10).map((t) => timeEntriesApi.list({ task_id: t.id }))
      )
      return allEntries.flat().sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()).slice(0, 10)
    },
    enabled: !!summary?.tasks.length,
  })

  if (isLoading) return <p className="text-muted-foreground">Cargando...</p>
  if (!summary) return <p className="text-muted-foreground">Cliente no encontrado</p>

  const { client, tasks } = summary

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link to="/clients">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold uppercase tracking-wide">{client.name}</h2>
            {statusBadge(client.status)}
          </div>
          {client.company && <p className="text-muted-foreground">{client.company}</p>}
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Total tareas</p>
            <p className="kpi-value mt-1">{summary.total_tasks}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Tiempo estimado</p>
            <p className="kpi-value mt-1">{formatMinutes(summary.total_estimated_minutes)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Tiempo real</p>
            <p className="kpi-value mt-1">{formatMinutes(summary.total_actual_minutes)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Tiempo tracked</p>
            <p className="kpi-value mt-1">{formatMinutes(summary.total_tracked_minutes)}</p>
          </CardContent>
        </Card>
        {health && (
          <Card className={health.risk_level === "at_risk" ? "border-red-300 bg-red-50/50" : health.risk_level === "warning" ? "border-amber-300 bg-amber-50/50" : ""}>
            <CardContent className="p-4">
              <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                <Heart className="h-3 w-3" /> Salud
              </p>
              <p className={`kpi-value mt-1 ${health.risk_level === "healthy" ? "text-green-600" : health.risk_level === "warning" ? "text-amber-500" : "text-red-500"}`}>
                {health.score}/100
              </p>
              <div className="mt-2 grid grid-cols-5 gap-1">
                {[
                  { label: "Com", val: health.factors.communication, max: 25 },
                  { label: "Tar", val: health.factors.tasks, max: 25 },
                  { label: "Dig", val: health.factors.digests, max: 15 },
                  { label: "Ren", val: health.factors.profitability, max: 20 },
                  { label: "Fup", val: health.factors.followups, max: 15 },
                ].map((f) => (
                  <div key={f.label} className="text-center">
                    <div className="text-[9px] text-muted-foreground">{f.label}</div>
                    <div className="h-1 bg-muted rounded-full overflow-hidden mt-0.5">
                      <div className="h-full bg-brand rounded-full" style={{ width: `${(f.val / f.max) * 100}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Tabs */}
      <div className="flex items-center space-x-1 bg-muted/30 p-1 w-fit rounded-lg border border-border overflow-x-auto">
        {(["actividad", "tareas", "proyectos", "panel", "comunicaciones", "contactos", "tiempo", "facturacion", "recursos", "informes", ...(holdedEnabled ? ["facturas" as const] : []), "ajustes"] as const).map((tab) => (
          <Button
            key={tab}
            variant={activeTab === tab ? "default" : "ghost"}
            size="sm"
            className="capitalize whitespace-nowrap"
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </Button>
        ))}
      </div>

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
            <CardTitle>Tareas</CardTitle>
          </CardHeader>
          <CardContent className="pt-4">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Titulo</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Est.</TableHead>
                  <TableHead>Real</TableHead>
                  <TableHead>Timer</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tasks.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-medium">{t.title}</TableCell>
                    <TableCell>{taskStatusBadge(t.status)}</TableCell>
                    <TableCell className="mono">{t.estimated_minutes ? formatMinutes(t.estimated_minutes) : "-"}</TableCell>
                    <TableCell className="mono">{t.actual_minutes ? formatMinutes(t.actual_minutes) : "-"}</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <TimerButton taskId={t.id} />
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => setTimeLogTaskId({ id: t.id, title: t.title })}
                        >
                          <Clock className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
                {tasks.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                      No hay tareas
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
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
                        {p.status}
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
          </CardContent>
        </Card>
      )}

      {/* Tab: Panel */}
      {activeTab === "panel" && (
        <ClientDashboardTab client={client} />
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
                    <TableCell className="mono">{new Date(e.date).toLocaleDateString("es-ES")}</TableCell>
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
          </CardContent>
        </Card>
      )}

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
            <ClientReportsTab clientId={clientId} clientName={client.name} />
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
                    <TableCell className="mono font-semibold">{inv.total.toLocaleString("es-ES", { style: "currency", currency: inv.currency || "EUR" })}</TableCell>
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
          open={!!timeLogTaskId}
          onOpenChange={(open) => !open && setTimeLogTaskId(null)}
        />
      )}
    </div>
  )
}
