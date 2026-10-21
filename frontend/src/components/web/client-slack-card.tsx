import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { MessageSquare, Send } from "lucide-react"
import { webApi } from "@/lib/api"
import type { ClientSlackSettings } from "@/lib/types"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { formatInstant } from "@/components/web/uptime-status"

interface Props {
  clientId: number
}

function stateLine(s: ClientSlackSettings) {
  if (!s.configured) return { text: "Sin configurar: los avisos de caída sólo llegan a Alertas.", tone: "text-muted-foreground" }
  if (s.revoked_at) return { text: `Revocado el ${formatInstant(s.revoked_at)}: Slack ya no acepta el webhook. Pega uno nuevo.`, tone: "text-red-400" }
  if (!s.enabled) return { text: "Configurado pero apagado: no se envía nada.", tone: "text-amber-600" }
  if (!s.downtime_to_slack) return { text: "Activo, pero los avisos de caída están desactivados.", tone: "text-amber-600" }
  return { text: "Activo: las caídas y recuperaciones de la web llegan a este canal.", tone: "text-green-500" }
}

/**
 * Canal de Slack del cliente para los avisos de "web caída" y "web recuperada".
 * Sólo admins. El webhook se guarda cifrado y nunca vuelve del servidor: aquí
 * sólo se ve si está configurado, activo o revocado.
 */
export function ClientSlackCard({ clientId }: Props) {
  const qc = useQueryClient()
  const queryKey = ["web-slack", clientId]
  const { data, isLoading } = useQuery({ queryKey, queryFn: () => webApi.slack(clientId) })
  const [webhook, setWebhook] = useState("")
  const [channel, setChannel] = useState("")
  const [enabled, setEnabled] = useState(true)
  const [downtime, setDowntime] = useState(true)
  const [userAgent, setUserAgent] = useState("")
  const [confirmRemove, setConfirmRemove] = useState(false)

  useEffect(() => {
    if (!data) return
    setChannel(data.channel_hint ?? "")
    setEnabled(data.configured ? data.enabled : true)
    setDowntime(data.downtime_to_slack)
    setUserAgent(data.user_agent ?? "")
  }, [data])

  const onSaved = (next: ClientSlackSettings, message: string) => {
    qc.setQueryData(queryKey, next)
    setWebhook("")
    toast.success(message)
  }
  const saveMut = useMutation({
    mutationFn: () => webApi.saveSlack(clientId, {
      ...(webhook.trim() ? { webhook_url: webhook.trim() } : {}),
      channel_hint: channel.trim() || null,
      enabled,
      downtime_to_slack: downtime,
      user_agent: userAgent.trim() || null,
    }),
    onSuccess: (next) => onSaved(next, "Ajustes de Slack guardados"),
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const removeMut = useMutation({
    mutationFn: () => webApi.removeSlack(clientId),
    onSuccess: (next) => onSaved(next, "Webhook quitado"),
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const testMut = useMutation({
    mutationFn: () => webApi.testSlack(clientId),
    onSuccess: (result) => {
      if (result.ok) toast.success("Mensaje de prueba enviado. Míralo en el canal del cliente.")
      else toast.error(result.error || "Slack no aceptó el mensaje")
      if (result.revoked) void qc.invalidateQueries({ queryKey })
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const busy = saveMut.isPending || removeMut.isPending || testMut.isPending
  const line = data ? stateLine(data) : null

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <MessageSquare className="h-4 w-4" /> Slack del cliente (avisos de la web)
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading || !data ? (
          <p className="text-sm text-muted-foreground">Cargando…</p>
        ) : (
          <>
            <p role="status" className={`text-sm ${line!.tone}`}>
              {line!.text}
              {data.channel_hint && <span className="text-muted-foreground"> Canal: {data.channel_hint}.</span>}
            </p>
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault()
                saveMut.mutate()
              }}
            >
              <div className="space-y-1">
                <Label htmlFor={`slack-webhook-${clientId}`}>Webhook de Slack</Label>
                <Input
                  id={`slack-webhook-${clientId}`}
                  type="password"
                  autoComplete="off"
                  value={webhook}
                  onChange={(e) => setWebhook(e.target.value)}
                  placeholder={data.configured ? "Guardado (no se muestra). Pega otro para cambiarlo." : "https://hooks.slack.com/services/…"}
                />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label htmlFor={`slack-channel-${clientId}`}>Canal (sólo como recordatorio)</Label>
                  <Input id={`slack-channel-${clientId}`} value={channel} onChange={(e) => setChannel(e.target.value)} placeholder="#cliente-avisos" />
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`slack-ua-${clientId}`}>User-Agent para comprobar su web</Label>
                  <Input id={`slack-ua-${clientId}`} value={userAgent} onChange={(e) => setUserAgent(e.target.value)} placeholder="El de por defecto" />
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="h-4 w-4" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
                Enviar avisos a este canal
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="h-4 w-4" checked={downtime} onChange={(e) => setDowntime(e.target.checked)} />
                Avisar de caídas y recuperaciones de la web
              </label>
              <div className="flex flex-wrap gap-2">
                <Button type="submit" size="sm" disabled={busy}>{saveMut.isPending ? "Guardando…" : "Guardar"}</Button>
                {data.configured && (
                  <>
                    <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => testMut.mutate()}>
                      <Send className="h-3.5 w-3.5 mr-1" /> Enviar prueba
                    </Button>
                    <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setConfirmRemove(true)}>
                      Quitar webhook
                    </Button>
                  </>
                )}
              </div>
            </form>
            {data.updated_at && <p className="text-[11px] text-muted-foreground">Último cambio: {formatInstant(data.updated_at)}</p>}
          </>
        )}
        <ConfirmDialog
          open={confirmRemove}
          onOpenChange={setConfirmRemove}
          title="¿Quitar el webhook?"
          description="Dejarán de llegar avisos de la web a Slack. Las caídas se siguen viendo en Alertas."
          confirmLabel="Quitar"
          onConfirm={() => removeMut.mutate()}
        />
      </CardContent>
    </Card>
  )
}
