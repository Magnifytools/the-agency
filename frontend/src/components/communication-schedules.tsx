import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useAuth } from "@/context/auth-context"
import { api } from "@/lib/api"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { DeliveryReceipts } from "@/components/delivery-receipts"
import type { DeliveryReceipt } from "@/lib/types"

type Kind = "morning" | "evening" | "meeting" | "weekly"
type Policy = { destination_id?: string | null; kind: Kind; revision: number; enabled: boolean; channels: string[]; time: string | null; minutes_before: number | null; quiet_start: string | null; quiet_end: string | null; state: string; reason: string | null }
type Catalog = { user_id: number; timezone: string; scheduler_enabled: boolean; extension_min_version: string; extension_download_url: string; policies: Policy[] }
type Occurrence = { id: number; kind: Kind; channel: string; state: string; reason: string | null; period_start: string; due_at: string; receipt: DeliveryReceipt | null }
const titles: Record<Kind, string> = { morning: "Plan de la mañana", evening: "Resumen del día", meeting: "Reuniones", weekly: "Informe semanal del equipo" }
const channelLabels: Record<string, string> = { in_app: "En mi app", extension: "En esta extensión de Chrome", team_webhook: "Canal de Discord del equipo (visible para todos)", owner_dm: "DM al destinatario técnico de Discord configurado" }
const channels: Record<Kind, string[]> = { morning: ["in_app", "team_webhook"], evening: ["in_app", "team_webhook"], meeting: ["in_app", "extension"], weekly: ["owner_dm"] }
const states: Record<string, string> = { needs_review: "Por configurar", disabled: "Desactivado", ready: "Preparado", blocked: "Requiere atención", planned: "Programado", expired: "Caducado", cancelled: "Cancelado", local_delivered: "Disponible en la app" }

function PolicyEditor({ policy, refresh }: { policy: Policy; refresh: () => void }) {
  const [draft, setDraft] = useState(policy)
  const [error, setError] = useState("")
  const mutation = useMutation({
    mutationFn: () => api.put<Policy>(`/communication-schedules/${policy.kind}`, {
      destination_id: draft.destination_id || null, revision: draft.revision, enabled: draft.enabled, channels: draft.channels, time: draft.time,
      minutes_before: draft.minutes_before, quiet_start: draft.quiet_start, quiet_end: draft.quiet_end,
    }).then(r => r.data),
    onSuccess: (saved) => { setDraft(saved); setError(""); refresh() },
    onError: (e) => setError(getErrorMessage(e, "No se pudo guardar. Tu selección se conserva.")),
  })
  return <details className="rounded-xl border p-4" open={policy.state === "blocked" ? true : undefined}>
    <summary className="cursor-pointer min-h-11 py-2"><span className="font-medium">{titles[policy.kind]}</span><span role="status" className="block mt-1 text-sm text-muted-foreground">{states[policy.state] || policy.state}</span></summary>
    <form onSubmit={e => { e.preventDefault(); mutation.mutate() }} className="space-y-3 pt-3">
    {policy.reason && policy.state !== "needs_review" && <p className="text-sm">{policy.reason}</p>}
    {policy.kind === "weekly" && <p className="text-sm text-muted-foreground">Se envía el sábado a las 08:00 con el trabajo del lunes al viernes. Al guardarlo, te encargas de este aviso del equipo.</p>}
    {policy.kind === "weekly" && <label className="block text-sm">ID Discord del destinatario técnico<input className="block rounded border p-2 bg-background w-full" inputMode="numeric" pattern="[0-9]{5,30}" value={draft.destination_id ?? ""} onChange={e => setDraft({ ...draft, destination_id: e.target.value || null })} /><span className="text-xs text-muted-foreground">Se enviará a este ID. No vincula la cuenta de ninguna persona de Agency.</span></label>}
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.enabled} onChange={e => setDraft({ ...draft, enabled: e.target.checked })} /> Activar {titles[policy.kind].toLowerCase()}</label>
    <fieldset className="space-y-2"><legend className="text-sm mb-2">Dónde recibirlo</legend>{channels[policy.kind].map(channel => <label key={channel} className="flex items-start gap-2 text-sm"><input type="checkbox" checked={draft.channels.includes(channel)} onChange={e => setDraft({ ...draft, channels: e.target.checked ? [...draft.channels, channel] : draft.channels.filter(c => c !== channel) })} />{channelLabels[channel]}</label>)}</fieldset>
    {policy.kind === "meeting" ? <label className="block text-sm">Antelación (minutos)<input className="block rounded border p-2 w-28 bg-background" type="number" min={5} max={120} value={draft.minutes_before ?? 30} onChange={e => setDraft({ ...draft, minutes_before: Number(e.target.value) })} /></label> : <label className="block text-sm">Hora<input className="block rounded border p-2 bg-background" type="time" required disabled={policy.kind === "weekly"} value={draft.time ?? "08:00"} onChange={e => setDraft({ ...draft, time: e.target.value })} /></label>}
    <details className="rounded-lg bg-muted/30 p-3"><summary className="cursor-pointer text-sm">Horario de silencio (opcional)</summary><div className="mt-3 flex flex-wrap gap-3">{(["quiet_start", "quiet_end"] as const).map(field => <label key={field} className="text-sm">{field === "quiet_start" ? "Silencio desde" : "Silencio hasta"}<input type="time" className="block rounded border p-2 bg-background" value={draft[field] ?? ""} onChange={e => setDraft({ ...draft, [field]: e.target.value || null })} /></label>)}</div>
    <p className="text-xs text-muted-foreground">Los avisos se aplazan durante este horario. Si dejan de ser útiles antes de que termine, no se envían.</p></details>
    {policy.kind === "meeting" && <p className="text-sm">Recibe un aviso antes de cada reunión. <a className="underline" href="#calendar">Configurar Google Calendar</a>.</p>}
    {error && <p role="alert" className="text-sm text-red-600">{error} <button type="button" className="underline" onClick={async () => { try { const fresh = await api.get<Catalog>("/communication-schedules"); const current = fresh.data.policies.find(p => p.kind === policy.kind); if (current) setDraft(current); setError(""); refresh() } catch { setError("No se pudo recargar; tu borrador se conserva") } }}>Descartar borrador y recargar</button></p>}
    <Button type="submit" disabled={mutation.isPending}>{mutation.isPending ? "Guardando…" : `Guardar ${titles[policy.kind].toLowerCase()}`}</Button>
    </form>
  </details>
}

export function CommunicationSchedules() {
  const { user, isAdmin } = useAuth()
  const client = useQueryClient()
  const key = ["communication-schedules", user?.id]
  const catalog = useQuery({ queryKey: key, queryFn: () => api.get<Catalog>("/communication-schedules").then(r => r.data), enabled: !!user })
  const [before, setBefore] = useState<number | null>(null)
  const history = useQuery({ queryKey: [...key, "history", before], queryFn: () => api.get<Occurrence[]>("/communication-schedules/history", { params: { limit: 20, before: before ?? undefined } }).then(r => r.data), enabled: !!user, refetchInterval: 15000, refetchIntervalInBackground: false })
  const refresh = () => { client.invalidateQueries({ queryKey: key }); client.invalidateQueries({ queryKey: ["deliveries"] }) }
  return <section id="notifications" className="bg-card border border-border rounded-2xl p-6 space-y-4 scroll-mt-8">
    <h2 className="text-base font-semibold">Avisos</h2>
    <p className="text-sm text-muted-foreground">Elige un aviso para configurar dónde y cuándo recibirlo. Solo se activa cuando lo guardas.</p>
    {catalog.isPending && <p>Cargando configuración…</p>}
    {catalog.isError && <p role="alert">No se pudo cargar la configuración. <button className="underline" onClick={() => catalog.refetch()}>Reintentar</button></p>}
    {catalog.data && <>
      <p className="text-sm">Zona: {catalog.data.timezone}. {!catalog.data.scheduler_enabled && "Los envíos están pausados; puedes guardar tus preferencias para cuando se reanuden."}</p>
      <details className="text-sm"><summary className="cursor-pointer">Avisos en Chrome</summary><p className="mt-2">Los avisos de escritorio requieren la extensión {catalog.data.extension_min_version} o posterior. <a className="underline" href={catalog.data.extension_download_url}>Descargar actualización</a>. En chrome://extensions puedes actualizarla; las versiones anteriores no reciben avisos. Cada instalación muestra sus propios avisos.</p></details>
      <div className="grid gap-4 lg:grid-cols-2">{catalog.data.policies.map(policy => <PolicyEditor key={`${user?.id}:${policy.kind}`} policy={policy} refresh={refresh} />)}</div>
    </>}
    {isAdmin && <DiscordConfiguration refresh={refresh} />}
    <h3 className="font-medium">Próximos y últimos avisos</h3>
    {history.isError && <p role="alert">No se pudo cargar el historial. <button className="underline" onClick={() => history.refetch()}>Reintentar</button></p>}
    {!history.isPending && !history.data?.length && <p className="text-sm text-muted-foreground">Todavía no hay avisos en esta página. Aquí verás los próximos avisos y qué ocurrió con los anteriores.</p>}
    {history.data?.map(row => <article key={row.id} className="border rounded-xl p-4 space-y-2 text-sm"><h4 className="font-medium">{titles[row.kind]} · {row.period_start}</h4><p>{channelLabels[row.channel]} · {states[row.state] || row.state}</p><p>{row.reason}</p>{row.receipt && <DeliveryReceipts sourceKind="communication" sourceId={row.receipt.source_id} />}</article>)}
    <div className="flex gap-2">{before && <Button variant="outline" onClick={() => setBefore(null)}>Más recientes</Button>}{history.data?.length === 20 && <Button variant="outline" onClick={() => setBefore(history.data![history.data!.length - 1].id)}>Anteriores</Button>}</div>
  </section>
}


function DiscordConfiguration({ refresh }: { refresh: () => void }) {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ["scheduled-discord-config"], queryFn: () => api.get<{ webhook_configured: boolean; bot_token_configured: boolean }>("/communication-schedules/discord-configuration").then(r => r.data) })
  const [webhook, setWebhook] = useState("")
  const [token, setToken] = useState("")
  const mutation = useMutation({
    mutationFn: () => api.put("/communication-schedules/discord-configuration", { ...(webhook.trim() ? { webhook_url: webhook.trim() } : {}), ...(token.trim() ? { bot_token: token.trim() } : {}) }),
    onSuccess: () => { setWebhook(""); setToken(""); client.invalidateQueries({ queryKey: ["scheduled-discord-config"] }); refresh() },
  })
  return <details className="border rounded-xl p-4"><summary className="cursor-pointer font-medium">Configurar Discord del equipo</summary>
    <p className="text-sm my-3">Webhook: {query.data?.webhook_configured ? "configurado" : "pendiente"}. Bot: {query.data?.bot_token_configured ? "configurado" : "pendiente"}. Guardar no envía ningún mensaje.</p>
    {query.isError && <p role="alert">No se pudo consultar la configuración.</p>}
    <form className="space-y-3" onSubmit={e => { e.preventDefault(); mutation.mutate() }}>
      <label className="block text-sm">Nuevo webhook del equipo<input type="password" autoComplete="new-password" className="block border rounded p-2 w-full bg-background" value={webhook} onChange={e => setWebhook(e.target.value)} /></label>
      <label className="block text-sm">Nuevo token del bot<input type="password" autoComplete="new-password" className="block border rounded p-2 w-full bg-background" value={token} onChange={e => setToken(e.target.value)} /></label>
      <p className="text-xs text-muted-foreground">Deja vacío para conservar la configuración actual. Las credenciales se cifran y nunca se muestran.</p>
      {mutation.isError && <p role="alert">{getErrorMessage(mutation.error, "No se pudo guardar; tus entradas se conservan")}</p>}
      <Button disabled={mutation.isPending || (!webhook.trim() && !token.trim())}>Guardar configuración de Discord</Button>
    </form>
  </details>
}
