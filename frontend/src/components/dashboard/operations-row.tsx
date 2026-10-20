import { Link } from "react-router-dom"
import { AlertTriangle, Euro, FileText, FolderKanban, type LucideIcon } from "lucide-react"
import type { DashboardOperations } from "@/lib/types"
import { formatCurrency } from "@/lib/format"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { InfoTooltip } from "@/components/ui/tooltip"

type Props = {
  operations?: DashboardOperations
  isError: boolean
  onRetry: () => void
}

type Item = { key: number; label: string; detail?: string | null; to: string }

type Indicator = {
  key: string
  icon: LucideIcon
  label: string
  value: string | number
  subtitle?: string
  tooltip: string
  items: Item[]
  more: { label: string; to: string }
  alert: boolean
}

function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`
}

/** Cifras de hoy, no del mes seleccionado: cada una enlaza a donde se actúa. */
export function OperationsRow({ operations, isError, onRetry }: Props) {
  if (isError) {
    return <Card><CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6"><p role="alert" className="text-sm">No se pudo cargar la operación.</p><Button type="button" variant="outline" size="sm" onClick={onRetry}>Reintentar</Button></CardContent></Card>
  }
  if (!operations) return null

  const { recurring_fee: fee, projects_at_risk: projects, clients_to_act: clients, digests_unsent: digests } = operations
  const indicators: Indicator[] = []
  if (fee) indicators.push({
    key: "fee", icon: Euro, label: "Cuota mensual recurrente", value: formatCurrency(fee.total),
    subtitle: plural(fee.clients, "cliente", "clientes"),
    tooltip: "Suma de la cuota mensual de los proyectos activos de clientes externos activos.",
    items: [], more: { label: "Ver proyectos", to: "/projects" }, alert: false,
  })
  if (projects) indicators.push({
    key: "projects", icon: FolderKanban, label: "Proyectos en riesgo", value: projects.count,
    subtitle: projects.count ? undefined : "Ninguno con cierre vencido ni horas pasadas",
    tooltip: "Proyectos activos o en planificación con el cierre vencido o con las horas del mes por encima de su techo.",
    items: projects.items.map((p) => ({ key: p.id, label: p.name, detail: p.reasons.join(" · "), to: `/projects/${p.id}` })),
    more: { label: "Ver proyectos", to: "/projects" }, alert: projects.count > 0,
  })
  if (clients) indicators.push({
    key: "clients", icon: AlertTriangle, label: "Clientes en Actuar", value: clients.count,
    subtitle: clients.count ? undefined : "Ningún cliente pide actuar",
    tooltip: "Clientes externos activos cuyo estado en la cartera es Actuar.",
    items: clients.items.map((c) => ({ key: c.id, label: c.name, detail: c.reason, to: `/clients/${c.id}` })),
    more: { label: "Ver cartera", to: "/clients" }, alert: clients.count > 0,
  })
  if (digests) indicators.push({
    key: "digests", icon: FileText, label: "Resúmenes sin entregar", value: digests.count,
    subtitle: `de ${digests.month}`,
    tooltip: "Clientes con resumen mensual sin entrega al cliente confirmada.",
    items: digests.items.map((d) => ({ key: d.id, label: d.name, to: `/digests?client_id=${d.id}&period_start=${digests.period_start}&period_end=${digests.period_end}` })),
    more: { label: "Ver resúmenes", to: "/digests" }, alert: digests.count > 0,
  })
  if (!indicators.length) return null

  return <section aria-labelledby="operations-heading" className="space-y-2">
    <h3 id="operations-heading" className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Operación · hoy</h3>
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {indicators.map(({ key, icon: Icon, label, value, subtitle, tooltip, items, more, alert }) => (
        <Card key={key} data-testid={`operations-${key}`}>
          <CardContent className="flex h-full flex-col gap-2 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="mb-2 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}<InfoTooltip content={tooltip} /></p>
                <p className={`kpi-value ${alert ? "text-red-500" : ""}`}>{value}</p>
                {subtitle && <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>}
              </div>
              <div className="rounded-[10px] bg-brand/10 p-2.5"><Icon className="h-5 w-5 text-brand" /></div>
            </div>
            {items.length > 0 && <ul className="space-y-1 text-sm">
              {items.map((item) => <li key={item.key} className="min-w-0">
                <Link to={item.to} className="block truncate font-medium hover:underline">{item.label}</Link>
                {item.detail && <p className="truncate text-xs text-muted-foreground">{item.detail}</p>}
              </li>)}
            </ul>}
            <Link to={more.to} className="mt-auto text-xs text-muted-foreground hover:text-foreground hover:underline">{more.label} →</Link>
          </CardContent>
        </Card>
      ))}
    </div>
  </section>
}
