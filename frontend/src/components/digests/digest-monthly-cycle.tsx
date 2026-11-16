import { useEffect, useRef, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, Sparkles } from "lucide-react"
import { toast } from "sonner"
import { useAuth } from "@/context/auth-context"
import { CADENCE_LABEL, previewItemKey, reportPolicyApi, reportPolicyKeys, type GenerationPreviewItem } from "@/lib/report-policy-api"
import { clearDigestGeneration, isConfirmedFailure, newDigestGenerationKey, persistDigestGeneration, type CohortDigestIntent } from "@/lib/digest-generation-recovery"
import { getAgencyTimezone, parseApiInstant } from "@/lib/dates"
import { localReportHref } from "@/lib/local-report"
import { getErrorMessage } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

// "Para entregar": one row per active external client and cadence that is on
// (monthly report for last month, weekly follow-up for the last closed week).
// "Delivered" means a confirmed external delivery event on some version of the
// period, the same rule as the report_unsent incident. DigestStatus "sent" is a
// legacy label without evidence and does not count. A client with an SEO local
// report gets its monthly row from that report (its tab), not from a digest.
// A skipped period (vacaciones, ya no se hace) is settled: nothing is expected.
type MonthState = "missing" | "blocked" | "prepared" | "delivered" | "skipped"
const ORDER: MonthState[] = ["missing", "blocked", "prepared", "delivered", "skipped"]
const LABELS: Record<MonthState, { text: string; variant: "destructive" | "warning" | "secondary" | "success" }> = {
  missing: { text: "Pendiente de generar", variant: "destructive" },
  blocked: { text: "Sin responsable disponible", variant: "destructive" },
  prepared: { text: "Borrador sin entregar", variant: "warning" },
  delivered: { text: "Entregado", variant: "success" },
  skipped: { text: "Saltado", variant: "secondary" },
}
const SKIP_PRESETS = ["Vacaciones", "Este periodo no se hace"]
const SKIP_REASONS: Record<string, string> = {
  already_exists: "Ya existe una versión de este mes. Abre la lista actualizada.",
  policy_changed: "La configuración del cliente cambió. Vuelve a intentarlo.",
  period_changed: "El período cambió. Vuelve a intentarlo.",
  concurrent_generation: "Otra persona lo está preparando ahora.",
  permission_changed: "Ya no tienes permiso para preparar este resumen.",
}

function monthState(item: GenerationPreviewItem): MonthState {
  if (item.skip) return "skipped"
  if (item.local_report && item.reason !== "responsible_unavailable") {
    return item.local_report.delivered_at ? "delivered" : item.local_report.report_id ? "prepared" : "missing"
  }
  if (item.external_delivery.state === "confirmed") return "delivered"
  if (item.digest.latest_digest_id) return "prepared"
  if (item.reason === "responsible_unavailable") return "blocked"
  return "missing"
}

function previousMonthLabel(asOf: string) {
  const [year, month] = asOf.split("-").map(Number)
  return new Intl.DateTimeFormat("es-ES", { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(Date.UTC(year, month - 2, 1)))
}
function periodLabel(item: GenerationPreviewItem) {
  if (!item.period_start || !item.period_end) return ""
  const day = (value: string) => new Date(`${value}T12:00:00Z`)
  if (item.cadence === "monthly") return new Intl.DateTimeFormat("es-ES", { month: "long", year: "numeric", timeZone: "UTC" }).format(day(item.period_start))
  const short = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short", timeZone: "UTC" })
  return `${short.format(day(item.period_start))} – ${short.format(day(item.period_end))}`
}
// Un cliente con las dos cadencias tiene dos filas: la semanal se nombra aparte.
const rowName = (item: GenerationPreviewItem) => item.cadence === "weekly" ? `${item.client_name} (semanal)` : item.client_name
const confirmedAt = (value: string) => parseApiInstant(value).toLocaleDateString("es-ES", { timeZone: getAgencyTimezone(), day: "numeric", month: "short" })

export function DigestMonthlyCycle() {
  const { user, isAdmin, hasPermission } = useAuth()
  if (!user || !hasPermission("digests")) return null
  return <MonthlyCycle userId={user.id} isAdmin={isAdmin} canWrite={hasPermission("digests", true)} canViewClients={hasPermission("clients")} />
}

function MonthlyCycle({ userId, isAdmin, canWrite, canViewClients }: { userId: number; isAdmin: boolean; canWrite: boolean; canViewClients: boolean }) {
  const scope = isAdmin ? "team" : "mine"
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const [error, setError] = useState("")
  const [skipping, setSkipping] = useState<GenerationPreviewItem | null>(null)
  const [skipReason, setSkipReason] = useState("")
  const query = useQuery({ queryKey: [...reportPolicyKeys.preview, userId, scope], queryFn: () => reportPolicyApi.generationPreview(scope) })
  // Active external clients, one row per cadence that is on.
  const rows = (query.data?.items ?? [])
    .filter(item => item.cadence !== null && item.reason !== "client_inactive" && item.reason !== "internal_client")
    .map(item => ({ item, state: monthState(item) }))
    .sort((a, b) => ORDER.indexOf(a.state) - ORDER.indexOf(b.state)
      || a.item.client_name.localeCompare(b.item.client_name, "es")
      || (a.item.cadence === "monthly" ? -1 : 1) - (b.item.cadence === "monthly" ? -1 : 1))
  const count = (state: MonthState) => rows.filter(row => row.state === state).length

  const generate = useMutation({
    retry: false,
    // Persisted like a cohort, so an unconfirmed answer is recovered by the
    // cohort panel after a reload instead of creating a duplicate version.
    mutationFn: (intent: CohortDigestIntent) => reportPolicyApi.generateCohort({ items: intent.items, tone: intent.tone }),
    onSuccess: (data, intent) => {
      clearDigestGeneration(userId, intent.operation_key)
      queryClient.invalidateQueries({ queryKey: reportPolicyKeys.preview })
      queryClient.invalidateQueries({ queryKey: ["digests"] })
      queryClient.invalidateQueries({ queryKey: ["incidents"] })
      if (!alive.current) return
      const result = data.results[0]
      if (result?.outcome === "generated" && result.digest_id) navigate(`/digests/${result.digest_id}/edit`)
      else setError(SKIP_REASONS[result?.reason ?? ""] ?? "No se pudo preparar el resumen. Vuelve a intentarlo.")
    },
    onError: (failure, intent) => {
      if (isConfirmedFailure(failure)) clearDigestGeneration(userId, intent.operation_key)
      if (!alive.current) return
      setError(isConfirmedFailure(failure) ? getErrorMessage(failure, "No se pudo preparar el resumen.") : "No se pudo confirmar si se preparó. Recarga la página para comprobarlo sin duplicar versiones.")
    },
  })
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: reportPolicyKeys.preview })
    queryClient.invalidateQueries({ queryKey: ["incidents"] })
    queryClient.invalidateQueries({ queryKey: ["clients"] })
  }
  const unskip = useMutation({
    mutationFn: (skipId: number) => reportPolicyApi.unskipPeriod(skipId),
    onSuccess: () => toast.success("Vuelve a estar pendiente"),
    onError: (failure) => toast.error(getErrorMessage(failure, "No se pudo volver a pendiente")),
    onSettled: refresh,
  })
  const skip = useMutation({
    mutationFn: ({ item, reason }: { item: GenerationPreviewItem; reason: string }) => reportPolicyApi.skipPeriod({
      client_id: item.client_id, period_start: item.period_start!, period_end: item.period_end!, reason,
    }),
    onSuccess: (saved, { item }) => {
      setSkipping(null)
      toast.success(`${rowName(item)}: ${periodLabel(item)} saltado`, {
        action: { label: "Deshacer", onClick: () => unskip.mutate(saved.id) },
      })
    },
    onError: (failure) => toast.error(getErrorMessage(failure, "No se pudo saltar el periodo")),
    onSettled: refresh,
  })
  const openSkip = (item: GenerationPreviewItem) => { setSkipReason(""); setSkipping(item) }

  function prepare(item: GenerationPreviewItem) {
    const intent: CohortDigestIntent = {
      kind: "cohort",
      operation_key: newDigestGenerationKey(),
      tone: "cercano",
      items: [{ generation_key: newDigestGenerationKey(), client_id: item.client_id, policy_revision: item.policy_revision!, period_start: item.period_start!, period_end: item.period_end! }],
    }
    if (!persistDigestGeneration(userId, intent)) {
      setError("El navegador no pudo guardar la clave de recuperación. No se ha preparado nada.")
      return
    }
    setError("")
    generate.mutate(intent)
  }

  return <Card>
    <CardContent className="p-4 sm:p-6 space-y-4">
      <div>
        <h2 className="font-semibold text-lg">Para entregar</h2>
        <p className="text-sm text-muted-foreground">
          {query.data ? `Informe de ${previousMonthLabel(query.data.as_of)} y seguimiento de la última semana cerrada de cada cliente${isAdmin ? "" : " a tu cargo"} que los tiene activados.` : "Informe del mes anterior y seguimiento de la última semana cerrada de cada cliente que los tiene activados."}
          {" "}Cuenta como entregado cuando alguien lo marca como entregado al cliente. Si un periodo no se va a entregar (vacaciones, ya no se hace), sáltalo: deja de avisar.
        </p>
      </div>
      {query.isPending ? <p role="status" className="text-sm flex items-center gap-2"><Loader2 className="size-4 animate-spin" />Consultando qué hay que entregar…</p>
        : query.isError ? <div role="alert" className="text-sm">No se pudo consultar qué hay que entregar. <Button size="sm" variant="outline" onClick={() => void query.refetch()}>Reintentar</Button></div>
        : rows.length === 0 ? <p className="text-sm">{isAdmin ? "Ningún cliente tiene activado el informe mensual ni el seguimiento semanal." : "Ningún cliente a tu cargo tiene activado el informe mensual ni el seguimiento semanal."}</p>
        : <>
          <p className="text-sm" aria-label="Recuento de lo que hay que entregar"><strong className="mono">{count("delivered")} de {rows.length}</strong> entregados · {count("missing") + count("blocked")} sin preparar · {count("prepared")} sin entregar{count("skipped") > 0 && ` · ${count("skipped")} saltados`}</p>
          <ul className="divide-y rounded-lg border">
            {rows.map(({ item, state }) => <li key={previewItemKey(item)} className="p-3 flex flex-wrap items-center gap-x-4 gap-y-2" data-state={state}>
              <div className="min-w-0 flex-[1_1_12rem]">
                <p className="font-medium break-words">{item.client_name}</p>
                <p className="text-xs text-muted-foreground">
                  {item.local_report ? "Informe SEO local" : item.cadence && CADENCE_LABEL[item.cadence]}{periodLabel(item) && ` · ${periodLabel(item)}`} · {item.responsible_name || "Sin responsable"}
                  {state === "delivered" && item.local_report && ` · Entregado${item.local_report.delivered_by_name ? ` por ${item.local_report.delivered_by_name}` : ""}${item.local_report.delivered_at ? ` el ${confirmedAt(item.local_report.delivered_at)}` : ""}`}
                  {state === "delivered" && !item.local_report && ` · Entregado${item.external_delivery.actor_name ? ` por ${item.external_delivery.actor_name}` : ""}${item.external_delivery.confirmed_at ? ` el ${confirmedAt(item.external_delivery.confirmed_at)}` : ""}`}
                  {state === "delivered" && item.state === "newer_version_unconfirmed" && " · Hay una versión posterior sin confirmar"}
                  {state === "prepared" && item.local_report && " · Ábrelo, genéralo y márcalo como entregado"}
                  {state === "prepared" && !item.local_report && ` · Ábrelo, revísalo y márcalo como entregado${item.digest.latest_status === "sent" ? " (marcado como enviado en el sistema antiguo)" : ""}`}
                  {state === "skipped" && item.skip && ` · Saltado${item.skip.skipped_by_name ? ` por ${item.skip.skipped_by_name}` : ""}${item.skip.skipped_at ? ` el ${confirmedAt(item.skip.skipped_at)}` : ""}: ${item.skip.reason}`}
                </p>
              </div>
              <Badge variant={LABELS[state].variant}>{LABELS[state].text}</Badge>
              <div className="flex gap-2">
                {item.local_report && state !== "blocked" && canViewClients && <Link className="text-sm text-primary underline underline-offset-2" to={item.local_report.report_id ? localReportHref(item.client_id, item.local_report.report_id) : `/clients/${item.client_id}?tab=informe_local`} aria-label={`Abrir informe SEO local de ${item.client_name}`}>{state === "missing" ? "Preparar" : "Abrir"}</Link>}
                {!item.local_report && (state === "prepared" || state === "delivered") && item.digest.latest_digest_id && <Link className="text-sm text-primary underline underline-offset-2" to={`/digests/${item.digest.latest_digest_id}/edit`} aria-label={`Abrir resumen de ${rowName(item)}`}>Abrir</Link>}
                {state === "missing" && !item.local_report && canWrite && item.eligible && <Button size="sm" disabled={generate.isPending} onClick={() => prepare(item)} aria-label={`Generar resumen de ${rowName(item)}`}>
                  {generate.isPending && generate.variables?.items[0].client_id === item.client_id && generate.variables?.items[0].period_start === item.period_start ? <Loader2 className="size-4 mr-2 animate-spin" /> : <Sparkles className="size-4 mr-2" />}Generar
                </Button>}
                {state === "blocked" && canViewClients && <Link className="text-sm text-primary underline underline-offset-2" to={`/clients/${item.client_id}?tab=resumenes`}>Configurar</Link>}
                {(state === "missing" || state === "prepared") && canWrite && item.period_start && item.period_end && <Button size="sm" variant="ghost" disabled={skip.isPending} onClick={() => openSkip(item)} aria-label={`Saltar ${periodLabel(item)} de ${rowName(item)}`}>Saltar</Button>}
                {state === "skipped" && canWrite && item.skip && <Button size="sm" variant="outline" disabled={unskip.isPending} onClick={() => unskip.mutate(item.skip!.id)} aria-label={`Volver a pendiente ${periodLabel(item)} de ${rowName(item)}`}>Volver a pendiente</Button>}
              </div>
            </li>)}
          </ul>
        </>}
      {error && <p role="alert" className="text-sm">{error}</p>}
      <Dialog open={skipping !== null} onOpenChange={(open) => { if (!open) setSkipping(null) }}>
        <DialogHeader><DialogTitle>{skipping ? `Saltar ${periodLabel(skipping)} de ${rowName(skipping)}` : "Saltar periodo"}</DialogTitle></DialogHeader>
        <form className="space-y-3" onSubmit={(event) => {
          event.preventDefault()
          if (skipping && skipReason.trim()) skip.mutate({ item: skipping, reason: skipReason.trim() })
        }}>
          <p className="text-sm text-muted-foreground">Deja de estar pendiente: no avisa, no cuenta como sin entregar y no empeora el estado del cliente. Se puede volver a pendiente.</p>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Motivos frecuentes">
            {SKIP_PRESETS.map((preset) => <Button key={preset} type="button" size="sm" variant={skipReason === preset ? "secondary" : "outline"} onClick={() => setSkipReason(preset)}>{preset}</Button>)}
          </div>
          <div className="space-y-1">
            <Label htmlFor="skip-reason">Motivo</Label>
            <Input id="skip-reason" value={skipReason} maxLength={300} onChange={(event) => setSkipReason(event.target.value)} placeholder="Por qué no se entrega este periodo" />
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setSkipping(null)}>Cancelar</Button>
            <Button type="submit" disabled={!skipReason.trim() || skip.isPending}>{skip.isPending ? "Saltando…" : "Saltar periodo"}</Button>
          </div>
        </form>
      </Dialog>
    </CardContent>
  </Card>
}
