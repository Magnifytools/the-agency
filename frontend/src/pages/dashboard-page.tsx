import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { dashboardApi, discordApi, tasksApi, timeEntriesApi, digestsApi, clientsApi, leadsApi, proposalsApi } from "@/lib/api"
import { useAuth } from "@/context/auth-context"
import { MetricCard } from "@/components/dashboard/metric-card"
import { ProfitabilityChart } from "@/components/dashboard/profitability-chart"
import { InsightsPanel } from "@/components/pm/insights-panel"
import { DailyBriefingButton } from "@/components/pm/daily-briefing"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Select } from "@/components/ui/select"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Users, CheckSquare, Clock, DollarSign, Send, Eye, Newspaper, Target, FileText } from "lucide-react"
import { toast } from "sonner"
import { Link } from "react-router-dom"
import { InboxWidget } from "@/components/dashboard/inbox-widget"
import { getErrorMessage } from "@/lib/utils"

const MONTHS = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

function profitBadge(status: string) {
  const map: Record<string, { label: string; variant: "success" | "warning" | "destructive" }> = {
    profitable: { label: "Rentable", variant: "success" },
    at_risk: { label: "En riesgo", variant: "warning" },
    unprofitable: { label: "No rentable", variant: "destructive" },
  }
  const { label, variant } = map[status] || { label: status, variant: "secondary" as any }
  return <Badge variant={variant}>{label}</Badge>
}

export default function DashboardPage() {
  const { user } = useAuth()
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [previewOpen, setPreviewOpen] = useState(false)
  const queryClient = useQueryClient()

  const params = { year, month }

  const { data: overview } = useQuery({
    queryKey: ["dashboard-overview", year, month],
    queryFn: () => dashboardApi.overview(params),
  })

  const { data: profitability } = useQuery({
    queryKey: ["dashboard-profitability", year, month],
    queryFn: () => dashboardApi.profitability(params),
  })

  const { data: team } = useQuery({
    queryKey: ["dashboard-team", year, month],
    queryFn: () => dashboardApi.team(params),
  })

  const { data: monthlyClose } = useQuery({
    queryKey: ["dashboard-monthly-close", year, month],
    queryFn: () => dashboardApi.monthlyClose(params),
  })

  const { data: financialSettings } = useQuery({
    queryKey: ["dashboard-financial-settings"],
    queryFn: () => dashboardApi.financialSettings(),
  })

  const { data: preview, refetch: fetchPreview } = useQuery({
    queryKey: ["discord-preview"],
    queryFn: () => discordApi.preview(),
    enabled: false,
  })

  const sendMutation = useMutation({
    mutationFn: () => discordApi.send(),
    onSuccess: () => toast.success("Resumen enviado a Discord"),
    onError: (err) => toast.error(getErrorMessage(err, "Error al enviar a Discord")),
  })

  const closeMutation = useMutation({
    mutationFn: (payload: Record<string, boolean | string>) => dashboardApi.updateMonthlyClose(payload, params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard-monthly-close", year, month] })
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar el cierre")),
  })

  const financialMutation = useMutation({
    mutationFn: (payload: Record<string, number>) => dashboardApi.updateFinancialSettings(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard-financial-settings"] })
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar los guardarraíles")),
  })

  // Worker-specific queries
  const { data: myInProgressTasks } = useQuery({
    queryKey: ["my-tasks-in-progress", user?.id],
    queryFn: () => tasksApi.listAll({ assigned_to: user!.id, status: "in_progress" }),
    enabled: !!user && user.role === "member",
  })

  const { data: myPendingTasks } = useQuery({
    queryKey: ["my-tasks-pending", user?.id],
    queryFn: () => tasksApi.listAll({ assigned_to: user!.id, status: "pending" }),
    enabled: !!user && user.role === "member",
  })

  const { data: myOverdueTasks } = useQuery({
    queryKey: ["my-tasks-overdue", user?.id],
    queryFn: () => tasksApi.listAll({ assigned_to: user!.id, overdue: true }),
    enabled: !!user && user.role === "member",
  })

  const { data: weeklyTimesheet } = useQuery({
    queryKey: ["weekly-timesheet"],
    queryFn: () => timeEntriesApi.weekly(),
    enabled: !!user && user.role === "member",
  })

  // Admin overdue tasks
  const { data: allOverdueTasks } = useQuery({
    queryKey: ["all-overdue-tasks"],
    queryFn: () => tasksApi.listAll({ overdue: true }),
    enabled: !!user && user.role === "admin",
  })

  // Digest widget: clients without digest this week
  const { data: recentDigests } = useQuery({
    queryKey: ["recent-digests"],
    queryFn: () => digestsApi.list({ limit: 100 }),
    enabled: !!user,
  })
  const { data: allClients } = useQuery({
    queryKey: ["clients-all-active"],
    queryFn: () => clientsApi.listAll("active"),
    enabled: !!user,
  })

  // Lead reminders: followups overdue or within 3 days
  const { data: leadReminders } = useQuery({
    queryKey: ["lead-reminders"],
    queryFn: () => leadsApi.reminders(),
    enabled: !!user,
  })

  // Proposals pipeline
  const { data: allProposals } = useQuery({
    queryKey: ["proposals-pipeline"],
    queryFn: () => proposalsApi.list(),
    enabled: !!user,
  })

  const proposalStats = (() => {
    if (!allProposals) return null
    const drafts = allProposals.filter(p => p.status === "draft")
    const sent = allProposals.filter(p => p.status === "sent")
    const accepted = allProposals.filter(p => p.status === "accepted")
    const pipelineValue = sent.reduce((sum, p) => {
      const maxPrice = (p.pricing_options || []).reduce((max, opt) => Math.max(max, opt.price || 0), 0)
      return sum + maxPrice
    }, 0)
    return { drafts: drafts.length, sent: sent.length, accepted: accepted.length, total: allProposals.length, pipelineValue }
  })()

  // Compute clients missing digests this week
  const getMondayOfWeek = (d: Date) => {
    const day = d.getDay()
    const diff = d.getDate() - day + (day === 0 ? -6 : 1)
    return new Date(d.getFullYear(), d.getMonth(), diff).toISOString().slice(0, 10)
  }
  const thisMonday = getMondayOfWeek(new Date())
  const clientsWithDigestThisWeek = new Set(
    (recentDigests || [])
      .filter(d => d.period_start >= thisMonday || d.created_at >= thisMonday)
      .map(d => d.client_id)
  )
  const clientsMissingDigest = (allClients || []).filter(c => !clientsWithDigestThisWeek.has(c.id))

  const handlePreview = async () => {
    await fetchPreview()
    setPreviewOpen(true)
  }

  const isAdmin = user?.role === "admin"
  const closeKeys = ["reviewed_numbers", "reviewed_margin", "reviewed_cash_buffer", "reviewed_reinvestment", "reviewed_debt", "reviewed_taxes", "reviewed_personal"]
  const closeDoneCount = monthlyClose
    ? closeKeys.filter((key) => Boolean((monthlyClose as any)[key])).length
    : 0
  const closeTotalCount = closeKeys.length
  const closeDay = financialSettings?.monthly_close_day || 5
  const nowDay = new Date().getDate()
  const closeReminder = monthlyClose && nowDay >= closeDay && closeDoneCount < closeTotalCount
  const creditUtilization = financialSettings?.credit_utilization || 0
  const creditAlertPct = financialSettings?.credit_alert_pct || 70
  const taxReserve = financialSettings?.tax_reserve || 0
  const taxReserveTargetPct = financialSettings?.tax_reserve_target_pct || 20
  const monthlyCost = overview?.total_cost || 0
  const financialAlerts = [
    creditUtilization >= creditAlertPct
      ? {
        title: "Uso alto de línea de crédito",
        description: `La línea está al ${creditUtilization}%, supera el umbral ${creditAlertPct}%.`,
      }
      : null,
    monthlyCost > 0 && taxReserve < monthlyCost * (taxReserveTargetPct / 100)
      ? {
        title: "Fondo de impuestos bajo",
        description: "El fondo reservado parece insuficiente para costes actuales.",
      }
      : null,
  ].filter(Boolean) as { title: string; description: string }[]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold uppercase tracking-wide">Dashboard</h2>
        <div className="flex items-center gap-2">
          <DailyBriefingButton />
          <Select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="w-40">
            {MONTHS.map((m, i) => (
              <option key={i} value={i + 1}>{m}</option>
            ))}
          </Select>
          <Select value={year} onChange={(e) => setYear(Number(e.target.value))} className="w-24">
            {[now.getFullYear() - 1, now.getFullYear(), now.getFullYear() + 1].map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </Select>
        </div>
      </div>

      {/* ===== WORKER DASHBOARD ===== */}
      {!isAdmin && user && (
        <div className="space-y-6">
          {/* Mis horas esta semana */}
          {weeklyTimesheet && (() => {
            const myRow = weeklyTimesheet.users.find(u => u.user_id === user.id)
            const totalHours = myRow ? Math.round(myRow.total_minutes / 60 * 10) / 10 : 0
            return (
              <div className="grid grid-cols-2 gap-4">
                <MetricCard icon={Clock} label="Mis horas esta semana" value={`${totalHours}h`} />
                <MetricCard icon={CheckSquare} label="Tareas en curso" value={myInProgressTasks?.length ?? 0} subtitle={`${myPendingTasks?.length ?? 0} pendientes`} />
              </div>
            )
          })()}

          {/* Mis tareas vencidas */}
          {myOverdueTasks && myOverdueTasks.length > 0 && (
            <Card className="border-red-500/30 bg-red-500/5">
              <CardHeader className="pb-2">
                <CardTitle className="text-red-400 text-sm">Mis tareas vencidas ({myOverdueTasks.length})</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Tarea</TableHead>
                      <TableHead>Cliente</TableHead>
                      <TableHead>Fecha limite</TableHead>
                      <TableHead>Dias atrasada</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {myOverdueTasks.map(t => {
                      const daysOverdue = t.due_date ? Math.floor((Date.now() - new Date(t.due_date).getTime()) / 86400000) : 0
                      return (
                        <TableRow key={t.id}>
                          <TableCell className="font-medium">{t.title}</TableCell>
                          <TableCell>{t.client_name || "-"}</TableCell>
                          <TableCell className="mono">{t.due_date ? new Date(t.due_date).toLocaleDateString("es-ES") : "-"}</TableCell>
                          <TableCell className="text-red-400 font-bold">{daysOverdue}d</TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {/* Mis tareas en curso */}
          {myInProgressTasks && myInProgressTasks.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Mis tareas en curso</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Tarea</TableHead>
                      <TableHead>Cliente</TableHead>
                      <TableHead>Fecha limite</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {myInProgressTasks.map(t => (
                      <TableRow key={t.id}>
                        <TableCell className="font-medium">{t.title}</TableCell>
                        <TableCell>{t.client_name || "-"}</TableCell>
                        <TableCell className="mono">{t.due_date ? new Date(t.due_date).toLocaleDateString("es-ES") : "-"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {/* Mis tareas pendientes */}
          {myPendingTasks && myPendingTasks.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Mis tareas pendientes</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Tarea</TableHead>
                      <TableHead>Cliente</TableHead>
                      <TableHead>Fecha limite</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {myPendingTasks.map(t => (
                      <TableRow key={t.id}>
                        <TableCell className="font-medium">{t.title}</TableCell>
                        <TableCell>{t.client_name || "-"}</TableCell>
                        <TableCell className="mono">{t.due_date ? new Date(t.due_date).toLocaleDateString("es-ES") : "-"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {closeReminder && (
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm font-medium">Recordatorio de cierre mensual</div>
            <div className="text-xs text-muted-foreground mt-1">
              Estamos a partir del día {closeDay}. Completa el cierre mensual para evitar decisiones con datos incompletos.
            </div>
          </CardContent>
        </Card>
      )}

      {/* Metric Cards & Inbox */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          {overview && (
            <div className="grid grid-cols-2 gap-4">
              <MetricCard icon={Users} label="Clientes activos" value={overview.active_clients} />
              <MetricCard icon={CheckSquare} label="Tareas pendientes" value={overview.pending_tasks + overview.in_progress_tasks} subtitle={`${overview.in_progress_tasks} en curso`} />
              <MetricCard icon={Clock} label="Horas mes" value={`${overview.hours_this_month}h`} />
              <MetricCard icon={DollarSign} label="Presupuesto total" value={`${overview.total_budget.toLocaleString("es-ES")}€`} subtitle={`Coste: ${overview.total_cost.toLocaleString("es-ES")}€`} />
            </div>
          )}
        </div>
        <div className="lg:col-span-1 h-[250px]">
          <InboxWidget />
        </div>
      </div>

      {/* PM Insights Panel - Moved to the very top for Daily Ops focus */}
      <InsightsPanel />

      {/* Admin: Tareas vencidas */}
      {isAdmin && allOverdueTasks && allOverdueTasks.length > 0 && (
        <Card className="border-red-500/30 bg-red-500/5">
          <CardHeader className="pb-2">
            <CardTitle className="text-red-400 text-sm">Tareas vencidas ({allOverdueTasks.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tarea</TableHead>
                  <TableHead>Cliente</TableHead>
                  <TableHead>Asignado</TableHead>
                  <TableHead>Fecha limite</TableHead>
                  <TableHead>Dias atrasada</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {allOverdueTasks.map(t => {
                  const daysOverdue = t.due_date ? Math.floor((Date.now() - new Date(t.due_date).getTime()) / 86400000) : 0
                  return (
                    <TableRow key={t.id}>
                      <TableCell className="font-medium">{t.title}</TableCell>
                      <TableCell>{t.client_name || "-"}</TableCell>
                      <TableCell>{t.assigned_user_name || "-"}</TableCell>
                      <TableCell className="mono">{t.due_date ? new Date(t.due_date).toLocaleDateString("es-ES") : "-"}</TableCell>
                      <TableCell className="text-red-400 font-bold">{daysOverdue}d</TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Digest widget: clients missing digest this week */}
      {clientsMissingDigest.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-2">
                <Newspaper className="w-4 h-4" />
                Digests pendientes ({clientsMissingDigest.length})
              </CardTitle>
              <Link to="/digests">
                <Button variant="outline" size="sm">Ver digests</Button>
              </Link>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {clientsMissingDigest.map(c => (
                <Badge key={c.id} variant="secondary">{c.name}</Badge>
              ))}
            </div>
            <p className="text-xs text-muted-foreground mt-3">
              Estos clientes no tienen digest generado esta semana.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Lead reminders: followups overdue or within 3 days */}
      {leadReminders && leadReminders.length > 0 && (
        <Card className="border-brand/20">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-2">
                <Target className="w-4 h-4 text-brand" />
                Seguimientos de leads ({leadReminders.length})
              </CardTitle>
              <Link to="/leads">
                <Button variant="outline" size="sm">Ver pipeline</Button>
              </Link>
            </div>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Empresa</TableHead>
                  <TableHead>Contacto</TableHead>
                  <TableHead>Followup</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Notas</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {leadReminders.map(r => (
                  <TableRow key={r.id}>
                    <TableCell>
                      <Link to={`/leads/${r.id}`} className="font-medium text-brand hover:underline">
                        {r.company_name}
                      </Link>
                    </TableCell>
                    <TableCell>{r.contact_name || "-"}</TableCell>
                    <TableCell>
                      <span className={r.days_until_followup < 0 ? "text-red-400 font-bold" : r.days_until_followup === 0 ? "text-yellow-400 font-bold" : ""}>
                        {r.days_until_followup < 0
                          ? `${Math.abs(r.days_until_followup)}d atrasado`
                          : r.days_until_followup === 0
                          ? "Hoy"
                          : `En ${r.days_until_followup}d`}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="text-xs">{r.status}</Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">
                      {r.next_followup_notes || "-"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Proposals pipeline */}
      {proposalStats && proposalStats.total > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-2">
                <FileText className="w-4 h-4 text-brand" />
                Pipeline de propuestas
              </CardTitle>
              <Link to="/proposals">
                <Button variant="outline" size="sm">Ver propuestas</Button>
              </Link>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-6">
              <div className="text-center">
                <div className="text-2xl font-bold">{proposalStats.drafts}</div>
                <div className="text-xs text-muted-foreground">Borradores</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-blue-400">{proposalStats.sent}</div>
                <div className="text-xs text-muted-foreground">Enviadas</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-green-400">{proposalStats.accepted}</div>
                <div className="text-xs text-muted-foreground">Aceptadas</div>
              </div>
              {proposalStats.pipelineValue > 0 && (
                <div className="ml-auto text-right">
                  <div className="text-2xl font-bold text-brand">{proposalStats.pipelineValue.toLocaleString("es-ES")}€</div>
                  <div className="text-xs text-muted-foreground">Valor pipeline (enviadas)</div>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {financialAlerts.length > 0 && isAdmin && (
        <Card className="border-warning/50 bg-warning/5">
          <CardHeader className="pb-2">
            <CardTitle className="text-warning text-sm">Alertas financieras</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {financialAlerts.map((alert, index) => (
              <div key={index} className="flex flex-col">
                <span className="text-sm font-medium">{alert.title}</span>
                <span className="text-xs text-muted-foreground">{alert.description}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {financialSettings && isAdmin && (
        <details className="group border border-border rounded-xl bg-card">
          <summary className="flex cursor-pointer items-center justify-between p-4 font-medium marker:content-none hover:bg-muted/50 transition-colors rounded-xl">
            Configuración Financiera
            <svg className="h-5 w-5 text-muted-foreground transition-transform group-open:rotate-180" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </summary>
          <div className="p-4 pt-0 border-t border-border mt-2 space-y-4">
            <div className="grid gap-4 md:grid-cols-3">
              <div>
                <div className="text-xs text-muted-foreground mb-1">Fondo impuestos (€)</div>
                <input
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                  type="number"
                  step="0.01"
                  defaultValue={financialSettings.tax_reserve}
                  onBlur={(e) => financialMutation.mutate({ tax_reserve: Number(e.target.value) })}
                />
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">Línea crédito total (€)</div>
                <input
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                  type="number"
                  step="0.01"
                  defaultValue={financialSettings.credit_limit}
                  onBlur={(e) => financialMutation.mutate({ credit_limit: Number(e.target.value) })}
                />
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">Crédito utilizado (€)</div>
                <input
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                  type="number"
                  step="0.01"
                  defaultValue={financialSettings.credit_used}
                  onBlur={(e) => financialMutation.mutate({ credit_used: Number(e.target.value) })}
                />
                <div className="text-xs text-muted-foreground mt-1">
                  Uso: {financialSettings.credit_utilization}% (alerta {financialSettings.credit_alert_pct}%)
                </div>
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div>
                <div className="text-xs text-muted-foreground mb-1">Día récord. cierre</div>
                <input
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                  type="number"
                  min="1"
                  max="28"
                  step="1"
                  defaultValue={financialSettings.monthly_close_day}
                  onBlur={(e) => financialMutation.mutate({ monthly_close_day: Number(e.target.value) })}
                />
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">Alerta crédito (%)</div>
                <input
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                  type="number"
                  min="0"
                  max="100"
                  step="1"
                  defaultValue={financialSettings.credit_alert_pct}
                  onBlur={(e) => financialMutation.mutate({ credit_alert_pct: Number(e.target.value) })}
                />
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">Cob. impuestos (%)</div>
                <input
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                  type="number"
                  min="0"
                  max="200"
                  step="1"
                  defaultValue={financialSettings.tax_reserve_target_pct}
                  onBlur={(e) => financialMutation.mutate({ tax_reserve_target_pct: Number(e.target.value) })}
                />
              </div>
            </div>
          </div>
        </details>
      )}

      {monthlyClose && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>Cierre mensual</span>
              <div className="flex items-center gap-2">
                <Badge variant={closeDoneCount === closeTotalCount ? "success" : "warning"}>
                  {closeDoneCount === closeTotalCount ? "OK" : "Pendiente"}
                </Badge>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={async () => {
                    const blob = await dashboardApi.exportMonthlyClose({ year, month })
                    const url = window.URL.createObjectURL(blob)
                    const link = document.createElement("a")
                    link.href = url
                    link.download = `cierre-mensual-${year}-${String(month).padStart(2, "0")}.csv`
                    document.body.appendChild(link)
                    link.click()
                    link.remove()
                    window.URL.revokeObjectURL(url)
                  }}
                >
                  Exportar CSV
                </Button>
              </div>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <div className="text-xs text-muted-foreground mb-1">Responsable</div>
                <input
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                  type="text"
                  defaultValue={monthlyClose.responsible_name || ""}
                  onBlur={(e) => closeMutation.mutate({ responsible_name: e.target.value })}
                />
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">Notas del cierre</div>
                <textarea
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                  rows={3}
                  defaultValue={monthlyClose.notes || ""}
                  onBlur={(e) => closeMutation.mutate({ notes: e.target.value })}
                />
              </div>
            </div>
            <div className="text-sm text-muted-foreground">
              Marca los checks para evitar las decisiones de riesgo más comunes.
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {[
                {
                  key: "reviewed_numbers",
                  label: "Revisar ingresos, gastos y cashflow del mes",
                },
                {
                  key: "reviewed_margin",
                  label: "Margen claro por cliente y global",
                },
                {
                  key: "reviewed_cash_buffer",
                  label: "Colchón de caja (≥ 3 meses)",
                },
                {
                  key: "reviewed_reinvestment",
                  label: "Plan de reinversión con ROI (captación/retención)",
                },
                {
                  key: "reviewed_debt",
                  label: "Líneas de crédito y deuda bajo control",
                },
                {
                  key: "reviewed_taxes",
                  label: "Impuestos y obligaciones fiscales al día",
                },
                {
                  key: "reviewed_personal",
                  label: "Nóminas y pagos personales revisados",
                },
              ].map((item) => (
                <label key={item.key} className="flex items-start gap-2 rounded-lg border border-border p-3">
                  <input
                    type="checkbox"
                    checked={Boolean((monthlyClose as any)[item.key])}
                    onChange={(e) => closeMutation.mutate({ [item.key]: e.target.checked })}
                    className="mt-1"
                  />
                  <span className="text-sm">{item.label}</span>
                </label>
              ))}
            </div>
            <div className="flex items-center justify-between">
              <div className="text-xs text-muted-foreground">
                {closeDoneCount} de {closeTotalCount} completados
              </div>
              <Button
                variant="outline"
                onClick={() => closeMutation.mutate({
                  reviewed_numbers: true,
                  reviewed_margin: true,
                  reviewed_cash_buffer: true,
                  reviewed_reinvestment: true,
                  reviewed_debt: true,
                  reviewed_taxes: true,
                  reviewed_personal: true,
                })}
                disabled={closeMutation.isPending}
              >
                Marcar cierre completo
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Profitability (admin only) */}
      {isAdmin && profitability && profitability.clients.length > 0 && (
        <div className="grid lg:grid-cols-2 gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Rentabilidad por cliente</CardTitle>
            </CardHeader>
            <CardContent className="pt-4">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Cliente</TableHead>
                    <TableHead>Presupuesto</TableHead>
                    <TableHead>Coste</TableHead>
                    <TableHead>Estimado</TableHead>
                    <TableHead>Real</TableHead>
                    <TableHead>Δ</TableHead>
                    <TableHead>Margen</TableHead>
                    <TableHead>Estado</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {profitability.clients.map((c) => (
                    <TableRow key={c.client_id}>
                      <TableCell className="font-medium">{c.client_name}</TableCell>
                      <TableCell className="mono">{c.budget.toLocaleString("es-ES")}€</TableCell>
                      <TableCell className="mono">{c.cost.toLocaleString("es-ES")}€</TableCell>
                      <TableCell className="mono">{Math.round((c.estimated_minutes || 0) / 60)}h</TableCell>
                      <TableCell className="mono">{Math.round((c.actual_minutes || 0) / 60)}h</TableCell>
                      <TableCell className="mono">{Math.round((c.variance_minutes || 0) / 60)}h</TableCell>
                      <TableCell className="mono">{c.margin.toLocaleString("es-ES")}€ ({c.margin_percent}%)</TableCell>
                      <TableCell>{profitBadge(c.status)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Presupuesto vs Coste</CardTitle>
            </CardHeader>
            <CardContent className="pt-4">
              <ProfitabilityChart data={profitability.clients} />
            </CardContent>
          </Card>
        </div>
      )}

      {/* Team Summary (admin only) */}
      {isAdmin && team && team.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Resumen del equipo</CardTitle>
          </CardHeader>
          <CardContent className="pt-4">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Miembro</TableHead>
                  <TableHead>Tarifa/h</TableHead>
                  <TableHead>Horas mes</TableHead>
                  <TableHead>Coste</TableHead>
                  <TableHead>Tareas</TableHead>
                  <TableHead>Clientes</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {team.map((m) => (
                  <TableRow key={m.user_id}>
                    <TableCell className="font-medium">{m.full_name}</TableCell>
                    <TableCell className="mono">{m.hourly_rate != null ? `${m.hourly_rate}€` : "-"}</TableCell>
                    <TableCell className="mono">{m.hours_this_month}h</TableCell>
                    <TableCell className="mono">{m.cost.toLocaleString("es-ES")}€</TableCell>
                    <TableCell className="mono">{m.task_count}</TableCell>
                    <TableCell className="mono">{m.clients_touched}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Discord Section (admin only) */}
      {isAdmin && (
        <Card>
          <CardHeader>
            <CardTitle>Resumen Diario</CardTitle>
          </CardHeader>
          <CardContent className="pt-4">
            <div className="flex gap-2">
              <Button variant="outline" onClick={handlePreview}>
                <Eye className="h-4 w-4 mr-2" /> Vista previa
              </Button>
              <Button onClick={() => sendMutation.mutate()} disabled={sendMutation.isPending}>
                <Send className="h-4 w-4 mr-2" /> Enviar a Discord
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Discord Preview Dialog */}
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogHeader>
          <DialogTitle>Vista previa — Discord</DialogTitle>
        </DialogHeader>
        <div className="bg-surface border border-brand/10 p-4 whitespace-pre-wrap text-sm font-mono text-foreground">
          {preview?.summary || "Cargando..."}
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <Button variant="outline" onClick={() => setPreviewOpen(false)}>Cerrar</Button>
          <Button onClick={() => { sendMutation.mutate(); setPreviewOpen(false) }} disabled={sendMutation.isPending}>
            <Send className="h-4 w-4 mr-2" /> Enviar
          </Button>
        </div>
      </Dialog>
    </div>
  )
}
