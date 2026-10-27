import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { clientSeoApi } from "@/lib/api"
import { clientSeoKeys } from "@/lib/query-keys"
import { useAuth } from "@/context/auth-context"
import { ImpactResult } from "@/components/clients/seo-control/seo-impact-card"

/**
 * "Impacto en Google" de una tarea cerrada que toca una URL: clics, impresiones
 * y posición de esa página antes y después del día en que se cerró.
 * Sólo se pide al abrir el bloque y si quien mira lee clientes.
 */
export function TaskSeoImpact({ clientId, url, completedAt }: { clientId: number; url: string; completedAt: string }) {
  const { hasPermission } = useAuth()
  const [open, setOpen] = useState(false)
  const date = completedAt.slice(0, 10)
  const params = { date, days: 28, page: url }
  const query = useQuery({
    queryKey: clientSeoKeys.impact(clientId, params),
    queryFn: () => clientSeoApi.impact(clientId, params),
    enabled: open,
    staleTime: 10 * 60_000,
    retry: false,
  })
  if (!hasPermission("clients") || !/^https?:\/\//i.test(url)) return null
  // Sin Search Console en el cliente, el bloque sobra.
  if (query.data && query.data.status === "no_property") return null
  return (
    <details onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer text-sm font-medium">Impacto en Google</summary>
      <div className="mt-2">
        {query.isPending ? <p role="status" className="text-sm text-muted-foreground">Comparando antes y después…</p>
          : query.isError ? <p role="alert" className="text-sm text-muted-foreground">No se pudo comparar ahora.</p>
            : query.data.status !== "ok" ? <p className="text-sm text-muted-foreground">Search Console de este cliente aún no tiene datos para comparar.</p>
              : <ImpactResult impact={query.data} />}
      </div>
    </details>
  )
}
