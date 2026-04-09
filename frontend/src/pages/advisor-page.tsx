import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { financeAdvisorApi } from "@/lib/api"
import { useAuth } from "@/context/auth-context"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { AlertTriangle, Bell, CheckCircle2, ListTodo, FileText } from "lucide-react"
import { toast } from "sonner"
import { formatCurrency } from "@/lib/format"
import { FinanceTabNav } from "@/components/finance/finance-tab-nav"

export default function AdvisorPage() {
  const qc = useQueryClient()
  const { user } = useAuth()
  const isAdmin = user?.role === "admin"

  const { data: overview } = useQuery({
    queryKey: ["advisor-overview"],
    queryFn: () => financeAdvisorApi.overview(),
  })

  const { data: insights = [] } = useQuery({
    queryKey: ["advisor-insights"],
    queryFn: () => financeAdvisorApi.insights(),
  })

  const { data: tasks = [] } = useQuery({
    queryKey: ["advisor-tasks"],
    queryFn: () => financeAdvisorApi.tasks({ status: "open" }),
  })

  const dismissMut = useMutation({
    mutationFn: (id: number) => financeAdvisorApi.dismissInsight(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["advisor-insights"] }),
    onError: () => toast.error("Error al descartar insight"),
  })

  const completeTaskMut = useMutation({
    mutationFn: (id: number) => financeAdvisorApi.updateTask(id, { status: "done" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["advisor-tasks"] })
      qc.invalidateQueries({ queryKey: ["advisor-overview"] })
      toast.success("Tarea completada")
    },
  })

  const severityIcon = (severity: string) => {
    switch (severity) {
      case "critical": return <AlertTriangle className="h-5 w-5 text-red-500" />
      case "warning": return <Bell className="h-5 w-5 text-amber-500" />
      default: return <CheckCircle2 className="h-5 w-5 text-blue-500" />
    }
  }

  return (
    <div className="space-y-6">
      <FinanceTabNav />
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">Asesor Financiero <Badge variant="warning" dot={false}>Beta</Badge></h1>
        <p className="text-muted-foreground">Resumen, alertas y tareas</p>
      </div>

      {overview && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <Card className="p-4">
            <p className="text-xs text-muted-foreground">Ingresos mes</p>
            <p className="text-xl font-bold">{formatCurrency(overview.total_income_month)}</p>
          </Card>
          <Card className="p-4">
            <p className="text-xs text-muted-foreground">Gastos mes</p>
            <p className="text-xl font-bold">{formatCurrency(overview.total_expenses_month)}</p>
          </Card>
          <Card className="p-4">
            <p className="text-xs text-muted-foreground">Beneficio neto</p>
            <p className={`text-xl font-bold ${overview.net_profit_month < 0 ? "text-red-600" : "text-green-600"}`}>
              {formatCurrency(overview.net_profit_month)}
            </p>
          </Card>
          <Card className="p-4">
            <p className="text-xs text-muted-foreground">Margen</p>
            <p className="text-xl font-bold">{overview.margin_pct.toFixed(1)}%</p>
          </Card>
          <Card className="p-4">
            <p className="text-xs text-muted-foreground">Impuestos pend.</p>
            <p className="text-xl font-bold text-amber-600">{formatCurrency(overview.pending_taxes)}</p>
          </Card>
        </div>
      )}

      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Bell className="h-5 w-5" />Alertas e insights ({insights.length})
          </h2>
          {isAdmin && <GenerateInsightsButton />}
        </div>
        {insights.length > 0 && (
          <div>
          <div className="space-y-2">
            {insights.map(insight => (
              <Card key={insight.id} className="p-4 flex items-start gap-3">
                {severityIcon(insight.severity)}
                <div className="flex-1">
                  <p className="font-medium">{insight.title}</p>
                  <p className="text-sm text-muted-foreground">{insight.description}</p>
                </div>
                <div className="flex gap-2">
                  <Badge variant={insight.severity === "critical" ? "destructive" : insight.severity === "warning" ? "warning" : "secondary"}>
                    {insight.severity}
                  </Badge>
                  <Button variant="ghost" size="sm" onClick={() => dismissMut.mutate(insight.id)}>Descartar</Button>
                </div>
              </Card>
            ))}
          </div>
          </div>
        )}
      </div>

      {tasks.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
            <ListTodo className="h-5 w-5" />Tareas pendientes ({tasks.length})
          </h2>
          <div className="space-y-2">
            {tasks.map(task => (
              <Card key={task.id} className="p-4 flex items-center gap-3">
                <div className="flex-1">
                  <p className="font-medium">{task.title}</p>
                  {task.description && <p className="text-sm text-muted-foreground">{task.description}</p>}
                  {task.due_date && <p className="text-xs text-muted-foreground">Vence: {task.due_date}</p>}
                </div>
                <Badge variant={task.priority === "high" ? "destructive" : task.priority === "medium" ? "warning" : "secondary"}>
                  {task.priority}
                </Badge>
                <Button size="sm" variant="outline" onClick={() => completeTaskMut.mutate(task.id)}>
                  <CheckCircle2 className="h-4 w-4 mr-1" />Hecho
                </Button>
              </Card>
            ))}
          </div>
        </div>
      )}

      {insights.length === 0 && tasks.length === 0 && overview && (
        <Card className="p-8 text-muted-foreground">
          <div className="flex flex-col items-center mb-6">
            <CheckCircle2 className="h-12 w-12 mb-3 text-green-500" />
            <p className="text-lg font-medium">Todo en orden</p>
            <p className="text-sm">No hay alertas ni tareas pendientes.</p>
          </div>
          <div className="border-t pt-6 space-y-3">
            <p className="text-sm font-semibold text-foreground">Consejos proactivos</p>
            <ul className="space-y-2 text-sm list-disc list-inside">
              <li>Revisa el margen por cliente en el Dashboard Ejecutivo al final de cada mes.</li>
              <li>Asegúrate de que el colchón de caja cubre al menos 3 meses de gastos.</li>
              <li>Registra los costes de equipo para que el margen sea preciso.</li>
              <li>Actualiza el saldo bancario semanalmente para un runway fiable.</li>
              <li>Cierra los leads ganados/perdidos para mantener el pipeline limpio.</li>
            </ul>
          </div>
        </Card>
      )}

      {/* Fiscal Brief — admin only */}
      {isAdmin && <FiscalBriefSection />}
    </div>
  )
}


function FiscalBriefSection() {
  const now = new Date()
  const currentQ = `Q${Math.ceil((now.getMonth() + 1) / 3)}`
  const [year, setYear] = useState(now.getFullYear())
  const [quarter, setQuarter] = useState(currentQ)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [brief, setBrief] = useState<Record<string, any> | null>(null)

  const generateMut = useMutation({
    mutationFn: () => financeAdvisorApi.generateBrief(year, quarter),
    onSuccess: (data) => {
      setBrief(data.content)
      toast.success("Informe fiscal generado")
    },
    onError: () => toast.error("Error al generar informe fiscal"),
  })

  return (
    <Card className="p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <FileText className="h-5 w-5" />
          <h2 className="text-lg font-semibold">Informe fiscal IA</h2>
        </div>
        <div className="flex items-center gap-2">
          <select value={quarter} onChange={(e) => setQuarter(e.target.value)} className="rounded-md border border-border bg-background px-2 py-1 text-sm">
            <option value="Q1">Q1</option>
            <option value="Q2">Q2</option>
            <option value="Q3">Q3</option>
            <option value="Q4">Q4</option>
          </select>
          <select value={year} onChange={(e) => setYear(Number(e.target.value))} className="rounded-md border border-border bg-background px-2 py-1 text-sm">
            <option value={2025}>2025</option>
            <option value={2026}>2026</option>
            <option value={2027}>2027</option>
          </select>
          <Button onClick={() => generateMut.mutate()} disabled={generateMut.isPending} size="sm">
            {generateMut.isPending ? "Generando..." : "Generar informe"}
          </Button>
        </div>
      </div>

      {brief && (
        <div className="space-y-4 text-sm">
          <div className="bg-muted/30 rounded-lg p-4">
            <h3 className="font-semibold text-base mb-2">{brief.title}</h3>
            <p className="text-muted-foreground leading-relaxed">{brief.executive_summary}</p>
          </div>

          {brief.income_analysis && (
            <div>
              <h4 className="font-semibold mb-1">Ingresos</h4>
              <p className="text-muted-foreground">{brief.income_analysis}</p>
            </div>
          )}

          {brief.expense_analysis && (
            <div>
              <h4 className="font-semibold mb-1">Gastos</h4>
              <p className="text-muted-foreground">{brief.expense_analysis}</p>
            </div>
          )}

          {brief.tax_status && (
            <div>
              <h4 className="font-semibold mb-1">Impuestos</h4>
              <p className="text-muted-foreground">{brief.tax_status}</p>
            </div>
          )}

          {brief.alerts?.length > 0 && (
            <div>
              <h4 className="font-semibold mb-1 text-red-600">Alertas</h4>
              <ul className="space-y-1">
                {brief.alerts.map((a: string, i: number) => (
                  <li key={i} className="flex items-start gap-2">
                    <AlertTriangle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
                    <span className="text-muted-foreground">{a}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {brief.pending_actions?.length > 0 && (
            <div>
              <h4 className="font-semibold mb-1">Acciones pendientes</h4>
              <ul className="space-y-1 list-disc list-inside text-muted-foreground">
                {brief.pending_actions.map((a: string, i: number) => <li key={i}>{a}</li>)}
              </ul>
            </div>
          )}

          {brief.recommendations?.length > 0 && (
            <div>
              <h4 className="font-semibold mb-1">Recomendaciones</h4>
              <ul className="space-y-1 list-disc list-inside text-muted-foreground">
                {brief.recommendations.map((r: string, i: number) => <li key={i}>{r}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}


function GenerateInsightsButton() {
  const qc = useQueryClient()
  const mut = useMutation({
    mutationFn: financeAdvisorApi.generateInsights,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["advisor-insights"] })
      toast.success(`${data.insights_created} insights generados con IA`)
    },
    onError: () => toast.error("Error al generar insights"),
  })

  return (
    <Button variant="outline" size="sm" onClick={() => mut.mutate()} disabled={mut.isPending}>
      {mut.isPending ? "Analizando..." : "Generar insights IA"}
    </Button>
  )
}
