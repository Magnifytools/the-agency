import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, RefreshCw, Sparkles } from "lucide-react"
import { useAuth } from "@/context/auth-context"
import { reportPolicyApi, reportPolicyKeys, type CohortGenerateResult, type GenerationPreviewItem, type ReportScope } from "@/lib/report-policy-api"
import type { DigestTone } from "@/lib/types"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"

const reasons: Record<string, string> = {
  eligible: "Pendiente de preparar", client_inactive: "Cliente inactivo", internal_client: "Cliente interno: fuera de los resúmenes para clientes",
  policy_missing: "Falta configurar la frecuencia y el responsable", policy_disabled: "Preparación periódica desactivada",
  responsible_unavailable: "El responsable no está disponible o no puede preparar resúmenes", already_exists: "Este período ya tiene un resumen",
  policy_changed: "La configuración cambió. Actualiza la selección", permission_changed: "Los permisos cambiaron",
  period_changed: "El período cambió. Actualiza la selección", concurrent_generation: "Otra generación está en curso", generation_failed: "No se pudo generar. Puedes volver a intentarlo tras actualizar",
}
const internalStates: Record<string, string> = { pending: "En cola", sending: "En curso", sent: "Confirmado en Discord", failed: "Fallido", uncertain: "Sin confirmación", cancelled: "Cancelado", expired: "Caducado" }
const statuses = { draft: "Borrador", reviewed: "Revisado", sent: "Marcado como enviado (histórico)" }
const itemKey = (item: GenerationPreviewItem) => [item.client_id, item.policy_revision, item.period_start, item.period_end].join(":")
const selectable = (item: GenerationPreviewItem) => item.eligible && item.policy_revision !== null && !!item.period_start && !!item.period_end
function civilDate(value: string) { return new Intl.DateTimeFormat("es", { day: "numeric", month: "short", year: "numeric" }).format(new Date(`${value}T12:00:00`)) }

export function DigestCohort({ clientId }: { clientId?: number } = {}) {
  const { user, isAdmin, hasPermission } = useAuth()
  if (!user || !hasPermission("digests")) return null
  return <Cohort key={`${user.id}:${isAdmin}:${hasPermission("digests", true)}:${clientId ?? "all"}`} clientId={clientId} userId={user.id} isAdmin={isAdmin} canWrite={hasPermission("digests", true)} canViewClients={hasPermission("clients")} />
}

function Cohort({ userId, isAdmin, canWrite, canViewClients, clientId }: { userId: number; isAdmin: boolean; canWrite: boolean; canViewClients: boolean; clientId?: number }) {
  const queryClient = useQueryClient()
  const [scope, setScope] = useState<ReportScope>("mine")
  const [tone, setTone] = useState<DigestTone>("cercano")
  const [selected, setSelected] = useState<string[]>([])
  const [results, setResults] = useState<(CohortGenerateResult & { name: string })[]>([])
  const [needsRefresh, setNeedsRefresh] = useState(false)
  const [submitError, setSubmitError] = useState("")
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const query = useQuery({ queryKey: [...reportPolicyKeys.preview, userId, scope], queryFn: () => reportPolicyApi.generationPreview(scope) })
  const rows = (query.data?.items ?? []).filter(item => !clientId || item.client_id === clientId)
  const chosen = rows.filter(item => selectable(item) && selected.includes(itemKey(item)))
  const mutation = useMutation({
    retry: false,
    mutationFn: ({ items, tone }: { items: GenerationPreviewItem[]; tone: DigestTone }) => reportPolicyApi.generateCohort({
      items: items.map(item => ({ client_id: item.client_id, policy_revision: item.policy_revision!, period_start: item.period_start!, period_end: item.period_end! })), tone,
    }),
    onSuccess: (data, request) => {
      if (!alive.current) return
      setResults(data.results.map(result => ({ ...result, name: request.items.find(item => item.client_id === result.client_id)?.client_name ?? `Cliente #${result.client_id}` })))
      setSelected([])
      setSubmitError("")
      queryClient.invalidateQueries({ queryKey: ["digests"] })
      queryClient.invalidateQueries({ queryKey: reportPolicyKeys.preview })
      queryClient.invalidateQueries({ queryKey: reportPolicyKeys.external })
    },
    onError: (error) => {
      if (!alive.current) return
      setNeedsRefresh(true)
      setSubmitError(getErrorMessage(error, "No se pudo confirmar el resultado de la generación."))
    },
  })
  const busy = mutation.isPending || query.isFetching
  async function refresh() {
    const next = await query.refetch()
    if (alive.current && !next.isError) { setNeedsRefresh(false); setSubmitError("") }
  }
  return <Card>
    <CardContent className="p-4 sm:p-6 space-y-4">
      <div className="flex flex-wrap justify-between gap-3">
        <div><h2 className="font-semibold text-lg">Preparar resúmenes pendientes</h2><p className="text-sm text-muted-foreground">Selecciona los clientes que quieres preparar. Cada uno usa su frecuencia y último período cerrado.</p></div>
        <Button variant="outline" size="sm" disabled={busy} onClick={() => void refresh()}><RefreshCw className="size-4 mr-2" />Actualizar selección</Button>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        {isAdmin ? <div className="space-y-1"><Label htmlFor="cohort-scope">Responsabilidad</Label><Select id="cohort-scope" value={scope} disabled={mutation.isPending} onChange={event => { setScope(event.target.value as ReportScope); setSelected([]); setResults([]); setNeedsRefresh(false); setSubmitError("") }}><option value="mine">A mi cargo</option><option value="team">Todo el equipo</option></Select></div> : <p className="text-sm">Clientes a mi cargo</p>}
        <div className="space-y-1"><Label htmlFor="cohort-tone">Tono de los nuevos resúmenes</Label><Select id="cohort-tone" value={tone} disabled={!canWrite || mutation.isPending} onChange={event => setTone(event.target.value as DigestTone)}><option value="cercano">Cercano</option><option value="formal">Formal</option><option value="equipo">Equipo</option></Select></div>
      </div>
      {!canWrite && <p className="text-sm text-muted-foreground">Tienes acceso de lectura. Necesitas permiso para preparar resúmenes.</p>}
      {query.isPending ? <p role="status" className="text-sm flex items-center gap-2"><Loader2 className="size-4 animate-spin" />Consultando los períodos pendientes…</p> : query.isError ? <div role="alert" className="text-sm">No se pudo consultar qué clientes necesitan un resumen. <Button size="sm" variant="outline" disabled={query.isFetching} onClick={() => void refresh()}>Reintentar consulta</Button></div> : <>
        <p className="text-sm text-muted-foreground">A {civilDate(query.data.as_of)}: {rows.filter(item => item.eligible).length} pendientes · {rows.filter(item => !item.eligible).length} fuera de esta selección.{clientId ? " Solo el cliente del filtro del historial." : ""}</p>
        {rows.length === 0 && <p className="text-sm">{scope === "mine" ? "No hay clientes a tu cargo en esta selección. La frecuencia y el responsable se configuran en la ficha del cliente." : "No hay clientes en esta consulta."}</p>}
        <ul className="divide-y rounded-lg border">
          {rows.map(item => <li key={item.client_id} className="p-3 sm:p-4 flex items-start gap-3">
            <input className="mt-1 shrink-0 size-4" type="checkbox" aria-label={`Preparar ${item.client_name}`} checked={chosen.some(row => row.client_id === item.client_id)} disabled={!canWrite || busy || needsRefresh || !selectable(item) || (chosen.length >= 50 && !selected.includes(itemKey(item)))} onChange={event => setSelected(previous => event.target.checked ? [...previous, itemKey(item)] : previous.filter(key => key !== itemKey(item)))} />
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1"><h3 className="font-medium break-words">{item.client_name}</h3><span className="text-xs text-muted-foreground">{item.cadence === "weekly" ? "Semanal" : item.cadence === "monthly" ? "Mensual" : "Sin frecuencia"} · {item.responsible_name || "Sin responsable"}</span></div>
              <p className="text-sm">{item.period_start && item.period_end ? `${civilDate(item.period_start)} — ${civilDate(item.period_end)}` : "Sin período configurado"}</p>
              <p className="text-sm text-muted-foreground">{reasons[item.reason] ?? "No disponible. Actualiza la selección."}</p>
              {item.digest.latest_digest_id && <p className="text-sm"><Link className="text-primary underline underline-offset-2" to={`/digests/${item.digest.latest_digest_id}/edit`}>Ver versión #{item.digest.latest_digest_id}</Link> · {item.digest.version_count} {item.digest.version_count === 1 ? "versión" : "versiones"}{item.digest.latest_status ? ` · ${statuses[item.digest.latest_status]}` : ""}</p>}
              {item.internal_distribution.state && <p className="text-xs text-muted-foreground">Discord interno · {internalStates[item.internal_distribution.state] ?? "Estado no disponible"}{item.internal_distribution.digest_id ? ` · Versión #${item.internal_distribution.digest_id}` : ""}</p>}
              {item.digest.latest_digest_id && <p className="text-xs text-muted-foreground">Entrega al cliente · {item.external_delivery.state === "confirmed" ? `Confirmada manualmente${item.external_delivery.actor_name ? ` por ${item.external_delivery.actor_name}` : ""}${item.external_delivery.digest_id ? ` · Versión #${item.external_delivery.digest_id}` : ""}` : "Sin confirmación registrada"}</p>}
              {item.state === "newer_version_unconfirmed" && <p className="text-sm text-amber-500">La última versión aún no tiene entrega confirmada.</p>}
              {canViewClients && ["policy_missing", "policy_disabled", "responsible_unavailable"].includes(item.reason) && <Link className="inline-block text-sm text-primary underline underline-offset-2" to={`/clients/${item.client_id}?tab=resumenes`}>Ver configuración del cliente</Link>}
            </div>
          </li>)}
        </ul>
      </>}
      {submitError && <div role="alert" className="text-sm space-y-1"><p>{submitError}</p><p>Puede haber versiones ya guardadas. Actualiza la selección para comprobarlo antes de volver a generar.</p></div>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">{chosen.length} seleccionados · Máximo 50. Preparar no envía nada al cliente ni a Discord.</p>
        {canWrite && <Button disabled={!chosen.length || busy || query.isError || needsRefresh} onClick={() => { setResults([]); setSubmitError(""); mutation.mutate({ items: chosen, tone }) }}>{mutation.isPending ? <Loader2 className="size-4 mr-2 animate-spin" /> : <Sparkles className="size-4 mr-2" />}{mutation.isPending ? "Preparando…" : `Preparar selección (${chosen.length})`}</Button>}
      </div>
      {results.length > 0 && <section className="rounded-lg bg-muted p-3 space-y-2" aria-label="Resultado de la preparación" aria-live="polite"><h3 className="font-medium">Resultado de la selección</h3><ul className="space-y-2">{results.map(result => <li key={result.client_id} className="text-sm break-words"><strong>{result.name}</strong> · {result.outcome === "generated" ? "Generado" : result.outcome === "skipped" ? "Omitido" : "Fallido"}{result.reason ? ` · ${reasons[result.reason] ?? "Actualiza para comprobar el estado"}` : ""}{result.digest_id && <> · <Link className="text-primary underline underline-offset-2" to={`/digests/${result.digest_id}/edit`}>Abrir versión #{result.digest_id}</Link></>}</li>)}</ul></section>}
    </CardContent>
  </Card>
}
