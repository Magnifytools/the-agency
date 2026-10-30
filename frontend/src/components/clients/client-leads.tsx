import { useQuery } from "@tanstack/react-query"
import { clientSeoApi } from "@/lib/api"
import { ga4Change, ga4ErrorLabel, ga4Number } from "@/lib/ga4"
import { clientSeoKeys } from "@/lib/query-keys"
import type { LeadsChange } from "@/lib/types"

const TOP = 5
const day = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString("es-ES", { day: "numeric", month: "short" })

function Change({ row }: { row: LeadsChange }) {
  const label = ga4Change(row.change_pct)
  if (label) return <span className="text-xs text-muted-foreground"> ({label})</span>
  if (row.previous === 0 && row.leads > 0) return <span className="text-xs text-muted-foreground"> (nuevo)</span>
  return null
}

/** Leads por landing (GA4, 28 días) en el bloque Resultados de la Vista general. */
export function ClientLeads({ clientId }: { clientId: number }) {
  const { data, isError } = useQuery({
    queryKey: clientSeoKeys.leads(clientId),
    queryFn: () => clientSeoApi.leads(clientId),
    staleTime: 10 * 60_000,
  })
  if (isError || !data || data.status === "no_property") return null

  return (
    <div>
      <p className="mb-0.5 text-xs font-medium">Leads por landing (GA4, 28 días)</p>
      {data.status !== "ok" || !data.total ? (
        <p className="text-xs text-muted-foreground">
          {ga4ErrorLabel(data.error_code) ?? "Se importarán en la próxima pasada diaria."}
        </p>
      ) : (
        <>
          <p className="text-sm">
            {ga4Number(data.total.leads)} leads
            <Change row={data.total} />
          </p>
          {data.landings && data.landings.length > 0 && (
            <ul className="mt-1 space-y-0.5 text-sm" aria-label="Landings con más leads">
              {data.landings.slice(0, TOP).map((row) => (
                <li key={row.landing_page} className="flex justify-between gap-2">
                  <span className="truncate" title={row.landing_page}>{row.landing_page}</span>
                  <span className="shrink-0 tabular-nums">
                    {ga4Number(row.leads)}
                    <Change row={row} />
                  </span>
                </li>
              ))}
            </ul>
          )}
          {data.channels && data.channels.some((c) => c.leads > 0) && (
            <p className="mt-1 text-xs text-muted-foreground">
              {data.channels.filter((c) => c.leads > 0).map((c) => `${c.channel}: ${ga4Number(c.leads)}`).join(" · ")}
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Eventos: {data.events.join(", ")}
            {data.end ? ` · hasta el ${day(data.end)}` : ""}
            {data.comparable === false ? " · sin datos anteriores para comparar" : ""}
          </p>
        </>
      )}
    </div>
  )
}
