import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { cfoApi } from "@/lib/api"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { formatCurrency } from "@/lib/format"
import { FinanceTabNav } from "@/components/finance/finance-tab-nav"
import { AlertTriangle, TrendingUp, Clock, Euro } from "lucide-react"

function currentMonth(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
}

function abrColor(abr: number | null): string {
  if (abr === null) return "text-muted-foreground"
  if (abr < 30) return "text-red-500 font-semibold"
  if (abr < 50) return "text-amber-500 font-semibold"
  return "text-green-500 font-semibold"
}

function marginColor(pct: number | null): string {
  if (pct === null) return "text-muted-foreground"
  if (pct < 0) return "text-red-500 font-semibold"
  if (pct < 30) return "text-amber-500 font-semibold"
  return "text-green-500 font-semibold"
}

function severityBadge(s: string) {
  const map: Record<string, string> = {
    critical: "bg-red-500/15 text-red-400 border-red-500/30",
    high: "bg-orange-500/15 text-orange-400 border-orange-500/30",
    medium: "bg-amber-500/15 text-amber-400 border-amber-500/30",
    low: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  }
  return map[s] ?? "bg-muted text-muted-foreground"
}

export default function CfoPage() {
  const [month, setMonth] = useState(currentMonth())

  const { data: margin } = useQuery({
    queryKey: ["cfo-margin", month],
    queryFn: () => cfoApi.deliveryMargin(month),
  })
  const { data: util } = useQuery({
    queryKey: ["cfo-utilization", month],
    queryFn: () => cfoApi.utilization(month),
  })
  const { data: pl } = useQuery({
    queryKey: ["cfo-pl", month],
    queryFn: () => cfoApi.monthlyPL(month),
  })
  const { data: alerts } = useQuery({
    queryKey: ["cfo-alerts", month],
    queryFn: () => cfoApi.alerts(month),
  })

  return (
    <div className="space-y-6">
      <FinanceTabNav />

      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold">CFO — Delivery Margin</h1>
          <p className="text-muted-foreground">Rentabilidad real: fee − horas × coste</p>
        </div>
        <Input
          type="month"
          value={month}
          onChange={(e) => setMonth(e.target.value)}
          className="w-40"
        />
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm text-muted-foreground">Revenue base</CardTitle>
            <Euro className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold mono">{formatCurrency(pl?.revenue ?? 0)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm text-muted-foreground">Labor cost</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold mono">{formatCurrency(pl?.labor_cost ?? 0)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm text-muted-foreground">Delivery margin</CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold mono ${(pl?.delivery_margin ?? 0) < 0 ? "text-red-500" : "text-green-500"}`}>
              {formatCurrency(pl?.delivery_margin ?? 0)}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              Neto (− overhead {formatCurrency(pl?.overhead ?? 0)}): <span className="mono">{formatCurrency(pl?.net_before_tax ?? 0)}</span>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm text-muted-foreground">Alertas activas</CardTitle>
            <AlertTriangle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{alerts?.alerts.length ?? 0}</div>
          </CardContent>
        </Card>
      </div>

      {/* Delivery margin table */}
      <Card>
        <CardHeader>
          <CardTitle>Margen por proyecto</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-muted-foreground border-b">
                <tr>
                  <th className="py-2 pr-4">Proyecto</th>
                  <th className="py-2 pr-4">Cliente</th>
                  <th className="py-2 pr-4 text-right">Fee</th>
                  <th className="py-2 pr-4 text-right">Horas</th>
                  <th className="py-2 pr-4 text-right">Coste</th>
                  <th className="py-2 pr-4 text-right">Margen</th>
                  <th className="py-2 pr-4 text-right">ABR</th>
                  <th className="py-2 pr-4 text-right">%</th>
                </tr>
              </thead>
              <tbody>
                {margin?.projects.map((p) => (
                  <tr key={p.project_id} className="border-b last:border-0">
                    <td className="py-2 pr-4 font-medium">{p.project_name}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{p.client_name}</td>
                    <td className="py-2 pr-4 text-right mono">{formatCurrency(p.monthly_fee)}</td>
                    <td className="py-2 pr-4 text-right mono">{p.total_hours.toFixed(1)}</td>
                    <td className="py-2 pr-4 text-right mono">{formatCurrency(p.labor_cost)}</td>
                    <td className={`py-2 pr-4 text-right mono ${p.delivery_margin < 0 ? "text-red-500 font-semibold" : ""}`}>
                      {formatCurrency(p.delivery_margin)}
                    </td>
                    <td className={`py-2 pr-4 text-right mono ${abrColor(p.abr)}`}>
                      {p.abr !== null ? `${p.abr.toFixed(1)} €/h` : "—"}
                    </td>
                    <td className={`py-2 pr-4 text-right mono ${marginColor(p.margin_pct)}`}>
                      {p.margin_pct !== null ? `${p.margin_pct.toFixed(0)}%` : "—"}
                    </td>
                  </tr>
                ))}
                {!margin?.projects.length && (
                  <tr><td colSpan={8} className="py-6 text-center text-muted-foreground">Sin proyectos con fee este mes</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Utilization */}
      <Card>
        <CardHeader>
          <CardTitle>Utilización del equipo</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {util?.users.map((u) => {
            const billPct = u.available_hours_month > 0 ? (u.billable_hours / u.available_hours_month) * 100 : 0
            const intPct = u.available_hours_month > 0 ? (u.internal_hours / u.available_hours_month) * 100 : 0
            return (
              <div key={u.user_id}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="font-medium">{u.user_name}</span>
                  <span className="text-muted-foreground mono">
                    {u.billable_hours.toFixed(1)}h facturables · {u.internal_hours.toFixed(1)}h internas · {u.utilization_pct.toFixed(0)}%
                  </span>
                </div>
                <div className="w-full bg-muted rounded-full h-3 overflow-hidden flex">
                  <div className="bg-green-500" style={{ width: `${Math.min(100, billPct)}%` }} />
                  <div className="bg-amber-500" style={{ width: `${Math.min(100 - billPct, intPct)}%` }} />
                </div>
              </div>
            )
          })}
          {!util?.users.length && (
            <p className="text-center text-muted-foreground py-4">Sin datos de utilización</p>
          )}
        </CardContent>
      </Card>

      {/* Alerts */}
      {alerts && alerts.alerts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Alertas</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {alerts.alerts.map((a, i) => (
              <div key={i} className="flex items-center gap-3 text-sm">
                <Badge className={`${severityBadge(a.severity)} border uppercase text-[10px]`}>
                  {a.severity}
                </Badge>
                <span>{a.message}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
