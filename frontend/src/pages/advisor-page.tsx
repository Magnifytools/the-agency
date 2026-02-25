import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { financeAdvisorApi } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { AlertTriangle, Bell, CheckCircle2, ListTodo } from "lucide-react"
import { toast } from "sonner"

const fmt = (n: number) => n.toLocaleString("es-ES", { style: "currency", currency: "EUR" })

export default function AdvisorPage() {
  const qc = useQueryClient()

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
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">Asesor Financiero <Badge variant="warning" dot={false}>Beta</Badge></h1>
        <p className="text-muted-foreground">Resumen, alertas y tareas</p>
      </div>

      {overview && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <Card className="p-4">
            <p className="text-xs text-muted-foreground">Ingresos mes</p>
            <p className="text-xl font-bold">{fmt(overview.total_income_month)}</p>
          </Card>
          <Card className="p-4">
            <p className="text-xs text-muted-foreground">Gastos mes</p>
            <p className="text-xl font-bold">{fmt(overview.total_expenses_month)}</p>
          </Card>
          <Card className="p-4">
            <p className="text-xs text-muted-foreground">Beneficio neto</p>
            <p className={`text-xl font-bold ${overview.net_profit_month < 0 ? "text-red-600" : "text-green-600"}`}>
              {fmt(overview.net_profit_month)}
            </p>
          </Card>
          <Card className="p-4">
            <p className="text-xs text-muted-foreground">Margen</p>
            <p className="text-xl font-bold">{overview.margin_pct.toFixed(1)}%</p>
          </Card>
          <Card className="p-4">
            <p className="text-xs text-muted-foreground">Impuestos pend.</p>
            <p className="text-xl font-bold text-amber-600">{fmt(overview.pending_taxes)}</p>
          </Card>
        </div>
      )}

      {insights.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
            <Bell className="h-5 w-5" />Alertas e insights ({insights.length})
          </h2>
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
        <Card className="p-8 text-center text-muted-foreground">
          <CheckCircle2 className="h-12 w-12 mx-auto mb-3 text-green-500" />
          <p className="text-lg font-medium">Todo en orden</p>
          <p>No hay alertas ni tareas pendientes.</p>
        </Card>
      )}
    </div>
  )
}
