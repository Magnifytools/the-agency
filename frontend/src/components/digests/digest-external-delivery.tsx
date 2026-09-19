import { useState } from "react"
import { isAxiosError } from "axios"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useAuth } from "@/context/auth-context"
import { reportPolicyApi } from "@/lib/report-policy-api"
import { getAgencyTimezone, parseApiInstant } from "@/lib/dates"
import { Button } from "@/components/ui/button"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"

type Action = "confirmed" | "revoked"
type Request = { action: Action; key: string }
const timestamp = (value: string) => parseApiInstant(value).toLocaleString("es-ES", { timeZone: getAgencyTimezone(), dateStyle: "medium", timeStyle: "short" })

export function DigestExternalDelivery({ digestId, unsaved = false, busy = false }: { digestId: number; unsaved?: boolean; busy?: boolean }) {
  return <VersionDelivery key={digestId} digestId={digestId} unsaved={unsaved} busy={busy} />
}

function VersionDelivery({ digestId, unsaved, busy }: { digestId: number; unsaved: boolean; busy: boolean }) {
  const { user, hasPermission } = useAuth()
  const cache = useQueryClient()
  const queryKey = ["digest-external-delivery", user?.id, digestId]
  const history = useQuery({ queryKey, queryFn: () => reportPolicyApi.externalEvents(digestId), retry: false })
  const [confirm, setConfirm] = useState<Action | null>(null)
  const [request, setRequest] = useState<Request | null>(null)
  const [knownError, setKnownError] = useState("")
  const [permissionDenied, setPermissionDenied] = useState(false)
  const mutation = useMutation({
    mutationFn: (value: Request) => reportPolicyApi.recordExternalEvent(digestId, value.action, value.key),
    onSuccess: () => {
      setRequest(null); setKnownError("")
      void cache.invalidateQueries({ queryKey })
      void cache.invalidateQueries({ queryKey: ["digest-generation-preview"] })
      void cache.invalidateQueries({ queryKey: ["digests"] })
    },
    onError: error => {
      const status = isAxiosError(error) ? error.response?.status : undefined
      if (status && status >= 400 && status < 500 && status !== 408) {
        // A rejected operation has a known outcome; repeating its key cannot
        // resolve another person's newer confirmation or revoked permission.
        setRequest(null)
        setKnownError(status === 403 || status === 401 ? "Ya no tienes permiso para registrar la entrega de esta versión." : status === 409 ? "La confirmación cambió mientras la revisabas. Se ha solicitado el estado actual." : "No se pudo registrar esta acción. Revisa el estado actual antes de intentarlo de nuevo.")
        if (status === 403 || status === 401) setPermissionDenied(true)
        void cache.invalidateQueries({ queryKey })
        void cache.invalidateQueries({ queryKey: ["digest-generation-preview"] })
      }
    },
  })
  const data = history.data
  const delivered = data?.external_delivery.state === "confirmed"
  const canRecord = data?.can_record && hasPermission("digests", true) && !permissionDenied
  const disabled = busy || unsaved || history.isFetching || mutation.isPending || !!request
  const perform = () => {
    if (!confirm || disabled || !canRecord) return
    const next = { action: confirm, key: crypto.randomUUID() }
    setRequest(next); setConfirm(null); setKnownError(""); mutation.mutate(next)
  }
  return (
    <section className="space-y-3 border-t pt-5" aria-labelledby="external-delivery-title">
      <h2 id="external-delivery-title" className="font-semibold">Entrega al cliente · versión #{digestId}</h2>
      <p className="text-sm text-muted-foreground">Es una confirmación manual de entrega fuera de The Agency. Compartir en Discord interno no la confirma.</p>
      {knownError && <p role="alert" className="text-sm">{knownError}</p>}
      {history.isPending ? <p role="status" className="text-sm">Consultando confirmaciones…</p> : history.isError ? (
        <div className="space-y-2"><p role="alert" className="text-sm">No se pudo consultar la entrega de esta versión.</p><Button variant="outline" onClick={() => void history.refetch()}>Reintentar consulta</Button></div>
      ) : data && (
        <>
          <p className="text-sm">{delivered ? `Marcado como entregado al cliente por ${data.external_delivery.actor_name || "un miembro del equipo"}${data.external_delivery.confirmed_at ? ` el ${timestamp(data.external_delivery.confirmed_at)}` : ""}.` : "Sin confirmación de entrega al cliente para esta versión."}</p>
          {data.has_newer_version && <p className="text-sm text-muted-foreground">Hay una versión posterior. Esta confirmación solo corresponde a la versión #{digestId}.</p>}
          {canRecord && <Button variant="outline" disabled={disabled} onClick={() => setConfirm(delivered ? "revoked" : "confirmed")}>{delivered ? "Corregir confirmación de entrega" : "Marcar como entregado al cliente"}</Button>}
          {canRecord && unsaved && <p className="text-sm text-muted-foreground">Guarda los cambios antes de confirmar la entrega: el texto editado todavía no tiene una versión guardada.</p>}
          {mutation.isPending && <p role="status" className="text-sm">Registrando confirmación…</p>}
          {mutation.isError && request && <div className="space-y-2"><p role="alert" className="text-sm">No se pudo confirmar el resultado. Reintenta la misma operación para comprobarla sin duplicar el registro.</p><Button variant="outline" disabled={busy || mutation.isPending} onClick={() => mutation.mutate(request)}>Reintentar registro</Button></div>}
          {!!data.events.length && <details className="text-sm"><summary className="min-h-10 cursor-pointer py-2 text-muted-foreground">Historial de confirmaciones ({data.events.length})</summary><ol className="space-y-2">{data.events.map(event => <li key={event.id}><span className="font-medium">{event.action === "confirmed" ? "Entrega confirmada" : "Confirmación retirada"}</span> · {event.actor_name || "Miembro del equipo"} · <time dateTime={event.created_at}>{timestamp(event.created_at)}</time></li>)}</ol></details>}
        </>
      )}
      <Dialog open={confirm !== null} onOpenChange={open => { if (!open) setConfirm(null) }}>
        <DialogHeader><DialogTitle>{confirm === "revoked" ? "Corregir confirmación de entrega" : `Confirmar entrega de la versión #${digestId}`}</DialogTitle></DialogHeader>
        <p className="mb-4 text-sm text-muted-foreground">{confirm === "revoked" ? "La versión volverá a figurar sin entrega confirmada. El historial de quién confirmó y corrigió la entrega se conserva." : "Confirma solo si tú u otra persona entregaste esta versión al cliente fuera de The Agency."}</p>
        <div className="flex flex-wrap justify-end gap-2"><Button variant="ghost" onClick={() => setConfirm(null)}>Cancelar</Button><Button disabled={disabled || !canRecord} onClick={perform}>{confirm === "revoked" ? "Retirar confirmación" : "Confirmar entrega"}</Button></div>
      </Dialog>
    </section>
  )
}
