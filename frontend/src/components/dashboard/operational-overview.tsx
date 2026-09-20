import { AlertTriangle, CheckSquare, Clock, Users, type LucideIcon } from "lucide-react"
import type { DashboardOverview } from "@/lib/types"
import { MetricCard } from "@/components/dashboard/metric-card"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { SkeletonCard } from "@/components/ui/skeleton"

type Props = {
  overview?: DashboardOverview
  isLoading: boolean
  isError: boolean
  onRetry: () => void
}

type Metric = {
  key: "clients" | "tasks" | "timesheet"
  icon: LucideIcon
  label: string
  value: string | number | null
  subtitle?: string
  tooltip: string
}

export function OperationalOverview({ overview, isLoading, isError, onRetry }: Props) {
  if (isLoading && !overview) {
    return <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 3 }).map((_, index) => <SkeletonCard key={index} />)}</div>
  }

  if (isError) {
    return <Card><CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6"><p role="alert" className="text-sm">No se pudo cargar la visión operativa.</p><Button type="button" variant="outline" size="sm" onClick={onRetry}>Reintentar</Button></CardContent></Card>
  }

  if (!overview) return null

  const metrics: Metric[] = [
    { key: "clients", icon: Users, label: "Clientes externos activos", value: overview.active_clients, tooltip: "Foto actual de clientes externos activos. No cambia con el mes seleccionado." },
    { key: "tasks", icon: CheckSquare, label: "Tareas del mes", value: overview.pending_tasks == null || overview.in_progress_tasks == null ? null : overview.pending_tasks + overview.in_progress_tasks, subtitle: overview.in_progress_tasks == null ? undefined : `${overview.in_progress_tasks} en curso`, tooltip: "Tareas pendientes y en curso del mes seleccionado." },
    { key: "timesheet", icon: Clock, label: overview.hours_scope === "mine" ? "Mis horas del mes" : "Horas del equipo", value: overview.hours_this_month == null ? null : `${overview.hours_this_month}h`, tooltip: overview.hours_scope === "mine" ? "Tus horas registradas en el mes seleccionado." : "Horas registradas en el mes seleccionado." },
  ]

  return <div className="space-y-2">
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {metrics.map(({ key, icon, label, value, subtitle, tooltip }) => overview.availability[key] ? <MetricCard key={key} icon={icon} label={label} value={value ?? "—"} subtitle={subtitle} tooltip={tooltip} /> : <Card key={key}><CardContent className="flex min-h-24 items-center gap-3 py-4"><AlertTriangle className="h-4 w-4 shrink-0 text-muted-foreground" /><p className="text-sm text-muted-foreground">No tienes acceso a {label.toLowerCase()}.</p></CardContent></Card>)}
    </div>
  </div>
}
