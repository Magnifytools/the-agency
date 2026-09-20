import { useState } from "react"
import { isAxiosError } from "axios"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import { useAuth } from "@/context/auth-context"
import { reportPolicyApi, type ReportPolicy } from "@/lib/report-policy-api"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"

type PolicyDraft = { enabled: boolean; cadence: "weekly" | "monthly"; responsible_user_id: number | null; revision: number }
const draftFrom = (policy: ReportPolicy): PolicyDraft => ({
  enabled: policy.enabled,
  cadence: policy.cadence ?? "weekly",
  responsible_user_id: policy.responsible_user_id,
  revision: policy.revision ?? 0,
})

export function ClientReportPolicy({ clientId, clientName }: { clientId: number; clientName: string }) {
  // A different client gets independent edits, errors and mutation callbacks.
  return <PolicyPanel key={clientId} clientId={clientId} clientName={clientName} />
}

function PolicyPanel({ clientId, clientName }: { clientId: number; clientName: string }) {
  const { isAdmin, user } = useAuth()
  const cache = useQueryClient()
  const key = ["report-policy", user?.id, clientId]
  const policy = useQuery({ queryKey: key, queryFn: () => reportPolicyApi.getPolicy(clientId), retry: false })
  const candidates = useQuery({ queryKey: ["digest-policy-responsibles", user?.id], queryFn: () => reportPolicyApi.responsibles(), enabled: isAdmin })
  const [draft, setDraft] = useState<PolicyDraft | null>(null)
  const [error, setError] = useState("")
  const [conflict, setConflict] = useState<ReportPolicy | null>(null)
  const save = useMutation({
    mutationFn: (body: PolicyDraft) => reportPolicyApi.updatePolicy(clientId, body),
    onSuccess: (data) => {
      cache.setQueryData(key, data)
      void cache.invalidateQueries({ queryKey: ["digest-generation-preview"] })
      void cache.invalidateQueries({ queryKey: ["digests"] })
      void cache.invalidateQueries({ queryKey: ["incidents"] })
      setDraft(null); setError(""); setConflict(null)
      toast.success("Frecuencia del resumen guardada")
    },
    onError: (err) => {
      if (isAxiosError(err) && err.response?.status === 409 && err.response.data?.detail?.current) {
        setConflict(err.response.data.detail.current)
        setError("Otra persona cambió esta configuración. Revisa la versión actual antes de guardar.")
      } else if (isAxiosError(err) && err.response?.status === 422) {
        setError("Elige un responsable activo con permiso para preparar resúmenes.")
        void candidates.refetch()
      } else {
        setError("No se pudo guardar. Tu selección se conserva; puedes volver a intentarlo.")
      }
    },
  })
  const current = policy.data
  const denied = isAxiosError(policy.error) && policy.error.response?.status === 403
  return (
    <section className="space-y-5 rounded-xl border p-5 sm:p-6" aria-labelledby="client-report-heading">
      <div>
        <h2 id="client-report-heading" className="text-lg font-semibold">Resúmenes de {clientName}</h2>
        <p className="mt-1 text-sm text-muted-foreground">Define quién los prepara y con qué frecuencia. La preparación y la entrega se revisan en Resúmenes.</p>
      </div>
      {policy.isPending ? <p role="status">Cargando configuración…</p> : policy.isError ? (
        <div className="space-y-2">
          <p role={denied ? undefined : "alert"} className="text-sm text-muted-foreground">{denied ? "La configuración está disponible para el responsable asignado y los administradores." : "No se pudo cargar la configuración del resumen."}</p>
          {!denied && <Button variant="outline" onClick={() => void policy.refetch()}>Reintentar</Button>}
        </div>
      ) : current && !draft ? (
        <div className="space-y-3">
          {!current.configured ? <p className="text-sm">Sin frecuencia definida. Ningún resumen se preparará por este criterio hasta que lo configures.</p> : (
            <dl className="flex flex-wrap gap-x-10 gap-y-3 text-sm">
              <div><dt className="text-muted-foreground">Preparación periódica</dt><dd className="font-medium">{current.enabled ? "Incluida al preparar resúmenes" : "Pausada"}</dd></div>
              <div><dt className="text-muted-foreground">Frecuencia</dt><dd className="font-medium">{current.cadence === "monthly" ? "Mensual · mes anterior completo" : "Semanal · última semana cerrada"}</dd></div>
              <div><dt className="text-muted-foreground">Responsable</dt><dd className="font-medium">{current.responsible_name || "Sin asignar"}</dd></div>
            </dl>
          )}
          {current.enabled && (!current.responsible_active || !current.responsible_can_prepare) && <p role="alert" className="text-sm">El responsable ya no está disponible o no tiene permiso para preparar resúmenes. Un administrador debe revisar la asignación.</p>}
          {isAdmin && <Button variant="outline" onClick={() => { setDraft(draftFrom(current)); setError(""); setConflict(null) }}>{current.configured ? "Cambiar frecuencia o responsable" : "Configurar resumen"}</Button>}
        </div>
      ) : null}
      {isAdmin && draft && (
        <form className="space-y-4" onSubmit={event => { event.preventDefault(); if (!conflict && !save.isPending) { setError(""); save.mutate(draft) } }}>
          <fieldset disabled={save.isPending} className="space-y-4">
            <label className="flex items-start gap-3 text-sm"><input type="checkbox" className="mt-1 h-4 w-4" checked={draft.enabled} onChange={event => setDraft({ ...draft, enabled: event.target.checked })} /><span>Incluir este cliente al preparar resúmenes periódicos<span className="block text-muted-foreground">Podrás revisar el período y seleccionar los clientes antes de generar. No activa envíos automáticos.</span></span></label>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2"><Label htmlFor="report-cadence">Frecuencia</Label><Select id="report-cadence" value={draft.cadence} onChange={event => setDraft({ ...draft, cadence: event.target.value as PolicyDraft["cadence"] })}><option value="weekly">Semanal · última semana cerrada</option><option value="monthly">Mensual · mes anterior completo</option></Select></div>
              <div className="space-y-2"><Label htmlFor="report-responsible">Responsable</Label><Select id="report-responsible" required={draft.enabled} value={draft.responsible_user_id ?? ""} onChange={event => setDraft({ ...draft, responsible_user_id: event.target.value ? Number(event.target.value) : null })} disabled={candidates.isPending || candidates.isError}><option value="">Sin asignar</option>{draft.responsible_user_id && !candidates.data?.some(person => person.id === draft.responsible_user_id) && <option value={draft.responsible_user_id} disabled>{current?.responsible_name || "Responsable anterior"} · no disponible</option>}{candidates.data?.map(person => <option key={person.id} value={person.id}>{person.full_name}</option>)}</Select></div>
            </div>
            {candidates.isError && <div role="alert" className="text-sm">No se pudo cargar el equipo. <Button type="button" variant="ghost" onClick={() => void candidates.refetch()}>Reintentar equipo</Button></div>}
            {error && <p role="alert" className="text-sm">{error}</p>}
            {conflict && <Button type="button" variant="outline" onClick={() => { cache.setQueryData(key, conflict); setDraft(draftFrom(conflict)); setConflict(null); setError("") }}>Cargar configuración actual</Button>}
            <div className="flex flex-wrap gap-2"><Button type="submit" disabled={!!conflict || candidates.isPending || candidates.isError || (draft.enabled && !draft.responsible_user_id)}>{save.isPending ? "Guardando…" : "Guardar configuración"}</Button><Button type="button" variant="ghost" onClick={() => { setDraft(null); setConflict(null); setError("") }}>Cancelar</Button></div>
          </fieldset>
        </form>
      )}
      <Link className="inline-flex min-h-10 items-center text-sm font-medium text-brand hover:underline" to={`/digests?client_id=${clientId}`}>Abrir resúmenes de {clientName}</Link>
    </section>
  )
}
