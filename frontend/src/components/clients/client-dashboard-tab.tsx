import { useQuery } from "@tanstack/react-query"
import { TrendingUp, TrendingDown, Clock, DollarSign, AlertTriangle, CheckCircle2, BarChart3 } from "lucide-react"
import { clientDashboardApi } from "@/lib/api"
import type { Client } from "@/lib/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

interface Props {
  client: Client
}

const STATUS_LABELS: Record<string, string> = {
  pending: "Pendientes",
  in_progress: "En curso",
  completed: "Completadas",
}

export function ClientDashboardTab({ client }: Props) {
  const { data: dash, isLoading } = useQuery({
    queryKey: ["client-dashboard", client.id],
    queryFn: () => clientDashboardApi.get(client.id),
    staleTime: 60_000,
  })

  if (isLoading) return <p className="text-muted-foreground text-sm">Cargando panel...</p>
  if (!dash) return <p className="text-muted-foreground text-sm">Sin datos</p>

  const profBadge = dash.profitability_status === "profitable"
    ? { label: "Rentable", variant: "success" as const }
    : dash.profitability_status === "at_risk"
      ? { label: "En riesgo", variant: "warning" as const }
      : { label: "No rentable", variant: "destructive" as const }

  const TrendIcon = dash.hours_trend_pct >= 0 ? TrendingUp : TrendingDown

  // Find max for bars
  const monthKeys = Object.keys(dash.monthly_hours_breakdown).sort()
  const maxHours = Math.max(...Object.values(dash.monthly_hours_breakdown), 1)

  return (
    <div className="space-y-6">
      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <Clock className="h-3 w-3" /> Horas este mes
            </p>
            <p className="kpi-value mt-1">{dash.hours_this_month}h</p>
            <div className="flex items-center gap-1 mt-1">
              <TrendIcon className={`h-3 w-3 ${dash.hours_trend_pct >= 0 ? "text-amber-500" : "text-green-500"}`} />
              <span className="text-xs text-muted-foreground">
                {dash.hours_trend_pct > 0 ? "+" : ""}{dash.hours_trend_pct}% vs mes anterior
              </span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <DollarSign className="h-3 w-3" /> Coste este mes
            </p>
            <p className="kpi-value mt-1">{dash.total_cost_this_month.toLocaleString("es-ES")} {client.currency}</p>
            <p className="text-xs text-muted-foreground mt-1">
              Fee: {dash.monthly_fee.toLocaleString("es-ES")} {client.currency}
            </p>
          </CardContent>
        </Card>

        <Card className={dash.profitability_status === "unprofitable" ? "border-red-300 bg-red-50/10" : ""}>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <BarChart3 className="h-3 w-3" /> Margen
            </p>
            <p className={`kpi-value mt-1 ${dash.margin >= 0 ? "text-green-500" : "text-red-500"}`}>
              {dash.margin.toLocaleString("es-ES")} {client.currency}
            </p>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-xs mono">{dash.margin_pct}%</span>
              <Badge variant={profBadge.variant}>{profBadge.label}</Badge>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <AlertTriangle className="h-3 w-3" /> Tareas
            </p>
            <div className="mt-1 space-y-1">
              {dash.tasks_overdue > 0 && (
                <div className="flex items-center gap-1">
                  <span className="text-sm font-semibold text-red-500">{dash.tasks_overdue}</span>
                  <span className="text-xs text-red-500">vencidas</span>
                </div>
              )}
              {dash.tasks_due_this_week > 0 && (
                <div className="flex items-center gap-1">
                  <span className="text-sm font-semibold text-amber-500">{dash.tasks_due_this_week}</span>
                  <span className="text-xs text-amber-500">esta semana</span>
                </div>
              )}
              {dash.tasks_overdue === 0 && dash.tasks_due_this_week === 0 && (
                <div className="flex items-center gap-1">
                  <CheckCircle2 className="h-4 w-4 text-green-500" />
                  <span className="text-xs text-green-500">Al dia</span>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Tasks by status + Monthly trend */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Tasks by status */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Tareas por estado</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {Object.entries(STATUS_LABELS).map(([status, label]) => {
                const count = dash.tasks_by_status[status] || 0
                const total = Object.values(dash.tasks_by_status).reduce((a, b) => a + b, 0) || 1
                const pct = Math.round((count / total) * 100)
                return (
                  <div key={status}>
                    <div className="flex justify-between text-sm mb-1">
                      <span>{label}</span>
                      <span className="mono">{count}</span>
                    </div>
                    <div className="h-2 bg-muted rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${
                          status === "completed" ? "bg-green-500" : status === "in_progress" ? "bg-brand" : "bg-muted-foreground/40"
                        }`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>

        {/* Monthly hours trend */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Horas mensuales</CardTitle>
          </CardHeader>
          <CardContent>
            {monthKeys.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">Sin datos de tiempo</p>
            ) : (
              <div className="flex items-end gap-2 h-32">
                {monthKeys.map((key) => {
                  const val = dash.monthly_hours_breakdown[key]
                  const pct = (val / maxHours) * 100
                  const [, mo] = key.split("-")
                  const monthName = new Date(2024, Number(mo) - 1).toLocaleString("es-ES", { month: "short" })
                  return (
                    <div key={key} className="flex-1 flex flex-col items-center gap-1">
                      <span className="text-[10px] mono">{val}h</span>
                      <div className="w-full bg-muted rounded-t" style={{ height: `${Math.max(pct, 4)}%` }}>
                        <div className="w-full h-full bg-brand rounded-t" />
                      </div>
                      <span className="text-[10px] text-muted-foreground capitalize">{monthName}</span>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Team breakdown */}
      {dash.team_breakdown.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Desglose por miembro</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {dash.team_breakdown
                .sort((a, b) => b.hours - a.hours)
                .map((m) => (
                  <div key={m.user_id} className="flex items-center justify-between text-sm">
                    <span>{m.full_name}</span>
                    <div className="flex items-center gap-4">
                      <span className="mono">{m.hours.toFixed(1)}h</span>
                      <span className="mono text-muted-foreground w-24 text-right">
                        {m.cost.toLocaleString("es-ES")} {client.currency}
                      </span>
                    </div>
                  </div>
                ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
