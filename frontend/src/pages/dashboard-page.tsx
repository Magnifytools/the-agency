import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { dashboardApi, discordApi, tasksApi, timeEntriesApi, timerApi, usersApi, dailysApi, digestsApi, clientsApi, leadsApi, proposalsApi, engineApi } from "@/lib/api"
import type { PricingOption } from "@/lib/types"
import { useAuth } from "@/context/auth-context"
import { MetricCard } from "@/components/dashboard/metric-card"
import { ProfitabilityChart } from "@/components/dashboard/profitability-chart"
import { InsightsPanel } from "@/components/pm/insights-panel"
import { DailyBriefingButton } from "@/components/pm/daily-briefing"
import { OverdueTasks } from "@/components/dashboard/overdue-tasks"
import { DigestTracker } from "@/components/dashboard/digest-tracker"
import { EngineAlertsWidget } from "@/components/dashboard/engine-alerts-widget"
import { LeadFollowups } from "@/components/dashboard/lead-followups"
import { MonthlyCloseChecklist } from "@/components/dashboard/monthly-close-checklist"
import { TeamSummaryTable } from "@/components/dashboard/team-summary-table"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Select } from "@/components/ui/select"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { InfoTooltip } from "@/components/ui/tooltip"
import { Users, CheckSquare, Clock, DollarSign, Send, Eye, FileText, ExternalLink, Play, Square, Check, UserCog, AlertTriangle, MessageSquare } from "lucide-react"
import { toast } from "sonner"
import { Link } from "react-router-dom"
import { InboxWidget } from "@/components/dashboard/inbox-widget"
import { DailyUpdateWidget } from "@/components/dashboard/daily-update-widget"
import { DeberesWidget } from "@/components/dashboard/deberes-widget"
import { getErrorMessage } from "@/lib/utils"
import { SkeletonCard } from "@/components/ui/skeleton"

const MONTHS = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

function profitBadge(status: string) {
  const map: Record<string, { label: string; variant: "success" | "warning" | "destructive" | "secondary" }> = {
    profitable: { label: "Rentable", variant: "success" },
    at_risk: { label: "En riesgo", variant: "warning" },
    unprofitable: { label: "No rentable", variant: "destructive" },
  }
  const { label, variant } = map[status] || { label: status, variant: "secondary" }
  return <Badge variant={variant}>{label}</Badge>
}

export default function DashboardPage() {
  const { user } = useAuth()
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [viewAsUserId, setViewAsUserId] = useState<number | null>(null)
  const queryClient = useQueryClient()

  const params = { year, month }
  const isAdmin = user?.role === "admin"

  // ─── Shared queries ─────────────────────────────────────────
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
  const { data: engineConfig } = useQuery({
    queryKey: ["engine-config"],
    queryFn: () => engineApi.getConfig(),
    staleTime: 10 * 60_000,
  })
  const { data: leadReminders } = useQuery({
    queryKey: ["lead-reminders"],
    queryFn: () => leadsApi.reminders(),
    enabled: !!user,
  })
  const { data: allProposals } = useQuery({
    queryKey: ["proposals-pipeline"],
    queryFn: () => proposalsApi.list(),
    enabled: !!user,
  })

  // ─── Worker queries ─────────────────────────────────────────
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
  const { data: activeTimer } = useQuery({
    queryKey: ["active-timer"],
    queryFn: () => timerApi.active(),
    enabled: !!user && user.role === "member",
    refetchInterval: 30_000,
  })
  const today = new Date().toISOString().slice(0, 10)
  const { data: todayDailys } = useQuery({
    queryKey: ["daily-today", user?.id, today],
    queryFn: () => dailysApi.list({ user_id: user!.id, date_from: today, date_to: today, limit: 1 }),
    enabled: !!user && user.role === "member",
  })
  const todayDaily = todayDailys?.[0]
  const showDailyReminder = !todayDaily && now.getHours() >= 17

  // ─── Admin queries ──────────────────────────────────────────
  const { data: allOverdueTasks } = useQuery({
    queryKey: ["all-overdue-tasks"],
    queryFn: () => tasksApi.listAll({ overdue: true }),
    enabled: !!user && user.role === "admin",
  })
  const { data: allUsers } = useQuery({
    queryKey: ["users-all"],
    queryFn: () => usersApi.listAll(),
    enabled: isAdmin,
  })
  const memberUsers = (allUsers || []).filter((u) => u.role === "member")
  const { data: viewAsInProgress } = useQuery({
    queryKey: ["viewas-tasks-in-progress", viewAsUserId],
    queryFn: () => tasksApi.listAll({ assigned_to: viewAsUserId!, status: "in_progress" }),
    enabled: isAdmin && !!viewAsUserId,
  })
  const { data: viewAsPending } = useQuery({
    queryKey: ["viewas-tasks-pending", viewAsUserId],
    queryFn: () => tasksApi.listAll({ assigned_to: viewAsUserId!, status: "pending" }),
    enabled: isAdmin && !!viewAsUserId,
  })
  const { data: viewAsOverdue } = useQuery({
    queryKey: ["viewas-tasks-overdue", viewAsUserId],
    queryFn: () => tasksApi.listAll({ assigned_to: viewAsUserId!, overdue: true }),
    enabled: isAdmin && !!viewAsUserId,
  })
  const { data: viewAsWeekly } = useQuery({
    queryKey: ["weekly-timesheet-viewas"],
    queryFn: () => timeEntriesApi.weekly(),
    enabled: isAdmin && !!viewAsUserId,
  })
  const viewAsUser = memberUsers.find((u) => u.id === viewAsUserId)
  const { data: preview, refetch: fetchPreview } = useQuery({
    queryKey: ["discord-preview"],
    queryFn: () => discordApi.preview(),
    enabled: false,
  })

  // ─── Mutations ──────────────────────────────────────────────
  const sendMutation = useMutation({
    mutationFn: () => discordApi.send(),
    onSuccess: () => toast.success("Resumen enviado a Discord"),
    onError: (err) => toast.error(getErrorMessage(err, "Error al enviar a Discord")),
  })
  const closeMutation = useMutation({
    mutationFn: (payload: Record<string, boolean | string>) => dashboardApi.updateMonthlyClose(payload, params),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["dashboard-monthly-close", year, month] }),
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar el cierre")),
  })
  const financialMutation = useMutation({
    mutationFn: (payload: Record<string, number>) => dashboardApi.updateFinancialSettings(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["dashboard-financial-settings"] }),
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar los guardarraíles")),
  })
  const markDoneMutation = useMutation({
    mutationFn: (taskId: number) => tasksApi.update(taskId, { status: "completed" }),
    onSuccess: () => {
      toast.success("Tarea completada")
      queryClient.invalidateQueries({ queryKey: ["my-tasks-in-progress", user?.id] })
      queryClient.invalidateQueries({ queryKey: ["my-tasks-pending", user?.id] })
      queryClient.invalidateQueries({ queryKey: ["my-tasks-overdue", user?.id] })
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al completar la tarea")),
  })
  const startTimerMutation = useMutation({
    mutationFn: (taskId: number) => timerApi.start({ task_id: taskId }),
    onSuccess: () => {
      toast.success("Timer iniciado")
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al iniciar el timer")),
  })
  const stopTimerMutation = useMutation({
    mutationFn: () => timerApi.stop(),
    onSuccess: () => {
      toast.success("Timer parado")
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al parar el timer")),
  })

  // ─── Computed ───────────────────────────────────────────────
  const getMondayOfWeek = (d: Date) => {
    const day = d.getDay()
    const diff = d.getDate() - day + (day === 0 ? -6 : 1)
    return new Date(d.getFullYear(), d.getMonth(), diff).toISOString().slice(0, 10)
  }
  const thisMonday = getMondayOfWeek(new Date())
  const clientsWithDigestThisWeek = new Set(
    (recentDigests || [])
      .filter((d) => d.period_start >= thisMonday || d.created_at >= thisMonday)
      .map((d) => d.client_id)
  )
  const clientsMissingDigest = (allClients || []).filter((c) => !clientsWithDigestThisWeek.has(c.id))

  const proposalStats = (() => {
    if (!allProposals) return null
    const drafts = allProposals.filter((p) => p.status === "draft")
    const sent = allProposals.filter((p) => p.status === "sent")
    const accepted = allProposals.filter((p) => p.status === "accepted")
    const pipelineValue = sent.reduce((sum, p) => {
      const maxPrice = (p.pricing_options || []).reduce((max: number, opt: PricingOption) => Math.max(max, opt.price || 0), 0)
      return sum + maxPrice
    }, 0)
    return { drafts: drafts.length, sent: sent.length, accepted: accepted.length, total: allProposals.length, pipelineValue }
  })()

  const closeKeys = ["reviewed_numbers", "reviewed_margin", "reviewed_cash_buffer", "reviewed_reinvestment", "reviewed_debt", "reviewed_taxes", "reviewed_personal"]
  const closeDoneCount = monthlyClose ? closeKeys.filter((key) => Boolean(monthlyClose[key as keyof typeof monthlyClose])).length : 0
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
    creditUtilization >= creditAlertPct ? { title: "Uso alto de línea de crédito", description: `La línea está al ${creditUtilization}%, supera el umbral ${creditAlertPct}%.` } : null,
    monthlyCost > 0 && taxReserve < monthlyCost * (taxReserveTargetPct / 100) ? { title: "Fondo de impuestos bajo", description: "El fondo reservado parece insuficiente para costes actuales." } : null,
  ].filter(Boolean) as { title: string; description: string }[]

  const handlePreview = async () => { await fetchPreview(); setPreviewOpen(true) }
  const handleExportClose = async () => {
    const blob = await dashboardApi.exportMonthlyClose({ year, month })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = `cierre-mensual-${year}-${String(month).padStart(2, "0")}.csv`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold uppercase tracking-wide">Dashboard</h2>
          {overview && (
            <p className="text-sm text-muted-foreground mt-1">
              {MONTHS[month - 1]}: {overview.pending_tasks + overview.in_progress_tasks} tareas activas, {overview.active_clients} clientes
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <DailyBriefingButton />
          {isAdmin && memberUsers.length > 0 && (
            <Select
              value={viewAsUserId ?? ""}
              onChange={(e) => setViewAsUserId(e.target.value ? Number(e.target.value) : null)}
              className="w-44"
            >
              <option value="">Ver dashboard de...</option>
              {memberUsers.map((u) => (
                <option key={u.id} value={u.id}>{u.full_name}</option>
              ))}
            </Select>
          )}
          <Select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="w-40">
            {MONTHS.map((m, i) => (<option key={i} value={i + 1}>{m}</option>))}
          </Select>
          <Select value={year} onChange={(e) => setYear(Number(e.target.value))} className="w-24">
            {[now.getFullYear() - 1, now.getFullYear(), now.getFullYear() + 1].map((y) => (<option key={y} value={y}>{y}</option>))}
          </Select>
        </div>
      </div>

      {/* Worker Dashboard */}
      {!isAdmin && user && (
        <div className="space-y-4">

          {/* Overdue banner — always at top, impossible to ignore */}
          {myOverdueTasks && myOverdueTasks.length > 0 && (
            <div className="flex items-center gap-4 bg-red-500/10 border border-red-500/40 rounded-xl px-5 py-4">
              <div className="flex items-center justify-center w-10 h-10 rounded-full bg-red-500/20 flex-shrink-0">
                <span className="text-red-400 font-bold text-lg">{myOverdueTasks.length}</span>
              </div>
              <div className="flex-1">
                <p className="text-sm font-semibold text-red-400">
                  {myOverdueTasks.length === 1 ? "Tienes 1 tarea vencida" : `Tienes ${myOverdueTasks.length} tareas vencidas`}
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {myOverdueTasks.slice(0, 2).map((t) => t.title).join(" · ")}
                  {myOverdueTasks.length > 2 ? ` · +${myOverdueTasks.length - 2} más` : ""}
                </p>
              </div>
              <Link to="/tasks" className="text-xs text-red-400 hover:underline flex-shrink-0">Ver todas →</Link>
            </div>
          )}

          {/* Daily reminder banner after 17:00 */}
          {showDailyReminder && (
            <div className="flex items-center gap-4 bg-amber-500/10 border border-amber-500/40 rounded-xl px-5 py-4">
              <MessageSquare className="h-5 w-5 text-amber-400 flex-shrink-0" />
              <div className="flex-1">
                <p className="text-sm font-semibold text-amber-400">Aún no has enviado el daily de hoy</p>
                <p className="text-xs text-muted-foreground mt-0.5">Antes de cerrar, cuéntale al equipo qué has hecho</p>
              </div>
            </div>
          )}

          {/* Active timer */}
          {activeTimer && (
            <Card className="border-brand/30 bg-brand/5">
              <CardContent className="pt-4 pb-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-2 h-2 rounded-full bg-brand animate-pulse" />
                    <div>
                      <p className="text-sm font-medium text-brand">Timer activo</p>
                      <p className="text-xs text-muted-foreground">
                        {activeTimer.task_title || "Sin tarea asignada"}
                        {activeTimer.client_name ? ` · ${activeTimer.client_name}` : ""}
                      </p>
                    </div>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => stopTimerMutation.mutate()}
                    disabled={stopTimerMutation.isPending}
                  >
                    <Square className="h-3 w-3 mr-1.5" />
                    Parar
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {weeklyTimesheet && (() => {
            const myRow = weeklyTimesheet.users.find((u: { user_id: number; total_minutes: number }) => u.user_id === user.id)
            const totalHours = myRow ? Math.round(myRow.total_minutes / 60 * 10) / 10 : 0
            return (
              <div className="grid grid-cols-2 gap-4">
                <MetricCard icon={Clock} label="Mis horas esta semana" value={`${totalHours}h`} tooltip="Horas registradas esta semana (lunes a hoy)." />
                <MetricCard icon={CheckSquare} label="Tareas en curso" value={myInProgressTasks?.length ?? 0} subtitle={`${myPendingTasks?.length ?? 0} pendientes`} tooltip="Tareas asignadas a ti con estado 'en curso'." />
              </div>
            )
          })()}

          <DailyUpdateWidget userId={user.id} />
          <DeberesWidget userId={user.id} />

          {/* Las 3 de hoy — tareas en curso como tarjetas visuales */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">En curso hoy</p>
              {myInProgressTasks && myInProgressTasks.length > 3 && (
                <p className="text-xs text-amber-400 flex items-center gap-1">
                  <AlertTriangle className="h-3 w-3" />
                  {myInProgressTasks.length} tareas activas — enfócate en menos
                </p>
              )}
            </div>
            {myInProgressTasks && myInProgressTasks.length > 0 ? (
              <div className="space-y-2">
                {myInProgressTasks.slice(0, 5).map((t) => (
                  <div
                    key={t.id}
                    className="flex items-center gap-3 bg-card border border-border rounded-xl px-4 py-3 hover:border-brand/30 transition-colors"
                  >
                    <button
                      onClick={() => markDoneMutation.mutate(t.id)}
                      disabled={markDoneMutation.isPending}
                      className="group w-5 h-5 rounded-full border-2 border-border hover:border-green-400 hover:bg-green-400/10 flex items-center justify-center flex-shrink-0 transition-colors"
                      title="Marcar como completada"
                    >
                      <Check className="h-3 w-3 text-transparent group-hover:text-green-400 transition-colors" />
                    </button>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{t.title}</p>
                      {t.client_name && <p className="text-xs text-muted-foreground">{t.client_name}</p>}
                    </div>
                    {t.due_date && (
                      <span className={`text-xs mono flex-shrink-0 ${new Date(t.due_date) < now ? "text-red-400" : "text-muted-foreground"}`}>
                        {new Date(t.due_date).toLocaleDateString("es-ES", { day: "numeric", month: "short" })}
                      </span>
                    )}
                    {activeTimer?.task_id === t.id ? (
                      <span className="text-brand text-xs font-medium flex items-center gap-1 flex-shrink-0">
                        <span className="w-1.5 h-1.5 rounded-full bg-brand animate-pulse" />timer
                      </span>
                    ) : (
                      <button
                        onClick={() => startTimerMutation.mutate(t.id)}
                        disabled={startTimerMutation.isPending || !!activeTimer}
                        className="p-1.5 text-muted-foreground hover:text-brand hover:bg-brand/10 rounded-lg transition-colors disabled:opacity-40 flex-shrink-0"
                        title="Iniciar timer"
                      >
                        <Play className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="border border-dashed border-border rounded-xl p-5 text-center">
                <p className="text-sm text-muted-foreground">Sin tareas en curso</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Ve a <Link to="/tasks" className="text-brand hover:underline">Tareas</Link> y pon en curso las de hoy
                </p>
              </div>
            )}
          </div>

          {/* Pendientes — lista compacta */}
          {myPendingTasks && myPendingTasks.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Pendientes ({myPendingTasks.length})
              </p>
              <div className="space-y-1">
                {myPendingTasks.slice(0, 8).map((t) => (
                  <div key={t.id} className="flex items-center gap-3 px-4 py-2.5 rounded-lg hover:bg-muted/50 transition-colors group">
                    <div className="w-1.5 h-1.5 rounded-full bg-muted-foreground/40 flex-shrink-0" />
                    <span className="text-sm flex-1 truncate">{t.title}</span>
                    {t.client_name && <span className="text-xs text-muted-foreground hidden group-hover:block">{t.client_name}</span>}
                    {t.due_date && (
                      <span className={`text-xs mono flex-shrink-0 ${new Date(t.due_date) < now ? "text-red-400" : "text-muted-foreground"}`}>
                        {new Date(t.due_date).toLocaleDateString("es-ES", { day: "numeric", month: "short" })}
                      </span>
                    )}
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                      <button
                        onClick={() => startTimerMutation.mutate(t.id)}
                        disabled={startTimerMutation.isPending || !!activeTimer}
                        className="p-1 text-muted-foreground hover:text-brand rounded transition-colors disabled:opacity-40"
                        title="Iniciar timer"
                      >
                        <Play className="h-3 w-3" />
                      </button>
                      <button
                        onClick={() => markDoneMutation.mutate(t.id)}
                        disabled={markDoneMutation.isPending}
                        className="p-1 text-muted-foreground hover:text-green-400 rounded transition-colors"
                        title="Marcar como completada"
                      >
                        <Check className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                ))}
                {myPendingTasks.length > 8 && (
                  <Link to="/tasks" className="block text-xs text-muted-foreground hover:text-brand px-4 py-1.5">
                    +{myPendingTasks.length - 8} más en Tareas →
                  </Link>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Admin: view as member */}
      {isAdmin && viewAsUserId && viewAsUser && (
        <div className="space-y-6 border border-brand/20 rounded-xl p-5 bg-brand/5">
          <div className="flex items-center gap-2">
            <UserCog className="h-4 w-4 text-brand" />
            <span className="text-sm font-semibold text-brand">Vista de {viewAsUser.full_name}</span>
            <span className="text-xs text-muted-foreground ml-auto">solo lectura</span>
          </div>
          {viewAsWeekly && (() => {
            const row = viewAsWeekly.users.find((u: { user_id: number; total_minutes: number }) => u.user_id === viewAsUserId)
            const hours = row ? Math.round(row.total_minutes / 60 * 10) / 10 : 0
            return (
              <div className="grid grid-cols-2 gap-4">
                <MetricCard icon={Clock} label="Horas esta semana" value={`${hours}h`} tooltip="Horas de esta semana." />
                <MetricCard icon={CheckSquare} label="Tareas en curso" value={viewAsInProgress?.length ?? 0} subtitle={`${viewAsPending?.length ?? 0} pendientes`} tooltip="Tareas en curso." />
              </div>
            )
          })()}
          <DailyUpdateWidget userId={viewAsUserId} readOnly />
          <DeberesWidget userId={viewAsUserId} />
          {viewAsOverdue && viewAsOverdue.length > 0 && (
            <OverdueTasks tasks={viewAsOverdue} title={`Tareas vencidas (${viewAsOverdue.length})`} />
          )}
          {viewAsInProgress && viewAsInProgress.length > 0 && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">Tareas en curso</CardTitle></CardHeader>
              <CardContent>
                <Table>
                  <TableHeader><TableRow><TableHead>Tarea</TableHead><TableHead>Cliente</TableHead><TableHead>Fecha límite</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {viewAsInProgress.map((t) => (
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
          {viewAsPending && viewAsPending.length > 0 && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">Tareas pendientes</CardTitle></CardHeader>
              <CardContent>
                <Table>
                  <TableHeader><TableRow><TableHead>Tarea</TableHead><TableHead>Cliente</TableHead><TableHead>Fecha límite</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {viewAsPending.map((t) => (
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
        <Card><CardContent className="pt-6"><div className="text-sm font-medium">Recordatorio de cierre mensual</div><div className="text-xs text-muted-foreground mt-1">Estamos a partir del día {closeDay}. Completa el cierre mensual para evitar decisiones con datos incompletos.</div></CardContent></Card>
      )}

      {/* Metric Cards & Inbox */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          {overview ? (
            <div className="grid grid-cols-2 gap-4">
              <MetricCard icon={Users} label="Clientes activos" value={overview.active_clients} tooltip="Clientes con estado 'activo'." />
              <MetricCard icon={CheckSquare} label="Tareas pendientes" value={overview.pending_tasks + overview.in_progress_tasks} subtitle={`${overview.in_progress_tasks} en curso`} tooltip="Tareas 'pendiente' + 'en curso' del mes." />
              <MetricCard icon={Clock} label="Horas mes" value={`${overview.hours_this_month}h`} tooltip="Total horas registradas del equipo." />
              <MetricCard icon={DollarSign} label="Presupuesto total" value={`${overview.total_budget.toLocaleString("es-ES")}€`} subtitle={`Coste: ${overview.total_cost.toLocaleString("es-ES")}€`} tooltip="Suma de presupuestos mensuales de clientes activos." />
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4">
              {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
            </div>
          )}
        </div>
        <div className="lg:col-span-1 h-[250px]"><InboxWidget /></div>
      </div>

      <InsightsPanel />

      {isAdmin && allOverdueTasks && allOverdueTasks.length > 0 && <OverdueTasks tasks={allOverdueTasks} showAssigned />}
      <DigestTracker clientsMissing={clientsMissingDigest} />
      <EngineAlertsWidget clients={allClients || []} />
      {leadReminders && <LeadFollowups reminders={leadReminders} />}

      {/* Proposals pipeline */}
      {proposalStats && proposalStats.total > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-2"><FileText className="w-4 h-4 text-brand" />Pipeline de propuestas</CardTitle>
              <Link to="/proposals"><Button variant="outline" size="sm">Ver propuestas</Button></Link>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-6">
              <div className="text-center"><div className="text-2xl font-bold">{proposalStats.drafts}</div><div className="text-xs text-muted-foreground">Borradores</div></div>
              <div className="text-center"><div className="text-2xl font-bold text-blue-400">{proposalStats.sent}</div><div className="text-xs text-muted-foreground">Enviadas</div></div>
              <div className="text-center"><div className="text-2xl font-bold text-green-400">{proposalStats.accepted}</div><div className="text-xs text-muted-foreground">Aceptadas</div></div>
              {proposalStats.pipelineValue > 0 && (
                <div className="ml-auto text-right"><div className="text-2xl font-bold text-brand">{proposalStats.pipelineValue.toLocaleString("es-ES")}€</div><div className="text-xs text-muted-foreground">Valor pipeline (enviadas)</div></div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {financialAlerts.length > 0 && isAdmin && (
        <Card className="border-warning/50 bg-warning/5">
          <CardHeader className="pb-2"><CardTitle className="text-warning text-sm">Alertas financieras</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {financialAlerts.map((alert, i) => (<div key={i} className="flex flex-col"><span className="text-sm font-medium">{alert.title}</span><span className="text-xs text-muted-foreground">{alert.description}</span></div>))}
          </CardContent>
        </Card>
      )}

      {financialSettings && isAdmin && (
        <details className="group border border-border rounded-xl bg-card">
          <summary className="flex cursor-pointer items-center justify-between p-4 font-medium marker:content-none hover:bg-muted/50 transition-colors rounded-xl">
            Configuración Financiera
            <svg className="h-5 w-5 text-muted-foreground transition-transform group-open:rotate-180" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
          </summary>
          <div className="p-4 pt-0 border-t border-border mt-2 space-y-4">
            <div className="grid gap-4 md:grid-cols-3">
              <div><div className="text-xs text-muted-foreground mb-1">Fondo impuestos (€)</div><input className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm" type="number" step="0.01" defaultValue={financialSettings.tax_reserve} onBlur={(e) => financialMutation.mutate({ tax_reserve: Number(e.target.value) })} /></div>
              <div><div className="text-xs text-muted-foreground mb-1">Línea crédito total (€)</div><input className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm" type="number" step="0.01" defaultValue={financialSettings.credit_limit} onBlur={(e) => financialMutation.mutate({ credit_limit: Number(e.target.value) })} /></div>
              <div><div className="text-xs text-muted-foreground mb-1">Crédito utilizado (€)</div><input className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm" type="number" step="0.01" defaultValue={financialSettings.credit_used} onBlur={(e) => financialMutation.mutate({ credit_used: Number(e.target.value) })} /><div className="text-xs text-muted-foreground mt-1">Uso: {financialSettings.credit_utilization}% (alerta {financialSettings.credit_alert_pct}%)</div></div>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div><div className="text-xs text-muted-foreground mb-1">Día récord. cierre</div><input className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm" type="number" min="1" max="28" step="1" defaultValue={financialSettings.monthly_close_day} onBlur={(e) => financialMutation.mutate({ monthly_close_day: Number(e.target.value) })} /></div>
              <div><div className="text-xs text-muted-foreground mb-1">Alerta crédito (%)</div><input className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm" type="number" min="0" max="100" step="1" defaultValue={financialSettings.credit_alert_pct} onBlur={(e) => financialMutation.mutate({ credit_alert_pct: Number(e.target.value) })} /></div>
              <div><div className="text-xs text-muted-foreground mb-1">Cob. impuestos (%)</div><input className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm" type="number" min="0" max="200" step="1" defaultValue={financialSettings.tax_reserve_target_pct} onBlur={(e) => financialMutation.mutate({ tax_reserve_target_pct: Number(e.target.value) })} /></div>
            </div>
          </div>
        </details>
      )}

      {monthlyClose && <MonthlyCloseChecklist monthlyClose={monthlyClose as unknown as Record<string, string | boolean | null>} onUpdate={(p) => closeMutation.mutate(p)} onExport={handleExportClose} isPending={closeMutation.isPending} />}

      {isAdmin && profitability && profitability.clients.length > 0 && (
        <div className="grid lg:grid-cols-2 gap-6">
          <Card>
            <CardHeader><CardTitle>Rentabilidad por cliente</CardTitle></CardHeader>
            <CardContent className="pt-4">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Cliente</TableHead>
                    <TableHead><span className="inline-flex items-center gap-1">Presupuesto <InfoTooltip content="Fee mensual del cliente" /></span></TableHead>
                    <TableHead><span className="inline-flex items-center gap-1">Coste <InfoTooltip content="Horas trabajadas × tarifa/hora" /></span></TableHead>
                    <TableHead><span className="inline-flex items-center gap-1">Estimado <InfoTooltip content="Horas estimadas en las tareas" /></span></TableHead>
                    <TableHead><span className="inline-flex items-center gap-1">Real <InfoTooltip content="Horas realmente registradas" /></span></TableHead>
                    <TableHead><span className="inline-flex items-center gap-1">Δ <InfoTooltip content="Diferencia real − estimado" /></span></TableHead>
                    <TableHead><span className="inline-flex items-center gap-1">Margen <InfoTooltip content="Presupuesto − Coste" /></span></TableHead>
                    <TableHead>Estado</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {profitability.clients.map((c) => {
                    const linkedClient = (allClients || []).find((cl) => cl.id === c.client_id)
                    const enginePid = linkedClient?.engine_project_id
                    return (
                    <TableRow key={c.client_id}>
                      <TableCell className="font-medium">
                        <span className="flex items-center gap-1.5">
                          {c.client_name}
                          {enginePid && engineConfig?.engine_frontend_url && (
                            <a
                              href={`${engineConfig.engine_frontend_url}/p/${enginePid}/dashboard`}
                              target="_blank"
                              rel="noopener noreferrer"
                              title="Abrir en Engine"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <ExternalLink className="h-3.5 w-3.5 text-muted-foreground hover:text-brand" />
                            </a>
                          )}
                        </span>
                      </TableCell>
                      <TableCell className="mono">{c.budget.toLocaleString("es-ES")}€</TableCell>
                      <TableCell className="mono">{c.cost.toLocaleString("es-ES")}€</TableCell>
                      <TableCell className="mono">{Math.round((c.estimated_minutes || 0) / 60)}h</TableCell>
                      <TableCell className="mono">{Math.round((c.actual_minutes || 0) / 60)}h</TableCell>
                      <TableCell className="mono">{Math.round((c.variance_minutes || 0) / 60)}h</TableCell>
                      <TableCell className="mono">{c.margin.toLocaleString("es-ES")}€ ({c.margin_percent}%)</TableCell>
                      <TableCell>{profitBadge(c.status)}</TableCell>
                    </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Presupuesto vs Coste</CardTitle></CardHeader>
            <CardContent className="pt-4"><ProfitabilityChart data={profitability.clients} /></CardContent>
          </Card>
        </div>
      )}

      {isAdmin && team && <TeamSummaryTable team={team} />}

      {isAdmin && (
        <Card>
          <CardHeader><CardTitle>Resumen Diario</CardTitle></CardHeader>
          <CardContent className="pt-4">
            <div className="flex gap-2">
              <Button variant="outline" onClick={handlePreview}><Eye className="h-4 w-4 mr-2" /> Vista previa</Button>
              <Button onClick={() => sendMutation.mutate()} disabled={sendMutation.isPending}><Send className="h-4 w-4 mr-2" /> Enviar a Discord</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogHeader><DialogTitle>Vista previa — Discord</DialogTitle></DialogHeader>
        <div className="bg-surface border border-brand/10 p-4 whitespace-pre-wrap text-sm font-mono text-foreground">{preview?.summary || "Cargando..."}</div>
        <div className="flex justify-end gap-2 mt-4">
          <Button variant="outline" onClick={() => setPreviewOpen(false)}>Cerrar</Button>
          <Button onClick={() => { sendMutation.mutate(); setPreviewOpen(false) }} disabled={sendMutation.isPending}><Send className="h-4 w-4 mr-2" /> Enviar</Button>
        </div>
      </Dialog>
    </div>
  )
}
