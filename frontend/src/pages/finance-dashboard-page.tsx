import { useQuery } from "@tanstack/react-query"
import { financeAdvisorApi, financeForecastsApi, financeTaxesApi } from "@/lib/api"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { TrendingUp, TrendingDown, DollarSign, Calculator, Calendar } from "lucide-react"

const fmt = (n: number) => n.toLocaleString("es-ES", { style: "currency", currency: "EUR" })
const currentYear = new Date().getFullYear()

export default function FinanceDashboardPage() {
  const { data: overview } = useQuery({
    queryKey: ["advisor-overview"],
    queryFn: () => financeAdvisorApi.overview(),
  })

  const { data: runway } = useQuery({
    queryKey: ["finance-runway"],
    queryFn: () => financeForecastsApi.runway(),
  })

  const { data: taxSummary } = useQuery({
    queryKey: ["tax-summary", currentYear],
    queryFn: () => financeTaxesApi.summary(currentYear),
  })

  const { data: calendar = [] } = useQuery({
    queryKey: ["tax-calendar", currentYear],
    queryFn: () => financeTaxesApi.calendar(currentYear),
  })

  const upcomingDeadlines = calendar
    .filter((d: Record<string, unknown>) => (d.status as string) !== "pagado")
    .slice(0, 3)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Dashboard Financiero</h1>
        <p className="text-muted-foreground">Resumen financiero del mes actual</p>
      </div>

      {overview && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Card className="p-4">
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
              <TrendingUp className="h-4 w-4 text-green-500" />Ingresos mes
            </div>
            <p className="text-2xl font-bold">{fmt(overview.total_income_month)}</p>
          </Card>
          <Card className="p-4">
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
              <TrendingDown className="h-4 w-4 text-red-500" />Gastos mes
            </div>
            <p className="text-2xl font-bold">{fmt(overview.total_expenses_month)}</p>
          </Card>
          <Card className="p-4">
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
              <DollarSign className="h-4 w-4" />Beneficio neto
            </div>
            <p className={`text-2xl font-bold ${overview.net_profit_month < 0 ? "text-red-600" : "text-green-600"}`}>
              {fmt(overview.net_profit_month)}
            </p>
            <p className="text-xs text-muted-foreground">Margen: {overview.margin_pct.toFixed(1)}%</p>
          </Card>
          <Card className="p-4">
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
              <Calculator className="h-4 w-4 text-amber-500" />Impuestos pend.
            </div>
            <p className="text-2xl font-bold text-amber-600">{fmt(overview.pending_taxes)}</p>
          </Card>
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-6">
        {runway && (
          <Card className="p-5">
            <h2 className="text-lg font-semibold mb-4">Runway</h2>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Cash disponible</span>
                <span className="font-mono font-medium">{fmt(runway.current_cash)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Gasto mensual medio</span>
                <span className="font-mono font-medium">{fmt(runway.avg_monthly_burn)}</span>
              </div>
              <div className="flex justify-between border-t pt-2">
                <span className="font-medium">Runway estimado</span>
                <span className="text-xl font-bold">{runway.runway_months} meses</span>
              </div>
            </div>
          </Card>
        )}

        {taxSummary && (
          <Card className="p-5">
            <h2 className="text-lg font-semibold mb-4">Impuestos {currentYear}</h2>
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Pendiente</span>
                <span className="font-mono font-medium text-amber-600">{fmt(taxSummary.total_pending)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Pagado</span>
                <span className="font-mono font-medium text-green-600">{fmt(taxSummary.total_paid)}</span>
              </div>
              <div className="flex justify-between border-t pt-2">
                <span className="font-medium">Total</span>
                <span className="font-mono font-bold">{fmt(taxSummary.total)}</span>
              </div>
            </div>
          </Card>
        )}
      </div>

      {upcomingDeadlines.length > 0 && (
        <Card className="p-5">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Calendar className="h-5 w-5" />Proximos vencimientos
          </h2>
          <div className="space-y-2">
            {upcomingDeadlines.map((d: Record<string, unknown>, i: number) => (
              <div key={i} className="flex items-center justify-between p-3 rounded-lg border">
                <div className="flex items-center gap-3">
                  <Badge variant="secondary">{d.model as string}</Badge>
                  <span>{d.description as string}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-sm text-muted-foreground">{d.due_date as string}</span>
                  {d.tax_amount != null && <span className="font-mono">{fmt(d.tax_amount as number)}</span>}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
