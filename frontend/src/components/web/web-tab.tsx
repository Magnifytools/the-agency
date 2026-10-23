import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Link } from "react-router-dom"
import { Activity, ExternalLink, ListChecks, Pause, Play, Plus, Radar, Trash2, Zap } from "lucide-react"
import { webApi, webWatchesApi } from "@/lib/api"
import type { UptimeProbeResult, UptimeTarget } from "@/lib/types"
import { useAuth } from "@/context/auth-context"
import { getErrorMessage } from "@/lib/utils"
import { webKeys } from "@/lib/query-keys"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { UptimeStatusPill, formatInstant, formatMinutes, formatPct } from "@/components/web/uptime-status"
import { WebWatchesCard } from "@/components/web/web-watches-card"
import { WebChangesList, type ChangeListFilters } from "@/components/web/web-changes-list"
import { WebRunsCard } from "@/components/web/web-runs-card"
import { WebChangeSettingsCard } from "@/components/web/web-change-settings-card"

interface Props {
  clientId: number
  website: string | null
}

export const webUptimeKey = (clientId: number) => ["web-uptime", clientId] as const

const OUTCOME_LABEL: Record<UptimeProbeResult["outcome"], string> = {
  up: "Responde",
  down: "No responde",
  blocked: "Nos bloquea",
}

/**
 * Pestaña "Web" de la ficha. Arriba la disponibilidad (fase 1); debajo la
 * vigilancia de cambios (fase 2), que se enciende por cliente: apagada sólo se
 * ve el interruptor; encendida, URLs vigiladas, cambios sin revisar, últimos
 * barridos y, con escritura en `web`, calendario y captura.
 */
export function WebTab({ clientId, website }: Props) {
  const { hasPermission } = useAuth()
  const canWrite = hasPermission("web", true)
  const [changeFilters, setChangeFilters] = useState<ChangeListFilters>({ severity: "all", pending: true })
  const settings = useQuery({ queryKey: webKeys.settings(clientId), queryFn: () => webWatchesApi.settings(clientId) })
  return (
    <div className="space-y-4">
      <UptimeCard clientId={clientId} website={website} />
      <ChangesSwitchCard clientId={clientId} enabled={settings.data?.changes_enabled ?? null} canWrite={canWrite} />
      {settings.data?.changes_enabled && <ChangesSections clientId={clientId} canWrite={canWrite} filters={changeFilters} onFiltersChange={setChangeFilters} />}
    </div>
  )
}

function ChangesSections({ clientId, canWrite, filters, onFiltersChange }: {
  clientId: number
  canWrite: boolean
  filters: ChangeListFilters
  onFiltersChange: (filters: ChangeListFilters) => void
}) {
  return (
    <>
      <WebWatchesCard clientId={clientId} />
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
          <CardTitle className="flex items-center gap-2 text-base"><ListChecks className="h-4 w-4" /> Cambios detectados</CardTitle>
          <Link to={`/web/cambios?cliente=${clientId}`} className="text-xs text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm">
            Abrir en Cambios web
          </Link>
        </CardHeader>
        <CardContent>
          <WebChangesList clientId={clientId} filters={filters} onFiltersChange={onFiltersChange} limit={50} />
        </CardContent>
      </Card>
      <WebRunsCard clientId={clientId} />
      {canWrite && <WebChangeSettingsCard clientId={clientId} />}
    </>
  )
}

/**
 * Interruptor de la vigilancia de cambios del cliente. Apagarla no borra sus
 * URLs ni su historial: deja de barrerlas, de avisar y de contar en su estado.
 */
function ChangesSwitchCard({ clientId, enabled, canWrite }: { clientId: number; enabled: boolean | null; canWrite: boolean }) {
  const qc = useQueryClient()
  const [confirmOff, setConfirmOff] = useState(false)
  const mut = useMutation({
    mutationFn: (next: boolean) => webWatchesApi.setChangesEnabled(clientId, next),
    onSuccess: (data) => {
      qc.setQueryData(webKeys.settings(clientId), data)
      toast.success(data.changes_enabled ? "Vigilancia de cambios activada" : "Vigilancia de cambios desactivada")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  if (enabled === null) return null
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
        <CardTitle className="flex items-center gap-2 text-base"><Radar className="h-4 w-4" /> Vigilancia de cambios</CardTitle>
        {canWrite && (enabled ? (
          <Button size="sm" variant="ghost" disabled={mut.isPending} onClick={() => setConfirmOff(true)}>Desactivar</Button>
        ) : (
          <Button size="sm" disabled={mut.isPending} onClick={() => mut.mutate(true)}>
            {mut.isPending ? "Activando…" : "Activar"}
          </Button>
        ))}
      </CardHeader>
      {!enabled && (
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Compara cada día las páginas que elijas (SEO, texto, enlaces y código) y avisa de lo que cambia.
            {canWrite ? " Actívala para añadir URLs y configurarla." : " Está apagada para este cliente."}
          </p>
        </CardContent>
      )}
      <ConfirmDialog
        open={confirmOff}
        onOpenChange={setConfirmOff}
        title="¿Desactivar la vigilancia de cambios?"
        description="Sus URLs y su historial se quedan, pero deja de comprobarlas, de avisar y de contar en el estado del cliente."
        confirmLabel="Desactivar"
        onConfirm={() => {
          mut.mutate(false)
          setConfirmOff(false)
        }}
      />
    </Card>
  )
}

/**
 * Disponibilidad: si responde cada URL vigilada del cliente, su disponibilidad
 * y sus últimas caídas. Leer = ver; escribir = gestionar URLs y "Probar ahora"
 * (que no cambia el estado: sólo informa).
 */
function UptimeCard({ clientId, website }: Props) {
  const { hasPermission } = useAuth()
  const canWrite = hasPermission("web", true)
  const qc = useQueryClient()
  const queryKey = webUptimeKey(clientId)
  const [url, setUrl] = useState("")
  const [label, setLabel] = useState("")
  const [adding, setAdding] = useState(false)
  const [probes, setProbes] = useState<Record<number, UptimeProbeResult>>({})
  const [deleting, setDeleting] = useState<UptimeTarget | null>(null)

  const { data, isLoading, isError, refetch } = useQuery({ queryKey, queryFn: () => webApi.targets(clientId) })
  const refresh = () => qc.invalidateQueries({ queryKey })

  const createMut = useMutation({
    mutationFn: () => webApi.createTarget(clientId, { url, label: label || null }),
    onSuccess: () => {
      setAdding(false)
      setUrl("")
      setLabel("")
      toast.success("URL añadida. Se comprueba en el próximo minuto.")
      void refresh()
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const toggleMut = useMutation({
    mutationFn: (target: UptimeTarget) => webApi.updateTarget(clientId, target.id, { is_active: !target.is_active }),
    onSuccess: (target) => {
      toast.success(target.is_active ? "URL reanudada" : "URL pausada")
      void refresh()
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const deleteMut = useMutation({
    mutationFn: (target: UptimeTarget) => webApi.deleteTarget(clientId, target.id),
    onSuccess: () => {
      toast.success("URL borrada")
      void refresh()
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const probeMut = useMutation({
    mutationFn: (target: UptimeTarget) => webApi.probe(target.id),
    onSuccess: (result) => setProbes((prev) => ({ ...prev, [result.target_id]: result })),
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const startAdding = () => {
    setUrl(data?.targets.length ? "" : website ?? "")
    setAdding(true)
  }

  if (isLoading) return <p role="status" className="text-sm text-muted-foreground">Cargando disponibilidad…</p>
  if (isError || !data) {
    return (
      <div role="alert" className="flex items-center justify-between gap-3 text-sm">
        <span>No se pudo cargar la disponibilidad de la web.</span>
        <Button size="sm" variant="outline" onClick={() => refetch()}>Reintentar</Button>
      </div>
    )
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="h-4 w-4" /> Disponibilidad de la web
        </CardTitle>
        {canWrite && !adding && (
          <Button size="sm" variant="outline" onClick={startAdding}>
            <Plus className="h-4 w-4 mr-1" /> Añadir URL
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {!data.enabled && (
          <p className="text-sm text-amber-600">
            El monitor está apagado: las URLs se guardan, pero no se comprueban hasta encenderlo.
          </p>
        )}
        {data.enabled && !data.monitored && (
          <p className="text-sm text-muted-foreground">
            Este cliente no está activo o es interno: sus URLs no se comprueban.
          </p>
        )}

        {adding && (
          <form
            className="flex flex-col sm:flex-row gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              createMut.mutate()
            }}
          >
            <Input aria-label="URL a vigilar" placeholder="https://ejemplo.com/" value={url} onChange={(e) => setUrl(e.target.value)} required />
            <Input aria-label="Nombre (opcional)" placeholder="Home, tienda…" value={label} onChange={(e) => setLabel(e.target.value)} className="sm:max-w-[180px]" />
            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={!url.trim() || createMut.isPending}>
                {createMut.isPending ? "Añadiendo…" : "Añadir"}
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => setAdding(false)}>Cancelar</Button>
            </div>
          </form>
        )}

        {data.targets.length === 0 && !adding && (
          <p className="text-sm text-muted-foreground">
            Todavía no vigilamos ninguna URL de este cliente.
            {canWrite && website && " Empieza por su home."}
          </p>
        )}

        <ul className="space-y-3">
          {data.targets.map((target) => {
            const probe = probes[target.id]
            return (
              <li key={target.id} className="rounded-lg border border-border p-3 space-y-2" aria-label={target.label || target.url}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0 flex items-center gap-2">
                    <UptimeStatusPill status={target.status} />
                    <a href={target.url} target="_blank" rel="noopener noreferrer" className="truncate text-sm font-medium hover:underline inline-flex items-center gap-1">
                      {target.label ? `${target.label} · ` : ""}{target.url} <ExternalLink className="h-3 w-3 shrink-0" />
                    </a>
                  </div>
                  {canWrite && (
                    <div className="flex gap-1">
                      <Button size="sm" variant="outline" disabled={probeMut.isPending} onClick={() => probeMut.mutate(target)}>
                        <Zap className="h-3.5 w-3.5 mr-1" /> Probar ahora
                      </Button>
                      <Button size="sm" variant="ghost" aria-label={target.is_active ? "Pausar" : "Reanudar"} title={target.is_active ? "Pausar" : "Reanudar"} onClick={() => toggleMut.mutate(target)}>
                        {target.is_active ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                      </Button>
                      <Button size="sm" variant="ghost" aria-label="Borrar" title="Borrar" onClick={() => setDeleting(target)}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  )}
                </div>

                {target.open_outage && (
                  <p role="alert" className="text-sm text-red-400">
                    {target.open_outage.kind === "down"
                      ? `No responde desde el ${formatInstant(target.open_outage.started_at)}`
                      : `Nos bloquea desde el ${formatInstant(target.open_outage.started_at)}: no podemos comprobarla`}
                    {target.open_outage.cause_label ? ` (${target.open_outage.cause_label})` : ""}.
                  </p>
                )}

                <dl className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                  <div><dt className="text-muted-foreground">Últimas 24 h</dt><dd className="mono">{formatPct(target.uptime_24h)}</dd></div>
                  <div><dt className="text-muted-foreground">30 días</dt><dd className="mono">{formatPct(target.uptime_30d)}</dd></div>
                  <div><dt className="text-muted-foreground">Desde</dt><dd>{formatInstant(target.status_since)}</dd></div>
                  <div>
                    <dt className="text-muted-foreground">Última comprobación</dt>
                    <dd>
                      {formatInstant(target.last_checked_at)}
                      {target.last_status_code ? <span className="mono"> · {target.last_status_code}</span> : null}
                      {target.last_response_ms !== null && target.last_checked_at ? <span className="mono"> · {target.last_response_ms} ms</span> : null}
                    </dd>
                  </div>
                </dl>

                {probe && (
                  <p role="status" className="text-xs">
                    Ahora mismo: <strong>{OUTCOME_LABEL[probe.outcome]}</strong>
                    {probe.status_code ? ` · HTTP ${probe.status_code}` : ""}
                    {probe.cause_label && probe.outcome !== "up" ? ` · ${probe.cause_label}` : ""}
                    {probe.response_ms !== null ? ` · ${probe.response_ms} ms` : ""}
                    <span className="text-muted-foreground"> (no cambia el estado)</span>
                  </p>
                )}

                {target.recent_outages.length > 0 && (
                  <details className="text-xs">
                    <summary className="cursor-pointer text-muted-foreground">Últimas caídas ({target.recent_outages.length})</summary>
                    <ul className="mt-1 space-y-0.5">
                      {target.recent_outages.map((outage) => (
                        <li key={outage.id}>
                          {outage.kind === "down" ? "Caída" : "Bloqueo"} el {formatInstant(outage.started_at)} ·{" "}
                          {outage.ended_at ? `duró ${formatMinutes(outage.duration_minutes)}` : "sigue abierta"}
                          {outage.cause_label ? ` · ${outage.cause_label}` : ""}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </li>
            )
          })}
        </ul>

        <p className="text-[11px] text-muted-foreground">
          Se mira cada 5 minutos. Dos comprobaciones fallidas seguidas son una caída (avisa en Alertas y en el Slack
          del cliente); un 401/403/429 es un bloqueo, no una caída.
        </p>

        <ConfirmDialog
          open={deleting !== null}
          onOpenChange={(open) => !open && setDeleting(null)}
          title="¿Borrar esta URL?"
          description="Se borra con su historial de comprobaciones y caídas. Si sólo quieres dejar de mirarla, páusala."
          confirmLabel="Borrar"
          onConfirm={() => {
            if (deleting) deleteMut.mutate(deleting)
            setDeleting(null)
          }}
        />
      </CardContent>
    </Card>
  )
}
