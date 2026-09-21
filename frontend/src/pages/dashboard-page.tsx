import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { dashboardApi, discordApi, tasksApi, timeEntriesApi, timerApi, usersApi, clientsApi, leadsApi, proposalsApi, engineApi, holdedApi } from "@/lib/api"
import { dashboardKeys, holdedKeys, invalidateTaskChange, invalidateTimeChange, taskKeys, timeKeys } from "@/lib/query-keys"
import { profitabilityStatus } from "@/lib/profitability"
import { isEnabled } from "@/lib/hidden-modules"
import type { PricingOption, Task } from "@/lib/types"
import { useAuth } from "@/context/auth-context"
import { MetricCard } from "@/components/dashboard/metric-card"
import { OperationalOverview } from "@/components/dashboard/operational-overview"
import { ProfitabilityChart } from "@/components/dashboard/profitability-chart"
import { InsightsPanel } from "@/components/pm/insights-panel"
import { DailyBriefingButton } from "@/components/pm/daily-briefing"
import { deliveryToast, ManualDeliveryReceipts } from "@/components/delivery-receipts"
import { OverdueTasks } from "@/components/dashboard/overdue-tasks"
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
import { CheckSquare, Clock, DollarSign, Send, Eye, FileText, ExternalLink, Play, Square, Check, UserCog, AlertTriangle, ChevronLeft, ChevronRight, BarChart3 } from "lucide-react"
import { toast } from "sonner"
import { Link } from "react-router-dom"
import { InboxWidget } from "@/components/dashboard/inbox-widget"
import { DailyUpdateWidget } from "@/components/dashboard/daily-update-widget"
import { DeberesWidget } from "@/components/dashboard/deberes-widget"
import { TodayBlock } from "@/components/dashboard/today-block"
import { getErrorMessage } from "@/lib/utils"
import { formatCurrency } from "@/lib/format"
import { addCivilDays, formatCivilDate, parseCivilDate } from "@/lib/dates"
import { useBusinessDate } from "@/hooks/use-business-date"

const MONTHS = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

function profitBadge(status: string) {
  const { label, variant } = profitabilityStatus(status)
  return <Badge variant={variant}>{label}</Badge>
}

function isForbidden(error: unknown) {
  return typeof error === "object" && error !== null && "response" in error
    && (error as { response?: { status?: number } }).response?.status === 403
}

function completionAction(task: Task, actorId: number, isAdmin: boolean) {
  const requiresReview = !task.is_recurring
    && task.project_requires_task_review === true
    && !isAdmin
    && task.project_review_owner_id !== actorId

  return requiresReview
    ? { status: "in_review" as const, label: "Enviar a revisión" }
    : { status: "completed" as const, label: "Completar" }
}

export default function DashboardPage() {
  const { user, hasPermission } = useAuth()
  const todayStr = useBusinessDate()
  const businessNow = parseCivilDate(todayStr)
  const businessWeekday = businessNow.getDay()
  const thisMonday = addCivilDays(todayStr, businessWeekday === 0 ? -6 : 1 - businessWeekday)
  const [year, setYear] = useState(businessNow.getFullYear())
  const [month, setMonth] = useState(businessNow.getMonth() + 1)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [viewAsUserId, setViewAsUserId] = useState<number | null>(null)
  const queryClient = useQueryClient()

  const params = { year, month }
  const isAdmin = user?.role === "admin"
  const canWriteTasks = hasPermission("tasks", true)
  const canWriteTime = hasPermission("timesheet", true)
  const financeEnabled = isAdmin && isEnabled("finance")
  const dashboardPermissionSignature = user ? `${user.role}:${[...(user.permissions ?? [])].sort((left, right) => left.module.localeCompare(right.module)).map((permission) => `${permission.module}:${Number(permission.can_read)}:${Number(permission.can_write)}`).join(",")}:${Number(isEnabled("finance"))}` : ""
  const isCurrentMonth = year === businessNow.getFullYear() && month === businessNow.getMonth() + 1

  const goToPrevMonth = () => {
    if (month === 1) { setMonth(12); setYear(year - 1) }
    else setMonth(month - 1)
  }
  const goToNextMonth = () => {
    if (month === 12) { setMonth(1); setYear(year + 1) }
    else setMonth(month + 1)
  }
  const goToCurrentMonth = () => { setYear(businessNow.getFullYear()); setMonth(businessNow.getMonth() + 1) }

  // ─── Shared queries ─────────────────────────────────────────
  const overviewQuery = useQuery({
    queryKey: dashboardKeys.overview(year, month, user?.id, dashboardPermissionSignature),
    queryFn: () => dashboardApi.overview(params),
    enabled: !!user,
    retry: false,
  })
  const overview = overviewQuery.data
  const financialOverviewQuery = useQuery({
    queryKey: dashboardKeys.financialOverview(year, month, user?.id, dashboardPermissionSignature),
    queryFn: () => dashboardApi.financialOverview(params),
    enabled: financeEnabled,
    retry: false,
  })
  const { data: profitability, isError: profitabilityError, refetch: refetchProfitability } = useQuery({
    queryKey: dashboardKeys.profitability(year, month, user?.id, dashboardPermissionSignature),
    queryFn: () => dashboardApi.profitability(params),
    enabled: financeEnabled,
    retry: false,
  })
  const { data: team, isError: teamError, refetch: refetchTeam } = useQuery({
    queryKey: dashboardKeys.team(year, month, user?.id, dashboardPermissionSignature),
    queryFn: () => dashboardApi.team(params),
    enabled: isAdmin,
    retry: false,
  })
  const { data: monthlyClose, error: monthlyCloseFailure, isError: monthlyCloseError, refetch: refetchMonthlyClose } = useQuery({
    queryKey: dashboardKeys.monthlyClose(year, month, user?.id, dashboardPermissionSignature),
    queryFn: () => dashboardApi.monthlyClose(params),
    enabled: financeEnabled,
  })
  const { data: financialSettings, error: financialSettingsFailure, isError: financialSettingsError, refetch: refetchFinancialSettings } = useQuery({
    queryKey: dashboardKeys.financialSettings(user?.id, dashboardPermissionSignature),
    queryFn: () => dashboardApi.financialSettings(),
    enabled: financeEnabled,
  })
  const financialOverviewForbidden = isForbidden(financialOverviewQuery.error)
  const monthlyCloseForbidden = isForbidden(monthlyCloseFailure)
  const financialSettingsForbidden = isForbidden(financialSettingsFailure)
  const { data: allClients, isError: allClientsError, refetch: refetchClients } = useQuery({
    queryKey: ["dashboard", "clients-active", user?.id ?? "anonymous", dashboardPermissionSignature],
    queryFn: () => clientsApi.listAll("active"),
    enabled: !!user && hasPermission("clients") && isEnabled("clients"),
  })
  const { data: engineConfig } = useQuery({
    queryKey: ["dashboard", "engine-config", user?.id ?? "anonymous", dashboardPermissionSignature],
    queryFn: () => engineApi.getConfig(),
    staleTime: 10 * 60_000,
    enabled: !!user && isEnabled("engine"),
  })
  // `enabled` corta la petición de raíz cuando el módulo está oculto: su router
  // no está registrado, así que la llamada sería un 404 en cada carga del panel.
  const { data: leadReminders } = useQuery({
    queryKey: ["dashboard", "lead-reminders", user?.id ?? "anonymous", dashboardPermissionSignature],
    queryFn: () => leadsApi.reminders(),
    enabled: !!user && hasPermission("leads") && isEnabled("leads"),
  })
  const { data: allProposals } = useQuery({
    queryKey: ["dashboard", "proposals-pipeline", user?.id ?? "anonymous", dashboardPermissionSignature],
    queryFn: () => proposalsApi.list(),
    enabled: !!user && hasPermission("proposals") && isEnabled("proposals"),
  })

  // ─── Holded queries (admin only) ───────────────────────────
  const { data: holdedConfig } = useQuery({
    queryKey: [...holdedKeys.config(), user?.id ?? "anonymous", dashboardPermissionSignature],
    queryFn: holdedApi.config,
    staleTime: 5 * 60_000,
    retry: false,
    enabled: financeEnabled && isEnabled("holded"),
  })
  const holdedEnabled = financeEnabled && isEnabled("holded") && (holdedConfig?.api_key_configured ?? false)
  const lastHoldedSync = holdedConfig?.last_sync_invoices?.completed_at ?? null

  const { data: holdedDashboard } = useQuery({
    queryKey: [...holdedKeys.dashboard(), user?.id ?? "anonymous", dashboardPermissionSignature],
    queryFn: holdedApi.dashboard,
    staleTime: 5 * 60_000,
    enabled: holdedEnabled,
  })
  const overdueInvoices = holdedDashboard?.pending_invoices.filter((i) => i.status === "overdue") ?? []
  const overdueTotal = overdueInvoices.reduce((sum, i) => sum + i.total, 0)

  // ─── Utilization (admin) ────────────────────────────────────
  const { data: utilization, isError: utilizationError, refetch: refetchUtilization } = useQuery({
    queryKey: dashboardKeys.utilization(year, month, user?.id, dashboardPermissionSignature),
    queryFn: () => dashboardApi.utilization({ year, month }),
    enabled: isAdmin,
    retry: false,
  })

  // ─── Worker queries ─────────────────────────────────────────
  const { data: myInProgressTasks, isError: myInProgressError, refetch: refetchMyInProgress } = useQuery({
    queryKey: taskKeys.assigned("dashboard", user?.id, "in_progress"),
    queryFn: () => tasksApi.listAll({ assigned_to: user!.id, status: "in_progress" }),
    enabled: !!user && user.role === "member" && hasPermission("tasks") && isEnabled("tasks"),
  })
  const { data: myPendingTasks, isError: myPendingError, refetch: refetchMyPending } = useQuery({
    queryKey: taskKeys.assigned("dashboard", user?.id, "pending"),
    queryFn: () => tasksApi.listAll({ assigned_to: user!.id, status: "pending" }),
    enabled: !!user && user.role === "member" && hasPermission("tasks") && isEnabled("tasks"),
  })
  const { data: weeklyTimesheet, isError: weeklyTimesheetError, refetch: refetchWeeklyTimesheet } = useQuery({
    queryKey: timeKeys.week(`dashboard:${user?.id ?? "anonymous"}:${thisMonday}`),
    queryFn: () => timeEntriesApi.weekly(thisMonday),
    enabled: !!user && user.role === "member" && hasPermission("timesheet") && isEnabled("timesheet"),
  })
  const activeTimerQuery = useQuery({
    queryKey: ["active-timer"],
    queryFn: () => timerApi.active(),
    enabled: !!user && user.role === "member" && hasPermission("tasks") && canWriteTime && isEnabled("tasks"),
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  })
  const activeTimer = activeTimerQuery.isError ? undefined : activeTimerQuery.data
  const timerUnknown = activeTimerQuery.isLoading || activeTimerQuery.isError
  // ─── Admin queries ──────────────────────────────────────────
  const { data: allOverdueTasks } = useQuery({
    queryKey: taskKeys.assigned("dashboard", "all", "overdue"),
    queryFn: () => tasksApi.listAll({ overdue: true }),
    enabled: !!user && user.role === "admin" && hasPermission("tasks") && isEnabled("tasks"),
  })
  const { data: allUsers } = useQuery({
    queryKey: ["dashboard", "users", user?.id ?? "anonymous", dashboardPermissionSignature],
    queryFn: () => usersApi.listAll(),
    enabled: isAdmin && isEnabled("users"),
  })
  const memberUsers = (allUsers || []).filter((u) => u.role === "member")
  const { data: viewAsInProgress, isError: viewAsInProgressError, refetch: refetchViewAsInProgress } = useQuery({
    queryKey: taskKeys.assigned("dashboard-view-as", viewAsUserId, "in_progress"),
    queryFn: () => tasksApi.listAll({ assigned_to: viewAsUserId!, status: "in_progress" }),
    enabled: isAdmin && !!viewAsUserId && hasPermission("tasks") && isEnabled("tasks"),
  })
  const { data: viewAsPending, isError: viewAsPendingError, refetch: refetchViewAsPending } = useQuery({
    queryKey: taskKeys.assigned("dashboard-view-as", viewAsUserId, "pending"),
    queryFn: () => tasksApi.listAll({ assigned_to: viewAsUserId!, status: "pending" }),
    enabled: isAdmin && !!viewAsUserId && hasPermission("tasks") && isEnabled("tasks"),
  })
  const { data: viewAsOverdue, isError: viewAsOverdueError, refetch: refetchViewAsOverdue } = useQuery({
    queryKey: taskKeys.assigned("dashboard-view-as", viewAsUserId, "overdue"),
    queryFn: () => tasksApi.listAll({ assigned_to: viewAsUserId!, overdue: true }),
    enabled: isAdmin && !!viewAsUserId && hasPermission("tasks") && isEnabled("tasks"),
  })
  const { data: viewAsWeekly, isError: viewAsWeeklyError, refetch: refetchViewAsWeekly } = useQuery({
    queryKey: timeKeys.week(`dashboard-view-as:${viewAsUserId ?? "none"}:${thisMonday}`),
    queryFn: () => timeEntriesApi.weekly(thisMonday),
    enabled: isAdmin && !!viewAsUserId && hasPermission("timesheet") && isEnabled("timesheet"),
  })
  const viewAsUser = memberUsers.find((u) => u.id === viewAsUserId)
  const { data: preview, refetch: fetchPreview, isError: previewError, isFetching: previewFetching } = useQuery({
    queryKey: dashboardKeys.discordPreview(user?.id, dashboardPermissionSignature),
    queryFn: () => discordApi.preview(),
    enabled: false,
    retry: false,
  })
  const { data: discordSettings } = useQuery({
    queryKey: ["discord-settings"],
    queryFn: () => discordApi.settings(),
    staleTime: 5 * 60_000,
    enabled: isAdmin,
  })
  const discordConfigured = discordSettings?.webhook_configured ?? false

  // ─── Mutations ──────────────────────────────────────────────
  const sendMutation = useMutation({
    mutationFn: (input: { date: string; expected_revision: string }) => discordApi.send(input),
    onSuccess: (receipt) => {
      deliveryToast(receipt)
      queryClient.invalidateQueries({ queryKey: ["deliveries", "manual"] })
      setPreviewOpen(false)
    },
    onError: (err) => {
      if ((err as { response?: { status?: number } }).response?.status === 409) {
        toast.error("El contenido cambió. Revisa la vista previa antes de enviar.")
        void fetchPreview()
        return
      }
      toast.error(getErrorMessage(err, "Error al enviar a Discord"))
    },
  })
  const closeMutation = useMutation({
    mutationFn: (payload: Record<string, boolean | string>) => dashboardApi.updateMonthlyClose(payload, params),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: dashboardKeys.monthlyClose(year, month, user?.id, dashboardPermissionSignature) }),
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar el cierre")),
  })
  const financialMutation = useMutation({
    mutationFn: (payload: Record<string, number>) => dashboardApi.updateFinancialSettings(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: dashboardKeys.financialSettings(user?.id, dashboardPermissionSignature) }),
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar los guardarraíles")),
  })
  const markDoneMutation = useMutation({
    mutationFn: ({ taskId, status }: { taskId: number; status: "completed" | "in_review" }) => tasksApi.update(taskId, { status }),
    onSuccess: (task, action) => {
      toast.success(action.status === "in_review" ? "Tarea enviada a revisión" : "Tarea completada")
      invalidateTaskChange(queryClient, { projectId: task.project_id, clientId: task.client_id })
    },
    onError: (err, action) => toast.error(getErrorMessage(err, action.status === "in_review" ? "Error al enviar la tarea a revisión" : "Error al completar la tarea")),
  })
  const startTimerMutation = useMutation({
    mutationFn: (taskId: number) => timerApi.start({ task_id: taskId }),
    onSuccess: () => {
      toast.success("Timer iniciado")
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
      queryClient.invalidateQueries({ queryKey: dashboardKeys.all() })
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al iniciar el timer")),
  })
  const stopTimerMutation = useMutation({
    mutationFn: () => timerApi.stop(),
    onSuccess: () => {
      toast.success("Timer parado")
      queryClient.invalidateQueries({ queryKey: dashboardKeys.all() })
      invalidateTimeChange(queryClient)
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al parar el timer")),
  })

  const weeklyReportMutation = useMutation({
    mutationFn: () => discordApi.sendWeeklyReport(),
    onSuccess: (data) => {
      deliveryToast(data)
      queryClient.invalidateQueries({ queryKey: ["deliveries", "manual"] })
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al enviar informe semanal")),
  })

  // ─── Computed ───────────────────────────────────────────────
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

  const closeKeys = ["reviewed_numbers", "reviewed_margin", "reviewed_cash_buffer", "reviewed_reinvestment", "reviewed_debt", "reviewed_taxes", "reviewed_personal", "reviewed_holded"]
  const closeDoneCount = monthlyClose ? closeKeys.filter((key) => Boolean(monthlyClose[key as keyof typeof monthlyClose])).length : 0
  const closeTotalCount = closeKeys.length
  const closeDay = financialSettings?.monthly_close_day || 5
  const nowDay = Number(todayStr.slice(8, 10))
  const closeReminder = monthlyClose && nowDay >= closeDay && closeDoneCount < closeTotalCount

  const creditUtilization = financialSettings?.credit_utilization || 0
  const creditAlertPct = financialSettings?.credit_alert_pct || 70
  const taxReserve = financialSettings?.tax_reserve || 0
  const taxReserveTargetPct = financialSettings?.tax_reserve_target_pct || 20
  const monthlyCost = financialOverviewQuery.isError ? null : financialOverviewQuery.data?.total_cost ?? null
  const financialAlerts = [
    creditUtilization >= creditAlertPct ? { title: "Uso alto de línea de crédito", description: `La línea está al ${creditUtilization}%, supera el umbral ${creditAlertPct}%.` } : null,
    monthlyCost != null && monthlyCost > 0 && taxReserve < monthlyCost * (taxReserveTargetPct / 100) ? { title: "Fondo de impuestos bajo", description: "El fondo reservado parece insuficiente para costes actuales." } : null,
  ].filter(Boolean) as { title: string; description: string }[]

  const handlePreview = async () => {
    setPreviewOpen(true)
    await fetchPreview()
  }
  const previewVerified = !!preview?.summary && !previewError && !previewFetching
  const handleExportClose = async () => {
    try {
      const blob = await dashboardApi.exportMonthlyClose({ year, month })
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = `cierre-mensual-${year}-${String(month).padStart(2, "0")}.csv`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      toast.error(getErrorMessage(err, "Error al exportar el cierre"))
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold uppercase tracking-wide">Visión general</h2>
          {!overviewQuery.isError && overview && overview.pending_tasks != null && overview.in_progress_tasks != null && overview.active_clients != null && (
            <p className="text-sm text-muted-foreground mt-1">
              {MONTHS[month - 1]}: {overview.pending_tasks + overview.in_progress_tasks} tareas activas · {overview.active_clients} clientes externos activos hoy
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <DailyBriefingButton />
          {isAdmin && (
            <Button
              variant="ghost"
              size="sm"
              disabled={weeklyReportMutation.isPending}
              onClick={() => weeklyReportMutation.mutate()}
              title="Enviar por Discord DM el último informe laboral cerrado (lunes a viernes)"
            >
              <BarChart3 className={`h-4 w-4 mr-1 ${weeklyReportMutation.isPending ? "animate-spin" : ""}`} />
              {weeklyReportMutation.isPending ? "Enviando..." : "Enviar informe semanal"}
            </Button>
          )}
          {isAdmin && memberUsers.length > 0 && (
            <Select
              aria-label="Persona del dashboard"
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
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={goToPrevMonth} title="Mes anterior">
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Select aria-label="Mes del dashboard" value={month} onChange={(e) => setMonth(Number(e.target.value))} className="w-40">
              {MONTHS.map((m, i) => (<option key={i} value={i + 1}>{m}</option>))}
            </Select>
            <Select aria-label="Año del dashboard" value={year} onChange={(e) => setYear(Number(e.target.value))} className="w-24">
              {[businessNow.getFullYear() - 1, businessNow.getFullYear(), businessNow.getFullYear() + 1].map((y) => (<option key={y} value={y}>{y}</option>))}
            </Select>
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={goToNextMonth} title="Mes siguiente">
              <ChevronRight className="h-4 w-4" />
            </Button>
            {!isCurrentMonth && (
              <Button variant="outline" size="sm" className="h-8 text-xs" onClick={goToCurrentMonth}>
                Hoy
              </Button>
            )}
          </div>
        </div>
      </div>
      {isAdmin && <ManualDeliveryReceipts kind="weekly_report" hideWhenEmpty />}
      {isAdmin && <ManualDeliveryReceipts kind="daily_summary" hideWhenEmpty />}
      {user && !viewAsUserId && <DailyUpdateWidget userId={user.id} />}

      {/* Overdue Holded invoices alert */}
      {financeEnabled && overdueInvoices.length > 0 && (
        <div className="rounded-lg border border-red-300 bg-red-50/10 p-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-red-500 flex-shrink-0" />
            <span className="text-sm font-medium text-red-500">
              {overdueInvoices.length} {overdueInvoices.length === 1 ? "factura vencida" : "facturas vencidas"} por un total de {formatCurrency(overdueTotal)}
            </span>
          </div>
          <Link to="/finance-holded" className="text-xs text-red-500 hover:underline whitespace-nowrap ml-4">
            Ver en Holded →
          </Link>
        </div>
      )}

      {/* Today Block */}
      {hasPermission("tasks") && isEnabled("tasks") && <TodayBlock />}

      {/* Worker Dashboard */}
      {!isAdmin && user && (
        <div className="space-y-4">
          {(myInProgressError || myPendingError || weeklyTimesheetError) && <Card><CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6"><p role="alert" className="text-sm">No se pudo actualizar tu trabajo del día.</p><Button type="button" variant="outline" size="sm" onClick={() => { void refetchMyInProgress(); void refetchMyPending(); void refetchWeeklyTimesheet() }}>Reintentar</Button></CardContent></Card>}

          {canWriteTime && activeTimerQuery.isError && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border p-3">
              <p role="alert" className="text-sm">No se pudo comprobar el cronómetro. Reintenta antes de iniciar otro.</p>
              <Button variant="outline" size="sm" disabled={activeTimerQuery.isFetching} onClick={() => void activeTimerQuery.refetch()}>Reintentar cronómetro</Button>
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
                    disabled={stopTimerMutation.isPending || !canWriteTime}
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
                {myInProgressTasks.slice(0, 5).map((t) => {
                  const completion = completionAction(t, user.id, isAdmin)
                  return (
                  <div
                    key={t.id}
                    className="flex items-center gap-3 bg-card border border-border rounded-xl px-4 py-3 hover:border-brand/30 transition-colors"
                  >
                    <button
                      onClick={() => markDoneMutation.mutate({ taskId: t.id, status: completion.status })}
                      disabled={markDoneMutation.isPending || !canWriteTasks}
                      className="group w-5 h-5 rounded-full border-2 border-border hover:border-green-400 hover:bg-green-400/10 flex items-center justify-center flex-shrink-0 transition-colors"
                      aria-label={`${completion.label}: ${t.title}`}
                      title={completion.label}
                    >
                      <Check className="h-3 w-3 text-transparent group-hover:text-green-400 transition-colors" />
                    </button>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{t.title}</p>
                      {t.client_name && <p className="text-xs text-muted-foreground">{t.client_name}</p>}
                    </div>
                    {t.due_date && (
                      <span className={`text-xs mono flex-shrink-0 ${t.due_date < todayStr ? "text-red-400" : "text-muted-foreground"}`}>
                        {formatCivilDate(t.due_date, { day: "numeric", month: "short" })}
                      </span>
                    )}
                    {activeTimer?.task_id === t.id ? (
                      <span className="text-brand text-xs font-medium flex items-center gap-1 flex-shrink-0">
                        <span className="w-1.5 h-1.5 rounded-full bg-brand animate-pulse" />timer
                      </span>
                    ) : (
                      <button
                        onClick={() => startTimerMutation.mutate(t.id)}
                        disabled={startTimerMutation.isPending || timerUnknown || !!activeTimer || !canWriteTime}
                        className="p-1.5 text-muted-foreground hover:text-brand hover:bg-brand/10 rounded-lg transition-colors disabled:opacity-40 flex-shrink-0"
                        title="Iniciar timer"
                      >
                        <Play className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                  )
                })}
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
                {myPendingTasks.slice(0, 8).map((t) => {
                  const completion = completionAction(t, user.id, isAdmin)
                  return (
                  <div key={t.id} className="flex items-center gap-3 px-4 py-2.5 rounded-lg hover:bg-muted/50 transition-colors group">
                    <div className="w-1.5 h-1.5 rounded-full bg-muted-foreground/40 flex-shrink-0" />
                    <span className="text-sm flex-1 truncate">{t.title}</span>
                    {t.client_name && <span className="text-xs text-muted-foreground hidden group-hover:block">{t.client_name}</span>}
                    {t.due_date && (
                      <span className={`text-xs mono flex-shrink-0 ${t.due_date < todayStr ? "text-red-400" : "text-muted-foreground"}`}>
                        {formatCivilDate(t.due_date, { day: "numeric", month: "short" })}
                      </span>
                    )}
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                      <button
                        onClick={() => startTimerMutation.mutate(t.id)}
                        disabled={startTimerMutation.isPending || timerUnknown || !!activeTimer || !canWriteTime}
                        className="p-1 text-muted-foreground hover:text-brand rounded transition-colors disabled:opacity-40"
                        title="Iniciar timer"
                      >
                        <Play className="h-3 w-3" />
                      </button>
                      <button
                        onClick={() => markDoneMutation.mutate({ taskId: t.id, status: completion.status })}
                        disabled={markDoneMutation.isPending || !canWriteTasks}
                        className="p-1 text-muted-foreground hover:text-green-400 rounded transition-colors"
                        aria-label={`${completion.label}: ${t.title}`}
                        title={completion.label}
                      >
                        <Check className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                  )
                })}
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
          {(viewAsInProgressError || viewAsPendingError || viewAsOverdueError || viewAsWeeklyError) && (
            <Card><CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6"><p role="alert" className="text-sm">No se pudo actualizar esta vista del equipo.</p><Button type="button" variant="outline" size="sm" onClick={() => { void refetchViewAsInProgress(); void refetchViewAsPending(); void refetchViewAsOverdue(); void refetchViewAsWeekly() }}>Reintentar</Button></CardContent></Card>
          )}
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
                <Table aria-label="Tareas en curso">
                  <TableHeader><TableRow><TableHead>Tarea</TableHead><TableHead>Cliente</TableHead><TableHead>Fecha límite</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {viewAsInProgress.map((t) => (
                      <TableRow key={t.id}>
                        <TableCell className="font-medium">{t.title}</TableCell>
                        <TableCell>{t.client_name || "-"}</TableCell>
                        <TableCell className="mono">{t.due_date ? formatCivilDate(t.due_date) : "-"}</TableCell>
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
                <Table aria-label="Tareas pendientes">
                  <TableHeader><TableRow><TableHead>Tarea</TableHead><TableHead>Cliente</TableHead><TableHead>Fecha límite</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {viewAsPending.map((t) => (
                      <TableRow key={t.id}>
                        <TableCell className="font-medium">{t.title}</TableCell>
                        <TableCell>{t.client_name || "-"}</TableCell>
                        <TableCell className="mono">{t.due_date ? formatCivilDate(t.due_date) : "-"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {financeEnabled && (monthlyCloseError || financialSettingsError) && (
        <Card><CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6"><p role="alert" className="text-sm">No se pudo actualizar el cierre mensual.</p><Button type="button" variant="outline" size="sm" onClick={() => { void refetchMonthlyClose(); void refetchFinancialSettings() }}>Reintentar</Button></CardContent></Card>
      )}

      {financeEnabled && !monthlyCloseError && !financialSettingsError && closeReminder && (
        <Card><CardContent className="pt-6"><div className="text-sm font-medium">Recordatorio de cierre mensual</div><div className="text-xs text-muted-foreground mt-1">Estamos a partir del día {closeDay}. Completa el cierre mensual para evitar decisiones con datos incompletos.</div></CardContent></Card>
      )}

      {/* Metric Cards & Inbox */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 2xl:gap-6">
        <div className="xl:col-span-2 space-y-4 2xl:space-y-6">
          <OperationalOverview overview={overview} isLoading={overviewQuery.isLoading} isError={overviewQuery.isError} onRetry={() => void overviewQuery.refetch()} />
          {financeEnabled && !financialOverviewForbidden && (
            financialOverviewQuery.isError ? <Card><CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6"><p role="alert" className="text-sm">No se pudo cargar el resumen financiero.</p><Button type="button" variant="outline" size="sm" onClick={() => void financialOverviewQuery.refetch()}>Reintentar</Button></CardContent></Card> : financialOverviewQuery.data ? <div className="space-y-2"><div className="grid grid-cols-1 gap-3 sm:grid-cols-2"><MetricCard icon={DollarSign} label="Presupuesto total" value={financialOverviewQuery.data.total_budget == null ? "—" : formatCurrency(financialOverviewQuery.data.total_budget)} tooltip="Suma de presupuestos del mes seleccionado." /><MetricCard icon={DollarSign} label="Coste total" value={financialOverviewQuery.data.total_cost == null ? "—" : formatCurrency(financialOverviewQuery.data.total_cost)} subtitle={financialOverviewQuery.data.margin == null ? undefined : `Margen: ${formatCurrency(financialOverviewQuery.data.margin)}`} tooltip="Coste registrado del mes seleccionado." /></div></div> : null
          )}
          {isAdmin && !utilizationError && utilization && <MetricCard icon={UserCog} label="Ocupación" value={utilization.global_utilization_pct == null ? "—" : `${utilization.global_utilization_pct}%`} subtitle={utilization.global_utilization_pct == null ? "Sin capacidad configurada" : `${utilization.total_logged_hours}h / ${utilization.total_available_hours}h`} tooltip="Horas registradas frente a horas disponibles del equipo." />}
          {isAdmin && utilizationError && <Card><CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6"><p role="alert" className="text-sm">No se pudo actualizar la ocupación del equipo.</p><Button type="button" variant="outline" size="sm" onClick={() => void refetchUtilization()}>Reintentar</Button></CardContent></Card>}
        </div>
        <div className="xl:col-span-1 h-[250px]"><InboxWidget /></div>
      </div>

      <InsightsPanel />

      {isAdmin && allOverdueTasks && allOverdueTasks.length > 0 && <OverdueTasks tasks={allOverdueTasks} showAssigned title="Tareas vencidas del equipo" />}
      {allClientsError ? (
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6">
            <p role="alert" className="text-sm">No se pudo cargar la relación de clientes para las métricas de Engine.</p>
            <Button variant="outline" size="sm" onClick={() => void refetchClients()}>Reintentar</Button>
          </CardContent>
        </Card>
      ) : allClients ? <EngineAlertsWidget clients={allClients} /> : null}
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
                <div className="ml-auto text-right"><div className="text-2xl font-bold text-brand">{formatCurrency(proposalStats.pipelineValue)}</div><div className="text-xs text-muted-foreground">Valor pipeline (enviadas)</div></div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {financeEnabled && !financialSettingsError && financialSettings && financialAlerts.length > 0 && (
        <Card className="border-warning/50 bg-warning/5">
          <CardHeader className="pb-2"><CardTitle className="text-warning text-sm">Alertas financieras</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {financialAlerts.map((alert, i) => (<div key={i} className="flex flex-col"><span className="text-sm font-medium">{alert.title}</span><span className="text-xs text-muted-foreground">{alert.description}</span></div>))}
          </CardContent>
        </Card>
      )}

      {financeEnabled && !financialSettingsForbidden && !financialSettingsError && financialSettings && (
        <details className="group border border-border rounded-xl bg-card">
          <summary className="flex cursor-pointer items-center justify-between p-4 font-medium marker:content-none hover:bg-muted/50 transition-colors rounded-xl">
            Configuración Financiera
            <svg className="h-5 w-5 text-muted-foreground transition-transform group-open:rotate-180" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
          </summary>
          <div className="p-4 pt-0 border-t border-border mt-2 space-y-4">
            <div className="grid gap-4 md:grid-cols-3">
              <div><div className="text-xs text-muted-foreground mb-1">Fondo impuestos (€)</div><input className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm" type="number" step="0.01" min="0" defaultValue={financialSettings.tax_reserve} onBlur={(e) => financialMutation.mutate({ tax_reserve: Number(e.target.value) })} /></div>
              <div><div className="text-xs text-muted-foreground mb-1">Línea crédito total (€)</div><input className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm" type="number" step="0.01" min="0" defaultValue={financialSettings.credit_limit} onBlur={(e) => financialMutation.mutate({ credit_limit: Number(e.target.value) })} /></div>
              <div><div className="text-xs text-muted-foreground mb-1">Crédito utilizado (€)</div><input className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm" type="number" step="0.01" min="0" defaultValue={financialSettings.credit_used} onBlur={(e) => financialMutation.mutate({ credit_used: Number(e.target.value) })} /><div className="text-xs text-muted-foreground mt-1">Uso: {financialSettings.credit_utilization}% (alerta {financialSettings.credit_alert_pct}%)</div></div>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div><div className="text-xs text-muted-foreground mb-1">Día récord. cierre</div><input className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm" type="number" min="1" max="28" step="1" defaultValue={financialSettings.monthly_close_day} onBlur={(e) => financialMutation.mutate({ monthly_close_day: Number(e.target.value) })} /></div>
              <div><div className="text-xs text-muted-foreground mb-1">Alerta crédito (%)</div><input className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm" type="number" min="0" max="100" step="1" defaultValue={financialSettings.credit_alert_pct} onBlur={(e) => financialMutation.mutate({ credit_alert_pct: Number(e.target.value) })} /></div>
              <div><div className="text-xs text-muted-foreground mb-1">Cob. impuestos (%)</div><input className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm" type="number" min="0" max="200" step="1" defaultValue={financialSettings.tax_reserve_target_pct} onBlur={(e) => financialMutation.mutate({ tax_reserve_target_pct: Number(e.target.value) })} /></div>
            </div>
          </div>
        </details>
      )}

      {financeEnabled && !monthlyCloseForbidden && !monthlyCloseError && monthlyClose && <MonthlyCloseChecklist key={`${user?.id ?? "anonymous"}:${year}:${month}:${dashboardPermissionSignature}`} monthlyClose={monthlyClose as unknown as Record<string, string | boolean | null>} onUpdate={(p) => closeMutation.mutate(p)} onExport={handleExportClose} isPending={closeMutation.isPending} lastHoldedSync={lastHoldedSync} />}

      {financeEnabled && !profitabilityError && profitability && profitability.clients.length > 0 && (
        <div className="grid lg:grid-cols-2 gap-6">
          <Card className="min-w-0">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Rentabilidad por cliente
                <span className="text-xs font-normal text-muted-foreground">
                  (datos del mes seleccionado arriba, no acumulado)
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-4">
              <div className="overflow-x-auto"><Table aria-label="Rentabilidad por cliente" className="min-w-[700px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>Cliente</TableHead>
                    <TableHead><span className="inline-flex items-center gap-1">Presupuesto <InfoTooltip content="Fee mensual del cliente" /></span></TableHead>
                    <TableHead><span className="inline-flex items-center gap-1">Coste <InfoTooltip content="Horas trabajadas × tarifa/hora" /></span></TableHead>
                    <TableHead><span className="inline-flex items-center gap-1">Estimado <InfoTooltip content="Suma de horas estimadas declaradas en las tareas del mes (campo opcional)" /></span></TableHead>
                    <TableHead><span className="inline-flex items-center gap-1">Real <InfoTooltip content="Tiempo tracked del mes (timesheet/cronómetro real). Es la fuente de verdad para horas trabajadas." /></span></TableHead>
                    <TableHead><span className="inline-flex items-center gap-1">Δ <InfoTooltip content="Diferencia real − estimado" /></span></TableHead>
                    <TableHead><span className="inline-flex items-center gap-1">Margen <InfoTooltip content="Presupuesto − Coste" /></span></TableHead>
                    <TableHead>Estado</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {profitability.clients.map((c) => {
                    const linkedClient = allClients?.find((cl) => cl.id === c.client_id)
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
                      <TableCell className="mono">{formatCurrency(c.budget)}</TableCell>
                      <TableCell className="mono">{formatCurrency(c.cost)}</TableCell>
                      <TableCell className="mono">{Math.round((c.estimated_minutes || 0) / 60)}h</TableCell>
                      <TableCell className="mono">{Math.round((c.actual_minutes || 0) / 60)}h</TableCell>
                      <TableCell className="mono">{Math.round((c.variance_minutes || 0) / 60)}h</TableCell>
                      <TableCell className="mono">{formatCurrency(c.margin)} ({c.margin_percent}%)</TableCell>
                      <TableCell>{profitBadge(c.status)}</TableCell>
                    </TableRow>
                    )
                  })}
                </TableBody>
              </Table></div>
            </CardContent>
          </Card>
          <Card className="min-w-0">
            <CardHeader><CardTitle>Presupuesto vs Coste</CardTitle></CardHeader>
            <CardContent className="pt-4"><ProfitabilityChart data={profitability.clients} /></CardContent>
          </Card>
        </div>
      )}

      {financeEnabled && profitabilityError && <Card><CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6"><p role="alert" className="text-sm">No se pudo cargar la rentabilidad del mes.</p><Button type="button" variant="outline" size="sm" onClick={() => void refetchProfitability()}>Reintentar</Button></CardContent></Card>}
      {isAdmin && !teamError && team && <TeamSummaryTable team={team} />}
      {isAdmin && teamError && <Card><CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6"><p role="alert" className="text-sm">No se pudo actualizar el resumen del equipo.</p><Button type="button" variant="outline" size="sm" onClick={() => void refetchTeam()}>Reintentar</Button></CardContent></Card>}

      {isAdmin && (
        <Card>
          <CardHeader><CardTitle>Resumen Diario</CardTitle></CardHeader>
          <CardContent className="pt-4">
            <div className="flex flex-wrap gap-2 items-center">
              <Button variant="outline" onClick={handlePreview}><Eye className="h-4 w-4 mr-2" /> Vista previa antes de enviar</Button>
              {!discordConfigured && <span className="text-xs text-muted-foreground">Configura el webhook en Ajustes → Discord</span>}
            </div>
          </CardContent>
        </Card>
      )}

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogHeader><DialogTitle>Vista previa — Discord</DialogTitle></DialogHeader>
        {previewError ? <div role="alert" className="space-y-2 border border-destructive/30 p-4 text-sm"><p>No se pudo verificar el contenido para Discord.</p><Button type="button" size="sm" variant="outline" onClick={() => void fetchPreview()}>Reintentar</Button></div> : <div className="bg-surface border border-brand/10 p-4 whitespace-pre-wrap text-sm font-mono text-foreground">{previewFetching ? "Cargando..." : preview?.summary || "No hay contenido verificado."}</div>}
        <div className="flex justify-end gap-2 mt-4">
          <Button variant="outline" onClick={() => setPreviewOpen(false)}>Cerrar</Button>
          <Button onClick={() => preview && sendMutation.mutate({ date: preview.date, expected_revision: preview.revision })} disabled={sendMutation.isPending || !discordConfigured || !previewVerified}><Send className="h-4 w-4 mr-2" /> {sendMutation.isPending ? "Enviando..." : "Enviar"}</Button>
        </div>
      </Dialog>
    </div>
  )
}
