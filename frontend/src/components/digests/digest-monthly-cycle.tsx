import { useEffect, useRef, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Loader2, Sparkles } from "lucide-react"
import { useAuth } from "@/context/auth-context"
import { reportPolicyApi, reportPolicyKeys, type GenerationPreviewItem } from "@/lib/report-policy-api"
import { clearDigestGeneration, isConfirmedFailure, newDigestGenerationKey, persistDigestGeneration, type CohortDigestIntent } from "@/lib/digest-generation-recovery"
import { getAgencyTimezone, parseApiInstant } from "@/lib/dates"
import { getErrorMessage } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"

// "Delivered" means a confirmed external delivery event on some version of the
// month, the same rule as the report_unsent incident. DigestStatus "sent" is a
// legacy label without evidence and does not count.
type MonthState = "missing" | "blocked" | "prepared" | "no_policy" | "weekly" | "delivered"
const ORDER: MonthState[] = ["missing", "blocked", "prepared", "no_policy", "weekly", "delivered"]
const LABELS: Record<MonthState, { text: string; variant: "destructive" | "warning" | "secondary" | "success" }> = {
  missing: { text: "Pendiente de generar", variant: "destructive" },
  blocked: { text: "Sin responsable disponible", variant: "destructive" },
  prepared: { text: "Borrador sin entregar", variant: "warning" },
  no_policy: { text: "Sin política", variant: "secondary" },
  weekly: { text: "Frecuencia semanal", variant: "secondary" },
  delivered: { text: "Entregado", variant: "success" },
}
const SKIP_REASONS: Record<string, string> = {
  already_exists: "Ya existe una versión de este mes. Abre la lista actualizada.",
  policy_changed: "La configuración del cliente cambió. Vuelve a intentarlo.",
  period_changed: "El período cambió. Vuelve a intentarlo.",
  concurrent_generation: "Otra persona lo está preparando ahora.",
  permission_changed: "Ya no tienes permiso para preparar este resumen.",
}

function monthState(item: GenerationPreviewItem): MonthState {
  if (item.reason === "policy_missing" || item.reason === "policy_disabled") return "no_policy"
  if (item.cadence !== "monthly") return "weekly"
  if (item.external_delivery.state === "confirmed") return "delivered"
  if (item.digest.latest_digest_id) return "prepared"
  if (item.reason === "responsible_unavailable") return "blocked"
  return "missing"
}

function previousMonthLabel(asOf: string) {
  const [year, month] = asOf.split("-").map(Number)
  return new Intl.DateTimeFormat("es-ES", { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(Date.UTC(year, month - 2, 1)))
}
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
  const query = useQuery({ queryKey: [...reportPolicyKeys.preview, userId, scope], queryFn: () => reportPolicyApi.generationPreview(scope) })
  // The cycle counts active external clients only.
  const rows = (query.data?.items ?? [])
    .filter(item => item.reason !== "client_inactive" && item.reason !== "internal_client")
    .map(item => ({ item, state: monthState(item) }))
    .sort((a, b) => ORDER.indexOf(a.state) - ORDER.indexOf(b.state) || a.item.client_name.localeCompare(b.item.client_name, "es"))
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
        <h2 className="font-semibold text-lg">Resúmenes de este mes</h2>
        <p className="text-sm text-muted-foreground">
          {query.data ? `Resumen de ${previousMonthLabel(query.data.as_of)} para cada cliente externo activo${isAdmin ? "" : " a tu cargo"}.` : "Resumen del mes anterior para cada cliente externo activo."}
          {" "}Cuenta como entregado cuando alguien marca la versión como entregada al cliente.
        </p>
      </div>
      {query.isPending ? <p role="status" className="text-sm flex items-center gap-2"><Loader2 className="size-4 animate-spin" />Consultando el ciclo mensual…</p>
        : query.isError ? <div role="alert" className="text-sm">No se pudo consultar el ciclo mensual. <Button size="sm" variant="outline" onClick={() => void query.refetch()}>Reintentar</Button></div>
        : rows.length === 0 ? <p className="text-sm">{isAdmin ? "No hay clientes externos activos." : "No tienes clientes a tu cargo."}</p>
        : <>
          <p className="text-sm" aria-label="Recuento del ciclo mensual"><strong className="mono">{count("delivered")} de {rows.length}</strong> entregados · {count("missing") + count("blocked")} sin preparar · {count("prepared")} sin entregar · {count("no_policy") + count("weekly")} fuera del ciclo mensual</p>
          <ul className="divide-y rounded-lg border">
            {rows.map(({ item, state }) => <li key={item.client_id} className="p-3 flex flex-wrap items-center gap-x-4 gap-y-2" data-state={state}>
              <div className="min-w-0 flex-[1_1_12rem]">
                <p className="font-medium break-words">{item.client_name}</p>
                <p className="text-xs text-muted-foreground">
                  {item.responsible_name || "Sin responsable"}
                  {state === "delivered" && ` · Entregado${item.external_delivery.actor_name ? ` por ${item.external_delivery.actor_name}` : ""}${item.external_delivery.confirmed_at ? ` el ${confirmedAt(item.external_delivery.confirmed_at)}` : ""}`}
                  {state === "delivered" && item.state === "newer_version_unconfirmed" && " · Hay una versión posterior sin confirmar"}
                  {state === "prepared" && ` · Versión #${item.digest.latest_digest_id} sin entrega confirmada${item.digest.latest_status === "sent" ? " (marcada como enviada en el sistema antiguo)" : ""}`}
                </p>
              </div>
              <Badge variant={LABELS[state].variant}>{item.reason === "policy_disabled" ? "Política desactivada" : LABELS[state].text}</Badge>
              <div className="flex gap-2">
                {(state === "prepared" || state === "delivered") && item.digest.latest_digest_id && <Link className="text-sm text-primary underline underline-offset-2" to={`/digests/${item.digest.latest_digest_id}/edit`} aria-label={`Abrir resumen de ${item.client_name}`}>Abrir</Link>}
                {state === "missing" && canWrite && item.eligible && <Button size="sm" disabled={generate.isPending} onClick={() => prepare(item)} aria-label={`Generar resumen de ${item.client_name}`}>
                  {generate.isPending && generate.variables?.items[0].client_id === item.client_id ? <Loader2 className="size-4 mr-2 animate-spin" /> : <Sparkles className="size-4 mr-2" />}Generar
                </Button>}
                {(state === "no_policy" || state === "weekly" || state === "blocked") && canViewClients && <Link className="text-sm text-primary underline underline-offset-2" to={`/clients/${item.client_id}?tab=resumenes`}>Configurar</Link>}
              </div>
            </li>)}
          </ul>
        </>}
      {error && <p role="alert" className="text-sm">{error}</p>}
    </CardContent>
  </Card>
}
