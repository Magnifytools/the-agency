import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  financeAdvisorApi,
  financeForecastsApi,
  dashboardApi,
  clientHealthApi,
  capacityApi,
  leadsApi,
} from "@/lib/api"
import { MetricCard } from "@/components/dashboard/metric-card"
import { RevenueTrendChart } from "@/components/dashboard/revenue-trend-chart"
import { HealthGrid } from "@/components/dashboard/health-grid"
import { CapacityBars } from "@/components/dashboard/capacity-bars"
import { PipelineCard } from "@/components/dashboard/pipeline-card"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Select } from "@/components/ui/select"
import { Link } from "react-router-dom"
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

const now = new Date()
const fmt = (n: number) => n.toLocaleString("es-ES", { style: "currency", currency: "EUR" })

export default function ExecutiveDashboardPage() {
  const [year, setYear] = useState(now.getFullYear())
  const month = now.getMonth() + 1

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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold uppercase tracking-wide">Dashboard Ejecutivo</h2>
          {ytd && (
            <p className="text-sm text-muted-foreground mt-1">
              YTD {year}: {fmt(ytd.income)} ingresos, {fmt(ytd.profit)} beneficio
            </p>
          )}
        </div>
        <Select value={year} onChange={(e) => setYear(Number(e.target.value))} className="w-24">
          {[now.getFullYear() - 1, now.getFullYear(), now.getFullYear() + 1].map((y) => (
            <option key={y} value={y}>{y}</option>
          ))}
        </Select>
      </div>

      {/* KPI Row — clickable cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {overview && (
          <>
            <Link to="/finance/income" className="hover:ring-1 hover:ring-brand/30 rounded-xl transition-all">
              <MetricCard
                icon={TrendingUp}
                label="Ingresos mes"
                value={fmt(overview.total_income_month)}
                tooltip="Total facturado este mes"
              />
            </Link>
            <Link to="/finance/expenses" className="hover:ring-1 hover:ring-brand/30 rounded-xl transition-all">
              <MetricCard
                icon={TrendingDown}
                label="Gastos mes"
                value={fmt(overview.total_expenses_month)}
                tooltip="Total gastos este mes"
              />
            </Link>
            <Link to="/finance" className="hover:ring-1 hover:ring-brand/30 rounded-xl transition-all">
              <MetricCard
                icon={DollarSign}
                label="Beneficio neto"
                value={fmt(overview.net_profit_month)}
                subtitle={overview.net_profit_month >= 0 ? "positivo" : "negativo"}
                tooltip="Ingresos - gastos del mes"
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
              value={`${runway.runway_months}m`}
              subtitle={fmt(runway.current_cash)}
              tooltip="Meses de operación con cash actual y gasto medio"
            />
          </Link>
        )}
        {pipeline && (
          <Link to="/leads" className="hover:ring-1 hover:ring-brand/30 rounded-xl transition-all">
            <MetricCard
              icon={Target}
              label="Pipeline"
              value={fmt(pipeline.total_value)}
              subtitle={`${pipeline.total_leads} leads`}
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
              <ResponsiveContainer width="100%" height={Math.max(200, profitChartData.length * 40)}>
                <BarChart data={profitChartData} layout="vertical">
                  <XAxis
                    type="number"
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
    </div>
  )
}
