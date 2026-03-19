import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Loader2, Receipt, CheckCircle, Circle, Calendar } from "lucide-react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import type { Project } from "@/lib/types"
import { getErrorMessage } from "@/lib/utils"

interface BillableTask {
  id: number
  title: string
  status: string
  unit_cost: number
  completed: boolean
  invoiced: boolean
  invoiced_at: string | null
  completed_at: string | null
}

interface BillingSummary {
  project_id: number
  pricing_model: string
  unit_price: number
  unit_label: string
  total_tasks: number
  completed_tasks: number
  pending_invoice_count: number
  invoiced_count: number
  total_amount: number
  pending_amount: number
  invoiced_amount: number
  tasks: BillableTask[]
}

export function ProjectBillingTab({ projectId, project }: { projectId: number; project?: Project }) {
  const queryClient = useQueryClient()
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  const { data: billing, isLoading } = useQuery({
    queryKey: ["project-billing", projectId],
    queryFn: () => api.get<BillingSummary>(`/projects/${projectId}/billing-summary`).then((r: { data: BillingSummary }) => r.data),
  })

  const invoiceMutation = useMutation({
    mutationFn: (taskIds: number[]) =>
      api.post<{ invoiced_tasks: number; total_amount: number; income_id: number }>(`/projects/${projectId}/invoice-tasks`, { task_ids: taskIds }).then((r: { data: { invoiced_tasks: number; total_amount: number } }) => r.data),
    onSuccess: (data: { invoiced_tasks: number; total_amount: number }) => {
      queryClient.invalidateQueries({ queryKey: ["project-billing", projectId] })
      toast.success(`Factura creada: ${data.total_amount}€ (${data.invoiced_tasks} tareas)`)
      setSelectedIds(new Set())
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al facturar")),
  })

  const markBilledMutation = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/mark-billed`).then((r: { data: { amount: number; next_billing_date: string | null } }) => r.data),
    onSuccess: (data: { amount: number; next_billing_date: string | null }) => {
      queryClient.invalidateQueries({ queryKey: ["project-billing", projectId] })
      queryClient.invalidateQueries({ queryKey: ["project", projectId.toString()] })
      toast.success(`Facturado: ${data.amount}€${data.next_billing_date ? ` — próxima: ${data.next_billing_date}` : ""}`)
    },
    onError: (err: unknown) => toast.error(getErrorMessage(err, "Error al facturar")),
  })

  if (isLoading) {
    return <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin opacity-40" /></div>
  }

  if (!billing) return null

  const pendingTasks = billing.tasks.filter(t => t.completed && !t.invoiced)
  const invoicedTasks = billing.tasks.filter(t => t.invoiced)
  const inProgressTasks = billing.tasks.filter(t => !t.completed)

  const toggleSelect = (id: number) => {
    const next = new Set(selectedIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelectedIds(next)
  }

  const selectAllPending = () => {
    setSelectedIds(new Set(pendingTasks.map(t => t.id)))
  }

  const selectedTotal = pendingTasks
    .filter(t => selectedIds.has(t.id))
    .reduce((sum, t) => sum + t.unit_cost, 0)

  const nextDate = project?.next_billing_date ? new Date(project.next_billing_date) : null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const daysUntil = nextDate ? Math.ceil((nextDate.getTime() - today.getTime()) / (1000 * 60 * 60 * 24)) : null
  const isOverdue = daysUntil !== null && daysUntil <= 0
  const billingAmount = project?.billing_amount ?? 0

  return (
    <div className="space-y-4">
      {/* Billing Schedule */}
      {billingAmount > 0 && (
        <Card className={isOverdue ? "border-red-500/50" : daysUntil !== null && daysUntil <= 3 ? "border-amber-500/50" : ""}>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <Calendar className="w-5 h-5 text-muted-foreground" />
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{billingAmount.toFixed(2)} €</span>
                    {project?.is_recurring && <Badge variant="outline" className="text-xs">Recurrente</Badge>}
                    {isOverdue ? (
                      <Badge variant="destructive">Vencida</Badge>
                    ) : daysUntil !== null && daysUntil <= 3 ? (
                      <Badge variant="warning">En {daysUntil} días</Badge>
                    ) : nextDate ? (
                      <Badge variant="success">Al día</Badge>
                    ) : null}
                  </div>
                  {nextDate && (
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Próxima factura: {nextDate.toLocaleDateString("es-ES")}
                      {project?.last_billed_date && ` — Última: ${new Date(project.last_billed_date).toLocaleDateString("es-ES")}`}
                    </p>
                  )}
                </div>
              </div>
              <Button
                size="sm"
                onClick={() => markBilledMutation.mutate()}
                disabled={markBilledMutation.isPending}
              >
                {markBilledMutation.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Receipt className="w-4 h-4 mr-2" />}
                Marcar facturado
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Total tareas</p>
            <p className="text-2xl font-bold">{billing.total_tasks}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Completadas</p>
            <p className="text-2xl font-bold">{billing.completed_tasks}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Pendiente facturar</p>
            <p className="text-2xl font-bold text-yellow-400">{billing.pending_amount.toFixed(2)} €</p>
            <p className="text-xs text-muted-foreground">{billing.pending_invoice_count} {billing.unit_label}s</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground uppercase tracking-wider">Facturado</p>
            <p className="text-2xl font-bold text-green-400">{billing.invoiced_amount.toFixed(2)} €</p>
            <p className="text-xs text-muted-foreground">{billing.invoiced_count} {billing.unit_label}s</p>
          </CardContent>
        </Card>
      </div>

      {/* Pending invoice */}
      {pendingTasks.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">Pendientes de facturar</CardTitle>
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" onClick={selectAllPending}>
                  Seleccionar todo
                </Button>
                {selectedIds.size > 0 && (
                  <Button
                    size="sm"
                    onClick={() => invoiceMutation.mutate(Array.from(selectedIds))}
                    disabled={invoiceMutation.isPending}
                  >
                    {invoiceMutation.isPending ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <Receipt className="w-4 h-4 mr-2" />
                    )}
                    Facturar {selectedIds.size} ({selectedTotal.toFixed(2)} €)
                  </Button>
                )}
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-1">
              {pendingTasks.map(task => (
                <div
                  key={task.id}
                  className={`flex items-center justify-between py-2 px-3 rounded cursor-pointer hover:bg-muted/50 ${selectedIds.has(task.id) ? 'bg-muted' : ''}`}
                  onClick={() => toggleSelect(task.id)}
                >
                  <div className="flex items-center gap-3">
                    {selectedIds.has(task.id) ? (
                      <CheckCircle className="w-4 h-4 text-primary" />
                    ) : (
                      <Circle className="w-4 h-4 text-muted-foreground" />
                    )}
                    <span className="text-sm">{task.title}</span>
                  </div>
                  <span className="text-sm font-medium">{task.unit_cost.toFixed(2)} €</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Invoiced */}
      {invoicedTasks.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Facturado</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1">
              {invoicedTasks.map(task => (
                <div key={task.id} className="flex items-center justify-between py-2 px-3">
                  <div className="flex items-center gap-3">
                    <CheckCircle className="w-4 h-4 text-green-400" />
                    <span className="text-sm text-muted-foreground">{task.title}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm">{task.unit_cost.toFixed(2)} €</span>
                    <Badge variant="success" className="text-xs">Facturado</Badge>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* In progress */}
      {inProgressTasks.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">En progreso</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1">
              {inProgressTasks.map(task => (
                <div key={task.id} className="flex items-center justify-between py-2 px-3">
                  <div className="flex items-center gap-3">
                    <Circle className="w-4 h-4 text-muted-foreground" />
                    <span className="text-sm text-muted-foreground">{task.title}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground">{task.unit_cost.toFixed(2)} €</span>
                    <Badge variant="outline" className="text-xs">{task.status}</Badge>
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
