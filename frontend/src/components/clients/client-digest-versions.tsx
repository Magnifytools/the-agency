import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { digestsApi } from "@/lib/api"
import { formatCivilDate } from "@/lib/dates"

const SHOWN = 8
const STATUS: Record<string, string> = { draft: "Borrador", reviewed: "Revisado", sent: "Marcado como enviado" }

/** Cadencia por el periodo, como el backend (`digest_periods.period_cadence`). */
function cadenceLabel(start: string, end: string): string {
  const [y, m, d] = start.split("-").map(Number)
  const first = new Date(Date.UTC(y, m - 1, d))
  const days = Math.round((Date.parse(`${end}T00:00:00Z`) - first.getTime()) / 86_400_000)
  if (first.getUTCDay() === 1 && days === 6) return "Seguimiento semanal"
  const monthEnd = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10)
  if (d === 1 && end === monthEnd) return "Informe mensual"
  return "Resumen"
}

/** Últimas versiones de resúmenes de un cliente, cada una con su enlace al editor. */
export function ClientDigestVersions({ clientId }: { clientId: number }) {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["digests", "client-versions", clientId],
    queryFn: () => digestsApi.list({ client_id: clientId, limit: SHOWN, offset: 0 }),
  })
  return (
    <section className="space-y-2" aria-label="Resúmenes del cliente">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium">Resúmenes preparados</h3>
        <Link to={`/digests?client_id=${clientId}`} className="text-xs text-brand hover:underline">Ver todos</Link>
      </div>
      {isLoading ? <p role="status" className="text-sm text-muted-foreground">Cargando resúmenes…</p>
        : isError ? <p role="alert" className="text-sm">No se pudieron cargar los resúmenes. <button className="underline" onClick={() => refetch()}>Reintentar</button></p>
        : !data?.length ? <p className="text-sm text-muted-foreground">Todavía no hay ninguno.</p>
        : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {data.map((digest) => (
              <li key={digest.id}>
                <Link to={`/digests/${digest.id}/edit`} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
                  <span>
                    <span className="font-medium">{cadenceLabel(digest.period_start, digest.period_end)}</span>
                    {" · "}{formatCivilDate(digest.period_start, { day: "numeric", month: "short" })} – {formatCivilDate(digest.period_end, { day: "numeric", month: "short", year: "numeric" })}
                  </span>
                  <span className="text-xs text-muted-foreground">{STATUS[digest.status] ?? digest.status} · #{digest.id}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
    </section>
  )
}
