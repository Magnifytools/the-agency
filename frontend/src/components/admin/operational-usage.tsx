import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { operationalUsageApi } from "@/lib/api"
import type { OperationalUsage } from "@/lib/types"
import { Button } from "@/components/ui/button"

function percent(value: number | null) {
  return value == null ? "Sin base suficiente" : `${value.toLocaleString("es-ES")} %`
}

function Metric({ title, value, detail, href }: { title: string; value: string; detail: string; href: string }) {
  return (
    <article className="rounded-xl border border-border bg-background/60 p-4">
      <h3 className="text-sm font-medium">{title}</h3>
      <p className="mt-2 text-xl font-semibold">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
      <Link className="mt-3 inline-block text-xs text-brand underline" to={href}>Abrir fuente</Link>
    </article>
  )
}

export function OperationalUsagePanel({ userId }: { userId?: number }) {
  const query = useQuery<OperationalUsage>({
    queryKey: ["admin-operational-usage", userId ?? "anonymous", 30],
    queryFn: () => operationalUsageApi.get(30),
  })

  if (query.isLoading) return <section id="operational-usage" role="status" className="rounded-2xl border border-border bg-card p-6">Cargando señales operativas…</section>
  if (query.isError || !query.data) return (
    <section id="operational-usage" className="rounded-2xl border border-border bg-card p-6">
      <p role="alert">No se pudieron cargar las señales operativas.</p>
      <Button className="mt-3" variant="outline" onClick={() => query.refetch()}>Reintentar</Button>
    </section>
  )

  const data = query.data
  const date = new Date(data.as_of).toLocaleString("es-ES", { timeZone: "Europe/Madrid", dateStyle: "medium", timeStyle: "short" })
  return (
    <section id="operational-usage" className="scroll-mt-8 rounded-2xl border border-border bg-card p-6">
      <h2 className="text-base font-semibold">Señales operativas</h2>
      <p className="mt-1 text-sm text-muted-foreground">Vista administrativa de {data.window.days} días. Estado observado a {date}.</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <Metric title="Trabajo con contexto" value={percent(data.work_context.coverage_percent)} detail={`${data.work_context.with_project} con proyecto · ${data.work_context.without_project} sin proyecto`} href="/tasks" />
        <Metric title="Planificado o en espera" value={percent(data.work_planning.coverage_percent)} detail={`${data.work_planning.planned_or_waiting} de ${data.work_planning.total} tareas activas`} href="/tasks" />
        <Metric title="Incidencias" value={`${data.incidents.active} activas`} detail={`${data.incidents.snoozed} pospuestas · ${data.incidents.dismissed} descartadas · ${data.incidents.resolved_in_window} resueltas en el período`} href="/incidents" />
        <Metric title="Dailys observados" value={`${data.dailys.updates} actualizaciones`} detail={`${data.dailys.authors} autores · ${data.dailys.user_days} días-persona observados`} href="/dailys" />
        <Metric title="Comandos" value={percent(data.commands.success_percent)} detail={`${data.commands.executed} ejecutados · ${data.commands.failed} fallidos · ${data.commands.undone} deshechos`} href="/inbox" />
        <Metric title="Entregas confirmadas" value={percent(data.deliveries.confirmation_percent)} detail={`${data.deliveries.sent} enviadas · ${data.deliveries.failed} fallidas · ${data.deliveries.uncertain} inciertas`} href="/dashboard" />
      </div>
    </section>
  )
}
