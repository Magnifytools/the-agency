import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { operationalUsageApi } from "@/lib/api"
import type { OperationalUsage } from "@/lib/types"
import { Button } from "@/components/ui/button"

function percent(value: number | null) {
  return value == null ? "Sin base suficiente" : `${value.toLocaleString("es-ES")} %`
}

function Metric({ title, value, detail, href, linkLabel }: { title: string; value: string; detail: string; href?: string; linkLabel?: string }) {
  return (
    <article className="rounded-xl border border-border bg-background/60 p-4">
      <h3 className="text-sm font-medium">{title}</h3>
      <p className="mt-2 text-xl font-semibold">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
      {href && <Link className="mt-3 inline-block text-xs text-brand underline" to={href}>{linkLabel}</Link>}
    </article>
  )
}

export function OperationalUsagePanel({ userId }: { userId?: number }) {
  const query = useQuery<OperationalUsage>({
    queryKey: ["admin-operational-usage", userId ?? "anonymous", 30],
    queryFn: () => operationalUsageApi.get(30),
  })
  const origins = useQuery({
    queryKey: ["admin-request-origins", userId ?? "anonymous", 30],
    queryFn: () => operationalUsageApi.origins(30),
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
      <p className="mt-1 text-sm text-muted-foreground">Trabajo e incidencias muestran el estado actual a {date}. Dailys, comandos y entregas corresponden a los últimos {data.window.days} días.</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <Metric title="Trabajo con contexto" value={percent(data.work_context.coverage_percent)} detail={`${data.work_context.with_project} con proyecto · ${data.work_context.without_project} sin proyecto. Estado actual; estar sin proyecto no implica un error.`} href="/tasks?view=all" linkLabel="Revisar tareas" />
        <Metric title="Planificado o en espera" value={percent(data.work_planning.coverage_percent)} detail={`${data.work_planning.planned_or_waiting} de ${data.work_planning.total} tareas activas. Estado actual.`} href="/tasks?view=all" linkLabel="Revisar planificación" />
        <Metric title="Incidencias" value={`${data.incidents.active} activas`} detail={`${data.incidents.snoozed} pospuestas · ${data.incidents.dismissed} descartadas ahora · ${data.incidents.resolved_in_window} resueltas en el período`} href="/incidents" linkLabel="Revisar incidencias" />
        <Metric title="Dailys observados" value={`${data.dailys.updates} actualizaciones`} detail={`${data.dailys.authors} autores · ${data.dailys.user_days} días-persona observados. Describe uso, no una obligación diaria.`} href="/dailys" linkLabel="Abrir dailys" />
        <Metric title="Comandos" value={percent(data.commands.success_percent)} detail={`${data.commands.executed} ejecutados de ${data.commands.terminal_total} intentos finalizados · ${data.commands.failed} fallidos · ${data.commands.undone} deshechos. Fuera del porcentaje: ${data.commands.needs_input} por aclarar y ${data.commands.needs_review} por revisar. Canal del recibo: ${data.commands.by_channel.app} app · ${data.commands.by_channel.extension} extensión · ${data.commands.by_channel.unknown} sin identificar. Los recibos propios se consultan en Añadir → Instrucción.`} />
        <Metric title="Entregas confirmadas" value={percent(data.deliveries.confirmation_percent)} detail={`${data.deliveries.sent} enviadas de ${data.deliveries.terminal_total} finalizadas · ${data.deliveries.failed} fallidas · ${data.deliveries.uncertain} inciertas · ${data.deliveries.expired} caducadas. Fuera del porcentaje: ${data.deliveries.pending} pendientes · ${data.deliveries.sending} en curso · ${data.deliveries.cancelled} canceladas. Cada recibo se consulta desde el envío de su resumen o aviso.`} />
      </div>
      <div className="mt-4 border-t pt-4">
        <h3 className="text-sm font-medium">Peticiones por aplicación declarada</h3>
        {origins.isPending ? <p role="status" className="mt-1 text-sm">Cargando origen de las peticiones…</p>
          : origins.isError ? <div className="mt-2"><p role="alert">No se pudo cargar el origen de las peticiones.</p><Button variant="outline" size="sm" onClick={() => origins.refetch()}>Reintentar origen</Button></div>
          : <p className="mt-1 text-sm">Web: {origins.data.find(row => row.origin === "web")?.hits ?? 0} · Extensión: {origins.data.find(row => row.origin === "extension")?.hits ?? 0} · Sin identificar: {origins.data.find(row => row.origin === "unknown")?.hits ?? 0}</p>}
        <p className="mt-1 text-xs text-muted-foreground">Últimos 30 días. Incluye lecturas y reintentos registrados; no mide personas ni acciones humanas. El histórico sin origen permanece sin identificar.</p>
      </div>
    </section>
  )
}
