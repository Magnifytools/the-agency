import { useState } from "react"
import { Link, useLocation } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Check, ExternalLink } from "lucide-react"
import { webChangesApi } from "@/lib/api"
import type { WebChange, WebChangeFilters, WebSeverity } from "@/lib/types"
import { invalidateWebReview, webKeys } from "@/lib/query-keys"
import { useAuth } from "@/context/auth-context"
import { cn, getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { formatInstant } from "@/components/web/uptime-status"
import { SEVERITY_FILTERS, htmlOnlySummary, pathOf } from "@/components/web/change-format"
import { SEVERITY_EDGE, Segmented, SeverityBadge } from "@/components/web/web-change-ui"

export interface ChangeListFilters {
  severity: WebSeverity | "all"
  /** true = sólo lo que falta por revisar. */
  pending: boolean
}

interface Props {
  /** Fijo (pestaña del cliente) o el del filtro de la página global. */
  clientId?: number
  filters: ChangeListFilters
  onFiltersChange: (filters: ChangeListFilters) => void
  /** En la lista global cada fila dice de qué cliente es. */
  showClient?: boolean
  limit?: number
}

/**
 * Lista de cambios detectados con sus dos filtros (severidad y revisado) como
 * controles segmentados. Los recuentos vienen del servidor IGNORANDO esos dos
 * filtros (lección 0decies de Vigil): "Críticos 1 · Avisos 3" no cambia al
 * pulsar uno, y por eso sirve para decidir a dónde ir.
 */
export function WebChangesList({ clientId, filters, onFiltersChange, showClient = false, limit = 200 }: Props) {
  const { hasPermission } = useAuth()
  const canWrite = hasPermission("web", true)
  const qc = useQueryClient()
  const location = useLocation()
  // Marcar todo no se deshace (no hay des-marcar): un segundo clic es barato.
  const [confirming, setConfirming] = useState(false)

  const params: WebChangeFilters = {
    ...(clientId !== undefined ? { client_id: clientId } : {}),
    ...(filters.severity !== "all" ? { severity: filters.severity } : {}),
    ...(filters.pending ? { acknowledged: false } : {}),
    limit,
  }
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: webKeys.changes(params),
    queryFn: () => webChangesApi.list(params),
  })

  const ackMut = useMutation({
    mutationFn: (change: WebChange) => webChangesApi.ack(change.id),
    onSuccess: () => {
      toast.success("Marcado como revisado")
      void invalidateWebReview(qc)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const ackAllMut = useMutation({
    // Acotado a lo que se está viendo: cliente y severidad del filtro.
    mutationFn: () => webChangesApi.ackAll({
      client_id: clientId ?? null,
      severity: filters.severity === "all" ? null : filters.severity,
    }),
    onSuccess: (result) => {
      setConfirming(false)
      toast.success(result.acknowledged === 1 ? "1 cambio revisado" : `${result.acknowledged} cambios revisados`)
      void invalidateWebReview(qc)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const change = (next: Partial<ChangeListFilters>) => {
    setConfirming(false)
    onFiltersChange({ ...filters, ...next })
  }

  const all = data?.counts
  const pending = data?.counts_pending
  // Los botones de severidad cuentan dentro del estado que se mira; los de
  // estado, dentro de la severidad. Cada grupo ignora su propio filtro.
  const severityCounts = filters.pending ? pending : all
  // Del servidor, no de la lista: la lista la corta `limit`, y "¿Marcar 200?"
  // mientras ack-all marca 600 sería mentir en la confirmación.
  const toAck = pending?.[filters.severity] ?? 0
  const changes = data?.changes ?? []
  const filterLabel = SEVERITY_FILTERS.find((f) => f.id === filters.severity)?.label.toLowerCase()

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          label="Filtrar por severidad"
          value={filters.severity}
          onChange={(severity) => change({ severity })}
          options={SEVERITY_FILTERS.map((f) => ({ ...f, count: severityCounts?.[f.id] }))}
        />
        <Segmented
          label="Filtrar por estado de revisión"
          value={filters.pending ? "pending" : "all"}
          onChange={(value) => change({ pending: value === "pending" })}
          options={[
            { id: "pending", label: "Sin revisar", count: pending?.[filters.severity] },
            // "Todo" y no "Todos": el grupo de al lado ya tiene un "Todos".
            { id: "all", label: "Todo", count: all?.[filters.severity] },
          ]}
        />
        {canWrite && toAck > 0 && (
          confirming ? (
            <span className="flex flex-wrap items-center gap-2" role="group" aria-label="Confirmar revisión en bloque">
              <span className="text-xs text-muted-foreground">¿Marcar {toAck} como revisados? No se puede deshacer.</span>
              <Button size="sm" onClick={() => ackAllMut.mutate()} disabled={ackAllMut.isPending}>Sí, marcar</Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>Cancelar</Button>
            </span>
          ) : (
            <Button size="sm" variant="outline" onClick={() => setConfirming(true)}>
              <Check className="h-3.5 w-3.5 mr-1" />
              {filters.severity === "all" ? "Marcar todo revisado" : "Marcar estos revisados"}
            </Button>
          )
        )}
      </div>

      {isLoading ? (
        <p role="status" className="text-sm text-muted-foreground">Cargando cambios…</p>
      ) : isError || !data ? (
        <div role="alert" className="flex items-center justify-between gap-3 text-sm">
          <span>No se pudieron cargar los cambios.</span>
          <Button size="sm" variant="outline" onClick={() => refetch()}>Reintentar</Button>
        </div>
      ) : changes.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm">
          {filters.pending ? (
            // Vacío por el filtro de revisado no es "no hay nada": es "no te queda nada".
            <>
              <p>{filters.severity === "all" ? "No queda nada sin revisar." : `Nada sin revisar en «${filterLabel}».`}</p>
              <p className="text-muted-foreground mt-1">
                {(all?.[filters.severity] ?? 0) > 0 ? (
                  <>
                    {all![filters.severity]} ya revisados siguen en el histórico.{" "}
                    <button type="button" className="text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm" onClick={() => change({ pending: false })}>
                      Verlos
                    </button>
                  </>
                ) : "Tampoco hay ninguno revisado: aquí no se ha detectado nada todavía."}
              </p>
            </>
          ) : filters.severity === "all" ? (
            <>
              <p>Ningún cambio detectado.</p>
              <p className="text-muted-foreground mt-1">Es lo normal: sólo se escribe cuando algo se mueve.</p>
            </>
          ) : (
            <p>
              Nada en «{filterLabel}».{" "}
              <button type="button" className="text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm" onClick={() => change({ severity: "all" })}>
                Ver todos ({all?.all ?? 0})
              </button>
            </p>
          )}
        </div>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {changes.map((c) => (
            <ChangeRow
              key={c.id}
              change={c}
              showClient={showClient}
              canWrite={canWrite}
              back={location.pathname + location.search}
              onAck={() => ackMut.mutate(c)}
              acking={ackMut.isPending && ackMut.variables?.id === c.id}
            />
          ))}
        </ul>
      )}

      {data?.truncated && (
        <p className="text-xs text-muted-foreground">Se enseñan los {changes.length} más recientes de {data.total}.</p>
      )}
    </div>
  )
}

function ChangeRow({ change: c, showClient, canWrite, back, onAck, acking }: {
  change: WebChange
  showClient: boolean
  canWrite: boolean
  back: string
  onAck: () => void
  acking: boolean
}) {
  const summary = htmlOnlySummary(c)
  const to = `/web/cambios/${c.id}`
  return (
    <li className={cn("p-3 space-y-2", !c.acknowledged_at && SEVERITY_EDGE[c.max_severity])} aria-label={c.label || c.url || c.id}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex flex-wrap items-center gap-2">
          <SeverityBadge severity={c.max_severity} />
          <Link to={to} state={{ back }} className="mono text-sm font-medium break-all hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm">
            {pathOf(c.url)}
          </Link>
          {c.url && (
            <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-muted-foreground hover:text-foreground transition-colors duration-150" title="Abrir la página">
              <ExternalLink className="h-3 w-3" />
              <span className="sr-only">Abrir {c.url}</span>
            </a>
          )}
          {c.label && <span className="text-xs text-muted-foreground">{c.label}</span>}
          {showClient && c.client_name && (
            <Link to={`/clients/${c.client_id}?tab=web`} className="text-xs text-muted-foreground hover:text-foreground hover:underline">
              {c.client_name}
            </Link>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <span className="mono text-xs text-muted-foreground">{formatInstant(c.detected_at)}</span>
          <Link to={to} state={{ back }} className="inline-flex h-8 items-center rounded-[8px] border border-border px-3 text-xs font-semibold transition-colors duration-150 hover:bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
            Ver detalle
          </Link>
          {c.acknowledged_at ? (
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" title={c.acknowledged_by_label ? `Revisado por ${c.acknowledged_by_label}` : undefined}>
              <Check className="h-3 w-3" /> Revisado
            </span>
          ) : canWrite ? (
            <Button size="sm" variant="ghost" onClick={onAck} disabled={acking}>Marcar revisado</Button>
          ) : null}
        </div>
      </div>

      {summary ? (
        <p className="text-sm">
          <span className="mono">{summary.headline}</span>
          <span className="text-muted-foreground ml-2">{summary.note}</span>
        </p>
      ) : (
        <ul className="space-y-1">
          {c.items.slice(0, 4).map((item) => (
            <li key={item.id} className="text-sm">
              <span className={cn(item.severity === "critical" && "text-red-300", item.severity === "warning" && "text-amber-300")}>
                {item.rule_label}
              </span>
              {(item.before_val || item.after_val) && (
                <span className="mono text-xs text-muted-foreground break-words">
                  {" · "}{item.before_val ?? "∅"} → {item.after_val ?? "∅"}
                </span>
              )}
            </li>
          ))}
          {c.items.length > 4 && <li className="text-xs text-muted-foreground">y {c.items.length - 4} más</li>}
        </ul>
      )}
    </li>
  )
}
