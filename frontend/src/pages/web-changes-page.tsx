import { useMemo } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ListChecks } from "lucide-react"
import { webApi } from "@/lib/api"
import { Card, CardContent } from "@/components/ui/card"
import { Select } from "@/components/ui/select"
import { isSeverity } from "@/components/web/change-format"
import { WebChangesList, type ChangeListFilters } from "@/components/web/web-changes-list"

/**
 * Cambios web de todos los clientes (o de uno: `?cliente={id}`, el enlace del
 * digest de Slack y de la incidencia). Los filtros viven en la URL y no en
 * memoria: revisar es entrar en un cambio y volver, y al volver el filtro
 * tiene que seguir puesto. Sin `estado`, se abre en "Sin revisar".
 */
export default function WebChangesPage() {
  const [params, setParams] = useSearchParams()
  const rawClient = params.get("cliente")
  const clientId = rawClient && /^\d+$/.test(rawClient) ? Number(rawClient) : undefined
  const sev = params.get("sev")
  const filters: ChangeListFilters = {
    severity: isSeverity(sev) ? sev : "all",
    pending: params.get("estado") !== "todo",
  }

  const setUrl = (next: { clientId?: number; filters: ChangeListFilters }) => {
    const p = new URLSearchParams()
    if (next.clientId !== undefined) p.set("cliente", String(next.clientId))
    if (next.filters.severity !== "all") p.set("sev", next.filters.severity)
    if (!next.filters.pending) p.set("estado", "todo")
    setParams(p, { replace: true })
  }

  // Los clientes que vigila Webs (activos, no internos): los mismos que el monitor.
  const overview = useQuery({ queryKey: ["web-uptime-overview"], queryFn: webApi.overview, staleTime: 5 * 60_000 })
  const clients = useMemo(() => {
    const rows = (overview.data?.clients ?? []).map((c) => ({ id: c.client_id, name: c.client_name }))
    if (clientId !== undefined && !rows.some((c) => c.id === clientId)) rows.push({ id: clientId, name: `Cliente ${clientId}` })
    return rows.sort((a, b) => a.name.localeCompare(b.name, "es"))
  }, [overview.data, clientId])
  const current = clients.find((c) => c.id === clientId)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2"><ListChecks className="h-6 w-6" /> Cambios web</h1>
          <p className="text-sm text-muted-foreground">
            Lo que se ha movido en las páginas vigiladas de los clientes: SEO, texto, enlaces y maquetación.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="web-changes-client" className="text-xs text-muted-foreground">Cliente</label>
          <Select
            id="web-changes-client"
            className="w-auto min-w-[200px]"
            value={clientId?.toString() ?? ""}
            onChange={(e) => setUrl({ clientId: e.target.value ? Number(e.target.value) : undefined, filters })}
          >
            <option value="">Todos los clientes</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
          {current && (
            <Link to={`/clients/${current.id}?tab=web`} className="text-xs text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm">
              Ver su web
            </Link>
          )}
        </div>
      </div>

      <Card>
        <CardContent className="p-3 sm:p-4">
          <WebChangesList
            clientId={clientId}
            filters={filters}
            onFiltersChange={(next) => setUrl({ clientId, filters: next })}
            showClient={clientId === undefined}
          />
        </CardContent>
      </Card>
    </div>
  )
}
