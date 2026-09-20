import { useId, useState } from "react"
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import axios from "axios"
import { Link } from "react-router-dom"
import { AlertTriangle, Clock3, ExternalLink, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { getErrorMessage } from "@/lib/utils"
import { incidentKeys, incidentsApi, type Incident, type IncidentDecisionAction, type IncidentState } from "@/lib/incidents-api"

const stateLabels: Record<IncidentState, string> = {
  active: "Pendientes",
  snoozed: "Pospuestos",
  dismissed: "Descartados",
  resolved: "Resueltos",
}

const severityClasses = {
  info: "bg-sky-500/10 text-foreground",
  warning: "bg-amber-500/10 text-foreground",
  critical: "bg-destructive/10 text-destructive",
}

const severityLabels = { info: "Información", warning: "Atención", critical: "Crítica" }
const resolutionLabels: Record<string, string> = {
  condition_cleared: "La condición dejó de cumplirse.",
  permission_lost: "La fuente ya no está disponible para ti.",
}

function isConflict(error: unknown) {
  return axios.isAxiosError(error) && error.response?.status === 409
}

function isUncertain(error: unknown) {
  return axios.isAxiosError(error) && error.code !== "ERR_CANCELED" && (!error.response || error.response.status >= 500)
}

function conflictMessage(error: unknown) {
  if (!isConflict(error)) return null
  const detail = (error as { response?: { data?: { detail?: { current?: { state?: IncidentState } } } } }).response?.data?.detail
  return detail?.current?.state
    ? `Este aviso cambió a «${stateLabels[detail.current.state]}» en otro sitio. Se ha actualizado la lista.`
    : "Este aviso cambió en otro sitio. Se ha actualizado la lista."
}

function localInputToInstant(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

export function IncidentInbox({ userId, compact = false, onNavigate }: { userId: number; compact?: boolean; onNavigate?: () => void }) {
  const queryClient = useQueryClient()
  const id = useId()
  const headingId = `incidents-${id}`
  const [state, setState] = useState<IncidentState>("active")
  const [snoozeFor, setSnoozeFor] = useState<number | null>(null)
  const [snoozeUntil, setSnoozeUntil] = useState("")
  const [dismissFor, setDismissFor] = useState<number | null>(null)
  const [dismissReason, setDismissReason] = useState("")
  const [decisionError, setDecisionError] = useState<string | null>(null)
  const [mustRefresh, setMustRefresh] = useState(false)

  const incidentsQuery = useInfiniteQuery({
    queryKey: incidentKeys.list(userId, compact ? "active" : state, compact ? 5 : 30),
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) => incidentsApi.list({ state: compact ? "active" : state, cursor: pageParam, limit: compact ? 5 : 30 }),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    refetchInterval: compact || (!snoozeFor && !dismissFor && !mustRefresh) ? 30_000 : false,
    refetchIntervalInBackground: false,
  })
  const incidents = (incidentsQuery.data?.pages.flatMap((page) => page.items) ?? []).slice(0, compact ? 5 : undefined)
  const { fetchNextPage } = incidentsQuery

  const decisionMutation = useMutation({
    mutationFn: ({ incident, action, until, reason }: { incident: Incident; action: IncidentDecisionAction; until?: string | null; reason?: string | null }) =>
      incidentsApi.decide(incident.id, { revision: incident.revision, action, until, reason }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: incidentKeys.all(userId) })
      setDecisionError(null)
      setMustRefresh(false)
      setSnoozeFor(null)
      setDismissFor(null)
      setSnoozeUntil("")
      setDismissReason("")
    },
    onError: (error) => {
      if (isConflict(error)) {
        setMustRefresh(true)
        setDecisionError(conflictMessage(error))
        void refresh()
        return
      }
      if (isUncertain(error)) {
        setMustRefresh(true)
        setDecisionError("No se pudo confirmar si se aplicó la decisión. Actualiza la lista antes de tomar otra decisión.")
        return
      }
      setDecisionError(getErrorMessage(error, "No se pudo guardar la decisión."))
    },
  })

  const refresh = async () => {
    const result = await incidentsQuery.refetch()
    if (result.isSuccess) {
      setMustRefresh(false)
      setDecisionError(null)
      setSnoozeFor(null)
      setDismissFor(null)
      setSnoozeUntil("")
      setDismissReason("")
    } else {
      setDecisionError("No se pudieron actualizar las alertas. Sigue bloqueada cualquier decisión hasta conseguir una actualización.")
    }
  }

  const changeState = (nextState: IncidentState) => {
    setState(nextState)
    setSnoozeFor(null)
    setDismissFor(null)
    setSnoozeUntil("")
    setDismissReason("")
  }

  const openSnooze = (incidentId: number) => {
    setSnoozeFor(snoozeFor === incidentId ? null : incidentId)
    setDismissFor(null)
    setSnoozeUntil("")
    setDismissReason("")
  }

  const openDismiss = (incidentId: number) => {
    setDismissFor(dismissFor === incidentId ? null : incidentId)
    setSnoozeFor(null)
    setSnoozeUntil("")
    setDismissReason("")
  }

  const decide = (incident: Incident, action: IncidentDecisionAction, until?: string | null, reason?: string | null) => {
    if (decisionMutation.isPending || mustRefresh) return
    decisionMutation.mutate({ incident, action, until, reason })
  }

  const submitSnooze = (incident: Incident) => {
    const until = localInputToInstant(snoozeUntil)
    if (!until) {
      setDecisionError("Indica un instante válido para posponer el aviso.")
      return
    }
    decide(incident, "snooze", until)
  }

  const submitDismiss = (incident: Incident) => {
    const reason = dismissReason.trim()
    if (!reason) {
      setDecisionError("Indica el motivo para descartar el aviso.")
      return
    }
    decide(incident, "dismiss", null, reason)
  }

  return (
    <section aria-labelledby={headingId} className="space-y-4">
      {!compact && (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 id={headingId} className="text-2xl font-bold">Alertas</h1>
            <p className="text-sm text-muted-foreground">Revisa condiciones que requieren una decisión. Abrir el detalle no resuelve el aviso.</p>
          </div>
          <div className="flex gap-2">
            <div className="min-w-40">
              <Label htmlFor={`incident-state-${id}`} className="sr-only">Estado</Label>
              <Select id={`incident-state-${id}`} value={state} onChange={(event) => changeState(event.target.value as IncidentState)} disabled={decisionMutation.isPending}>
                {(Object.keys(stateLabels) as IncidentState[]).map((value) => <option key={value} value={value}>{stateLabels[value]}</option>)}
              </Select>
            </div>
            <Button type="button" variant="outline" onClick={() => void refresh()} isLoading={incidentsQuery.isRefetching} aria-label="Actualizar alertas">
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}

      {decisionError && !compact && (
        <div role="alert" className="flex flex-wrap items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-foreground">
          <AlertTriangle className="h-4 w-4 text-destructive" aria-hidden="true" />
          <span className="flex-1">{decisionError}</span>
          <Button type="button" size="sm" variant="outline" onClick={() => void refresh()} isLoading={incidentsQuery.isRefetching}>Actualizar</Button>
        </div>
      )}

      {compact && incidents.length > 0 && <h2 id={headingId} className="text-sm font-semibold">Alertas pendientes</h2>}
      {incidentsQuery.isLoading ? <p className="text-sm text-muted-foreground">Cargando alertas…</p> : incidentsQuery.isError ? (
        <div role="alert" className="rounded-lg border border-destructive/40 p-4 text-sm">No se pudieron cargar las alertas. <button type="button" className="underline" onClick={() => void refresh()}>Reintentar</button></div>
      ) : incidents.length === 0 ? compact ? (
        <p className="text-sm text-muted-foreground">Sin alertas pendientes · <Link to="/incidents" onClick={onNavigate} className="text-brand underline-offset-4 hover:underline">Ver alertas</Link></p>
      ) : (
        <Card><CardContent className="p-5 text-sm text-muted-foreground">No hay alertas en «{stateLabels[state]}».</CardContent></Card>
      ) : (
        <div className="space-y-3">
          {incidents.map((incident) => compact ? (
            <Link key={incident.id} to={incident.href} onClick={onNavigate} className="block rounded-lg border border-border px-3 py-2 hover:bg-muted/50">
              <p className="text-sm font-medium">{incident.title}</p>
              {incident.message && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{incident.message}</p>}
            </Link>
          ) : (
            <Card key={incident.id}>
              <CardContent className="space-y-3 p-4 sm:p-5">
                <div className="flex items-start gap-3">
                  <span className={`mt-0.5 rounded-full px-2 py-0.5 text-xs font-semibold ${incident.state === "active" ? severityClasses[incident.severity] : "bg-muted text-muted-foreground"}`}>{incident.state === "active" ? severityLabels[incident.severity] : ({ snoozed: "Pospuesto", dismissed: "Descartado", resolved: "Resuelto" }[incident.state])}</span>
                  <div className="min-w-0 flex-1">
                    <h2 className="font-semibold">{incident.title}</h2>
                    {incident.message && <p className="mt-1 text-sm text-muted-foreground">{incident.message}</p>}
                    <p className="mt-1 text-xs text-muted-foreground">Detectado el {new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short" }).format(new Date(incident.created_at))}</p>
                    {incident.snoozed_until && <p className="mt-1 text-xs text-muted-foreground">Pospuesto hasta {new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short" }).format(new Date(incident.snoozed_until))}</p>}
                    {incident.dismissal_reason && <p className="mt-1 text-xs text-muted-foreground">Motivo: {incident.dismissal_reason}</p>}
                    {incident.resolution_reason && <p className="mt-1 text-xs text-muted-foreground">Resultado: {resolutionLabels[incident.resolution_reason] ?? "Resuelto."}</p>}
                  </div>
                  <Link to={incident.href} onClick={onNavigate} className="inline-flex shrink-0 items-center gap-1 text-sm text-brand underline-offset-4 hover:underline">
                    Abrir <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                  </Link>
                </div>

                {incident.state !== "resolved" && (
                  <div className="flex flex-wrap gap-2 border-t border-border pt-3">
                    {incident.state !== "dismissed" && <Button type="button" size="sm" variant="outline" disabled={decisionMutation.isPending || mustRefresh} onClick={() => openSnooze(incident.id)}><Clock3 className="mr-1 h-3.5 w-3.5" />Posponer</Button>}
                    {incident.state !== "dismissed" && <Button type="button" size="sm" variant="ghost" disabled={decisionMutation.isPending || mustRefresh} onClick={() => openDismiss(incident.id)}>Descartar</Button>}
                    {incident.state !== "active" && <Button type="button" size="sm" variant="outline" disabled={decisionMutation.isPending || mustRefresh} onClick={() => decide(incident, "reactivate")}>Reactivar</Button>}
                  </div>
                )}

                {snoozeFor === incident.id && (
                  <div className="rounded-lg bg-muted/50 p-3">
                    <Label htmlFor={`snooze-${id}-${incident.id}`}>Posponer hasta</Label>
                    <p className="mb-2 text-xs text-muted-foreground">Hora de este dispositivo ({Intl.DateTimeFormat().resolvedOptions().timeZone}).</p>
                    <div className="flex flex-col gap-2 sm:flex-row">
                      <Input id={`snooze-${id}-${incident.id}`} type="datetime-local" value={snoozeUntil} onChange={(event) => setSnoozeUntil(event.target.value)} disabled={decisionMutation.isPending} />
                      <Button type="button" size="sm" onClick={() => submitSnooze(incident)} isLoading={decisionMutation.isPending} disabled={mustRefresh}>Guardar</Button>
                    </div>
                  </div>
                )}
                {dismissFor === incident.id && (
                  <div className="rounded-lg bg-muted/50 p-3">
                    <Label htmlFor={`dismiss-${id}-${incident.id}`}>Motivo para descartar</Label>
                    <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                      <Input id={`dismiss-${id}-${incident.id}`} value={dismissReason} onChange={(event) => setDismissReason(event.target.value)} maxLength={500} disabled={decisionMutation.isPending} />
                      <Button type="button" size="sm" variant="destructive" aria-label="Confirmar descarte" onClick={() => submitDismiss(incident)} isLoading={decisionMutation.isPending} disabled={mustRefresh}>Descartar</Button>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
          {!compact && <>
            {incidentsQuery.hasNextPage && <Button type="button" variant="outline" className="w-full" onClick={() => fetchNextPage()} isLoading={incidentsQuery.isFetchingNextPage}>Cargar más</Button>}
            {incidentsQuery.isFetchNextPageError && <p role="alert" className="text-sm text-destructive">No se pudo cargar la siguiente página. <button type="button" className="underline" onClick={() => fetchNextPage()}>Reintentar</button></p>}
          </>}
        </div>
      )}
      {compact && incidents.length > 0 && <Link to="/incidents" onClick={onNavigate} className="inline-block text-sm text-brand underline-offset-4 hover:underline">Ver todas las alertas</Link>}
    </section>
  )
}
