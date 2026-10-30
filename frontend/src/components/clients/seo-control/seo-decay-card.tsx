import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { clientSeoApi, tasksApi } from "@/lib/api"
import { clientSeoKeys, invalidateTaskChange } from "@/lib/query-keys"
import type { SeoDecayRow } from "@/lib/types"
import { formatDay } from "@/lib/gsc"
import { formatInt, formatPosition } from "@/lib/seo-control"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

const CAUSES: Record<SeoDecayRow["cause"], string> = {
  position: "Pierde posiciones",
  demand: "Menos búsquedas",
  ctr: "Menos clics por impresión",
}

function pathOf(url: string) {
  try {
    const parsed = new URL(url)
    return decodeURIComponent(parsed.pathname) || "/"
  } catch {
    return url
  }
}

/** Páginas muy por debajo de su mejor tramo de 28 días: cola de páginas a refrescar. */
export function SeoDecayCard({ clientId, canCreateTask, onCompare }: {
  clientId: number
  canCreateTask: boolean
  onCompare?: (page: string) => void
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const query = useQuery({
    queryKey: clientSeoKeys.decay(clientId),
    queryFn: () => clientSeoApi.decay(clientId),
    staleTime: 10 * 60_000,
  })
  const createTask = useMutation({
    mutationFn: (row: SeoDecayRow) => tasksApi.create({
      title: `Refrescar ${pathOf(row.page)}`,
      client_id: clientId,
      link_url: row.page,
      description: `Clics de los últimos 28 días: ${row.current.clicks} (su mejor tramo, ${formatDay(row.peak.start)}–${formatDay(row.peak.end)}: ${row.peak.clicks}). Motivo probable: ${CAUSES[row.cause].toLowerCase()}.`,
    }),
    onSuccess: (task) => {
      invalidateTaskChange(queryClient, { clientId })
      toast.success("Tarea creada", { action: { label: "Abrir", onClick: () => navigate(`/tasks?task=${task.id}`) } })
    },
    onError: (error) => toast.error(getErrorMessage(error, "No se pudo crear la tarea")),
  })

  const data = query.data
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Páginas que pierden tráfico</CardTitle>
        <p className="text-xs text-muted-foreground">
          Páginas con al menos un 40 % menos de clics que en su mejor tramo de 28 días (de los últimos 120). Puede ser estacional: compáralo con lo que pasó en el sector.
        </p>
      </CardHeader>
      <CardContent className="space-y-2">
        {query.isPending ? <p role="status" className="text-sm text-muted-foreground">Buscando páginas que caen…</p>
          : query.isError ? <div role="alert" className="text-sm">No se pudo calcular. <Button size="sm" variant="outline" onClick={() => void query.refetch()}><RefreshCw className="h-3.5 w-3.5 mr-1" />Reintentar</Button></div>
            : !data || data.status !== "ok" ? <p className="text-sm text-muted-foreground">Sin datos de Search Console por página.</p>
              : data.windows < 2 ? <p className="text-sm text-muted-foreground">Aún no hay bastante histórico por página (hace falta al menos 56 días).</p>
                : data.rows.length === 0 ? <p className="text-sm text-muted-foreground">Ninguna página ha caído tanto. Bien.</p>
                  : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-left text-xs text-muted-foreground">
                            <th className="py-1 pr-3 font-medium">Página</th>
                            <th className="py-1 pr-3 font-medium">Clics ahora</th>
                            <th className="py-1 pr-3 font-medium">En su mejor tramo</th>
                            <th className="py-1 pr-3 font-medium">Posición</th>
                            <th className="py-1 pr-3 font-medium">Motivo probable</th>
                            <th className="py-1 font-medium" />
                          </tr>
                        </thead>
                        <tbody>
                          {data.rows.map((row) => (
                            <tr key={row.page} className="border-t border-border align-top">
                              <td className="py-1.5 pr-3 max-w-[18rem]">
                                <a href={row.page} target="_blank" rel="noreferrer" className="break-all hover:underline">{pathOf(row.page)}</a>
                              </td>
                              <td className="py-1.5 pr-3 mono">{formatInt(row.current.clicks)} <span className="text-xs text-destructive">({row.drop_pct} %)</span></td>
                              <td className="py-1.5 pr-3 mono">{formatInt(row.peak.clicks)}<span className="block text-[11px] text-muted-foreground">{formatDay(row.peak.start)}–{formatDay(row.peak.end)}</span></td>
                              <td className="py-1.5 pr-3 mono">{formatPosition(row.peak.position)} → {formatPosition(row.current.position)}</td>
                              <td className="py-1.5 pr-3">{CAUSES[row.cause]}</td>
                              <td className="py-1.5 whitespace-nowrap text-right">
                                {onCompare && <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => onCompare(row.page)}>Comparar</Button>}
                                {canCreateTask && <Button size="sm" variant="outline" className="h-7 text-xs" disabled={createTask.isPending}
                                  aria-label={`Crear tarea para refrescar ${pathOf(row.page)}`} onClick={() => createTask.mutate(row)}>Crear tarea</Button>}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {data.total != null && data.total > data.rows.length && <p className="mt-2 text-xs text-muted-foreground">Mostramos las {data.rows.length} que más clics han perdido de {data.total}.</p>}
                      {!canCreateTask && <p className="mt-2 text-xs text-muted-foreground">Para crear tareas de refresco hace falta permiso de escritura en Tareas. <Link to="/tasks" className="underline">Ver tareas</Link></p>}
                    </div>
                  )}
      </CardContent>
    </Card>
  )
}
