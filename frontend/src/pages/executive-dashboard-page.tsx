import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  financeAdvisorApi,
  financeForecastsApi,
  dashboardApi,
  clientHealthApi,
  capacityApi,
  leadsApi,
  balanceApi,
} from "@/lib/api"
import { MetricCard } from "@/components/dashboard/metric-card"
import { RevenueTrendChart } from "@/components/dashboard/revenue-trend-chart"
import { HealthGrid } from "@/components/dashboard/health-grid"
import { CapacityBars } from "@/components/dashboard/capacity-bars"
import { PipelineCard } from "@/components/dashboard/pipeline-card"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Select } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import { formatCurrency } from "@/lib/format"
import type { BalanceSnapshotCreate } from "@/lib/types"
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts"
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  Percent,
  Clock,
  Target,
} from "lucide-react"
import { FinanceTabNav } from "@/components/finance/finance-tab-nav"

export default function ExecutiveDashboardPage() {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const month = now.getMonth() + 1
  const [balanceDialogOpen, setBalanceDialogOpen] = useState(false)
  const qc = useQueryClient()

  // Financial overview (current month)
  const { data: overview } = useQuery({
    queryKey: ["exec-advisor-overview"],
    queryFn: () => financeAdvisorApi.overview(),
  })

  // 12-month trend (forecast vs actual)
  const { data: vsActual } = useQuery({
    queryKey: ["exec-vs-actual", year],
    queryFn: () => financeForecastsApi.vsActual(year),
  })

  // Runway
  const { data: runway } = useQuery({
    queryKey: ["exec-runway"],
    queryFn: () => financeForecastsApi.runway(),
  })

  // Profitability per client
  const { data: profitability } = useQuery({
    queryKey: ["exec-profitability", year, month],
    queryFn: () => dashboardApi.profitability({ year, month }),
  })

  // Client health scores
  const { data: healthScores } = useQuery({
    queryKey: ["exec-health"],
    queryFn: () => clientHealthApi.list(),
  })

  // Team capacity
  const { data: capacity } = useQuery({
    queryKey: ["exec-capacity"],
    queryFn: () => capacityApi.get(),
  })

  // Lead pipeline
  const { data: pipeline } = useQuery({
    queryKey: ["exec-pipeline"],
    queryFn: () => leadsApi.pipelineSummary(),
  })

  // Manual balance snapshot
  const { data: latestBalance } = useQuery({
    queryKey: ["balance-latest"],
    queryFn: () => balanceApi.latest(),
  })

  const createBalanceMut = useMutation({
    mutationFn: (data: BalanceSnapshotCreate) => balanceApi.create(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["balance-latest"] })
      qc.invalidateQueries({ queryKey: ["exec-runway"] })
      setBalanceDialogOpen(false)
      toast.success("Saldo actualizado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al guardar saldo")),
  })

  function handleBalanceSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    createBalanceMut.mutate({
      date: fd.get("date") as string,
      amount: parseFloat(fd.get("amount") as string) || 0,
      notes: (fd.get("notes") as string) || "",
    })
  }

  // YTD totals from vsActual
  const ytd = vsActual
    ? vsActual.reduce(
        (acc, m) => ({
          income: acc.income + m.actual_income,
          expenses: acc.expenses + m.actual_expenses,
          profit: acc.profit + m.actual_profit,
        }),
        { income: 0, expenses: 0, profit: 0 }
      )
    : null

  // Profitability chart data — sorted by margin %
  const profitChartData = profitability
    ? [...profitability.clients]
        .sort((a, b) => b.margin_percent - a.margin_percent)
        .map((c) => ({
          name: c.client_name.length > 18 ? c.client_name.slice(0, 18) + "..." : c.client_name,
          margen: c.margin_percent,
          status: c.status,
        }))
    : []

  // Clients with no recorded costs (margin may be misleading)
  const zeroCostClients = profitability
    ? profitability.clients.filter((c) => c.cost === 0 && c.margin_percent >= 95)
    : []

  // Month-over-month delta from vsActual
  const prevMonth = month === 1 ? 12 : month - 1
  const prevYear = month === 1 ? year - 1 : year
  const currentMonthRow = vsActual?.find((r) => {
    const d = new Date(r.month + "T12:00:00")
    return d.getFullYear() === year && d.getMonth() + 1 === month
  })
  const prevMonthRow = vsActual?.find((r) => {
    const d = new Date(r.month + "T12:00:00")
    return d.getFullYear() === prevYear && d.getMonth() + 1 === prevMonth
  })
  const momDelta =
    currentMonthRow && prevMonthRow
      ? {
          income: currentMonthRow.actual_income - prevMonthRow.actual_income,
          expenses: currentMonthRow.actual_expenses - prevMonthRow.actual_expenses,
          profit: currentMonthRow.actual_profit - prevMonthRow.actual_profit,
        }
      : null

  return (
    <div className="space-y-6">
      <FinanceTabNav />
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold uppercase tracking-wide">Dashboard Ejecutivo</h2>
          {ytd && (
            <p className="text-sm text-muted-foreground mt-1">
              YTD {year}: {formatCurrency(ytd.income)} ingresos, {formatCurrency(ytd.profit)} beneficio
            </p>
          )}
        </div>
        <Select value={year} onChange={(e) => setYear(Number(e.target.value))} className="w-24">
          {[now.getFullYear() - 1, now.getFullYear(), now.getFullYear() + 1].map((y) => (
            <option key={y} value={y}>{y}</option>
          ))}
        </Select>
      </div>

      {/* Saldo Bancario Manual */}
      <Card className="border-border/60">
        <CardContent className="pt-4 pb-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wide font-medium">Saldo Real (Banco)</p>
              {latestBalance ? (
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-2xl font-bold">{formatCurrency(latestBalance.amount)}</span>
                  <Badge variant="secondary">Manual</Badge>
                  <span className="text-xs text-muted-foreground">
                    {new Date(latestBalance.date + "T12:00:00").toLocaleDateString("es-ES", { day: "2-digit", month: "short" })}
                  </span>
                </div>
              ) : (
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xl text-muted-foreground">Sin datos</span>
                  <Badge variant="secondary">Calculado</Badge>
                </div>
              )}
              {latestBalance?.notes && <p className="text-xs text-muted-foreground mt-1">{latestBalance.notes}</p>}
            </div>
            <Button variant="outline" size="sm" onClick={() => setBalanceDialogOpen(true)}>
              Actualizar
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* KPI Row — clickable cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {overview && (
          <>
            <Link to="/finance/income" className="hover:ring-1 hover:ring-brand/30 rounded-xl transition-all">
              <MetricCard
                icon={TrendingUp}
                label="Ingresos mes"
                value={formatCurrency(overview.total_income_month)}
                tooltip="Total facturado este mes"
                delta={momDelta?.income}
              />
            </Link>
            <Link to="/finance/expenses" className="hover:ring-1 hover:ring-brand/30 rounded-xl transition-all">
              <MetricCard
                icon={TrendingDown}
                label="Gastos mes"
                value={formatCurrency(overview.total_expenses_month)}
                tooltip="Total gastos este mes"
                delta={momDelta?.expenses}
              />
            </Link>
            <Link to="/finance" className="hover:ring-1 hover:ring-brand/30 rounded-xl transition-all">
              <MetricCard
                icon={DollarSign}
                label="Beneficio neto"
                value={formatCurrency(overview.net_profit_month)}
                subtitle={overview.net_profit_month >= 0 ? "positivo" : "negativo"}
                tooltip="Ingresos - gastos del mes"
                delta={momDelta?.profit}
              />
            </Link>
            <Link to="/finance" className="hover:ring-1 hover:ring-brand/30 rounded-xl transition-all">
              <MetricCard
                icon={Percent}
                label="Margen"
                value={`${overview.margin_pct.toFixed(1)}%`}
                tooltip="Margen neto = beneficio / ingresos"
              />
            </Link>
          </>
        )}
        {runway && (
          <Link to="/finance/forecasts" className="hover:ring-1 hover:ring-brand/30 rounded-xl transition-all">
            <MetricCard
              icon={Clock}
              label="Runway"
              value={runway.runway_months != null ? `${runway.runway_months}m` : "∞"}
              subtitle={`${formatCurrency(runway.current_cash)} · ${runway.source === "manual" ? "Manual" : "Est."}`}
              tooltip="Meses de operación con cash actual y gasto medio"
            />
          </Link>
        )}
        {pipeline && (
          <Link to="/leads" className="hover:ring-1 hover:ring-brand/30 rounded-xl transition-all">
            <MetricCard
              icon={Target}
              label="Pipeline"
              value={formatCurrency(pipeline.total_value)}
              subtitle={`${pipeline.total_leads} ${pipeline.total_leads === 1 ? "lead" : "leads"}`}
              tooltip="Valor total de leads activos en el pipeline"
            />
          </Link>
        )}
      </div>

      {/* Revenue Trend */}
      {vsActual && vsActual.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Tendencia de ingresos {year}</CardTitle>
          </CardHeader>
          <CardContent>
            <RevenueTrendChart data={vsActual} />
          </CardContent>
        </Card>
      )}

      {/* Profitability + Health */}
      <div className="grid lg:grid-cols-2 gap-6">
        {/* Profitability Bar Chart */}
        {profitChartData.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Margen por cliente (%)</CardTitle>
            </CardHeader>
            <CardContent>
              {zeroCostClients.length > 0 && (
                <div className="mb-3 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
                  <span className="mt-0.5">⚠️</span>
                  <span>
                    <strong>{zeroCostClients.map((c) => c.client_name).join(", ")}</strong>: No se han registrado costes de equipo. El margen real puede ser menor.
                  </span>
                </div>
              )}
              <ResponsiveContainer width="100%" height={Math.max(200, profitChartData.length * 40)}>
                <BarChart data={profitChartData} layout="vertical">
                  <XAxis
                    type="number"
                    domain={[0, 100]}
                    fontSize={11}
                    tick={{ fill: "#8a8a80" }}
                    tickFormatter={(v) => `${v}%`}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={140}
                    fontSize={11}
                    tick={{ fill: "#8a8a80" }}
                  />
                  <Tooltip
                    formatter={(value) => `${Number(value).toFixed(1)}%`}
                    contentStyle={{
                      backgroundColor: "#2a2a28",
                      border: "1px solid rgba(254, 230, 48, 0.3)",
                      color: "#f5f5f0",
                      fontSize: 12,
                      borderRadius: 8,
                    }}
                    labelStyle={{ color: "#FEE630" }}
                  />
                  <Bar dataKey="margen" radius={[0, 4, 4, 0]}>
                    {profitChartData.map((entry, index) => (
                      <Cell
                        key={index}
                        fill={
                          entry.status === "profitable"
                            ? "#22c55e"
                            : entry.status === "at_risk"
                            ? "#eab308"
                            : "#ef4444"
                        }
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        )}

        {/* Health Scores */}
        {healthScores && healthScores.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Salud de clientes</CardTitle>
            </CardHeader>
            <CardContent>
              <HealthGrid data={healthScores} />
            </CardContent>
          </Card>
        )}
      </div>

      {/* Capacity + Pipeline */}
      <div className="grid lg:grid-cols-2 gap-6">
        {capacity && capacity.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Capacidad del equipo</CardTitle>
            </CardHeader>
            <CardContent>
              <CapacityBars data={capacity} />
            </CardContent>
          </Card>
        )}

        {pipeline && (
          <Card>
            <CardHeader>
              <CardTitle>Pipeline de ventas</CardTitle>
            </CardHeader>
            <CardContent>
              <PipelineCard data={pipeline} />
            </CardContent>
          </Card>
        )}
      </div>

      {/* Balance Dialog */}
      <Dialog open={balanceDialogOpen} onOpenChange={setBalanceDialogOpen}>
        <DialogHeader><DialogTitle>Actualizar saldo bancario</DialogTitle></DialogHeader>
        <form onSubmit={handleBalanceSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div><Label>Fecha</Label><Input name="date" type="date" defaultValue={new Date().toISOString().slice(0, 10)} required /></div>
            <div><Label>Saldo (€)</Label><Input name="amount" type="number" step="0.01" placeholder="2984.00" required /></div>
          </div>
          <div><Label>Nota <span className="text-muted-foreground text-xs">(opcional)</span></Label><Input name="notes" placeholder="Saldo BBVA lunes" /></div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setBalanceDialogOpen(false)}>Cancelar</Button>
            <Button type="submit">Guardar</Button>
          </div>
        </form>
      </Dialog>
    </div>
  )
}
