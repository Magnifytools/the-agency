import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { discordApi } from "@/lib/api"
import type { DiscordSettings } from "@/lib/types"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Loader2, Send, CheckCircle, Bell } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

export default function DiscordSettingsPage() {
  const queryClient = useQueryClient()
  const [webhookInput, setWebhookInput] = useState("")
  const [summaryTimeInput, setSummaryTimeInput] = useState("18:00")
  const [autoSendInput, setAutoSendInput] = useState(false)
  const [includeAiInput, setIncludeAiInput] = useState(true)
  const [initialized, setInitialized] = useState(false)

  const { data: settings, isLoading } = useQuery({
    queryKey: ["discord-settings"],
    queryFn: discordApi.settings,
  })

  // Initialize form when settings load
  if (settings && !initialized) {
    setWebhookInput(settings.webhook_url || "")
    setSummaryTimeInput(settings.summary_time || "18:00")
    setAutoSendInput(settings.auto_daily_summary)
    setIncludeAiInput(settings.include_ai_note)
    setInitialized(true)
  }

  const updateMutation = useMutation({
    mutationFn: (data: Partial<DiscordSettings>) => discordApi.updateSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["discord-settings"] })
      toast.success("Configuracion guardada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al guardar")),
  })

  const testMutation = useMutation({
    mutationFn: () => discordApi.testWebhook(),
    onSuccess: (data) => {
      if (data.success) {
        toast.success(data.message)
      } else {
        toast.error(data.message)
      }
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al probar webhook")),
  })

  const sendSummaryMutation = useMutation({
    mutationFn: () => discordApi.sendDailySummary(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["discord-settings"] })
      toast.success(data.message)
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al enviar resumen")),
  })

  const handleSave = () => {
    updateMutation.mutate({
      webhook_url: webhookInput,
      auto_daily_summary: autoSendInput,
      summary_time: summaryTimeInput,
      include_ai_note: includeAiInput,
    })
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="w-6 h-6 animate-spin opacity-40" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Discord</h1>
          <p className="text-muted-foreground">Configuracion de integracion con Discord</p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => sendSummaryMutation.mutate()}
            disabled={sendSummaryMutation.isPending || !settings?.webhook_configured}
          >
            {sendSummaryMutation.isPending ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Send className="w-4 h-4 mr-2" />
            )}
            Enviar resumen de hoy
          </Button>
        </div>
      </div>

      {/* Connection status */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Estado de conexion
            {settings?.webhook_configured ? (
              <Badge variant="success">Conectado</Badge>
            ) : (
              <Badge variant="destructive">No configurado</Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2 text-sm">
            {settings?.last_sent_at ? (
              <p className="text-muted-foreground">
                Ultimo envio: {new Date(settings.last_sent_at).toLocaleString("es-ES")}
              </p>
            ) : (
              <p className="text-muted-foreground">No se ha enviado ningun mensaje aun</p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Webhook configuration */}
      <Card>
        <CardHeader>
          <CardTitle>Webhook URL</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="webhook">URL del webhook de Discord</Label>
            <div className="flex gap-2">
              <Input
                id="webhook"
                type="url"
                placeholder="https://discord.com/api/webhooks/..."
                value={webhookInput}
                onChange={(e) => setWebhookInput(e.target.value)}
                className="flex-1"
              />
              <Button
                variant="outline"
                onClick={() => testMutation.mutate()}
                disabled={testMutation.isPending || !webhookInput.trim()}
              >
                {testMutation.isPending ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <Bell className="w-4 h-4 mr-2" />
                )}
                Probar
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Crea un webhook en Discord: Configuracion del canal → Integraciones → Webhooks → Nuevo webhook
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Auto-send settings */}
      <Card>
        <CardHeader>
          <CardTitle>Resumen diario automatico</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3">
            <input
              type="checkbox"
              id="auto-send"
              checked={autoSendInput}
              onChange={(e) => setAutoSendInput(e.target.checked)}
              className="h-4 w-4 rounded border-border"
            />
            <Label htmlFor="auto-send">Enviar resumen diario automaticamente</Label>
          </div>

          <div className="space-y-2">
            <Label htmlFor="summary-time">Hora de envio</Label>
            <Input
              id="summary-time"
              type="time"
              value={summaryTimeInput}
              onChange={(e) => setSummaryTimeInput(e.target.value)}
              className="w-32"
              disabled={!autoSendInput}
            />
          </div>

          <div className="flex items-center gap-3">
            <input
              type="checkbox"
              id="ai-note"
              checked={includeAiInput}
              onChange={(e) => setIncludeAiInput(e.target.checked)}
              className="h-4 w-4 rounded border-border"
            />
            <Label htmlFor="ai-note">Incluir nota generada por IA</Label>
          </div>
        </CardContent>
      </Card>

      {/* Save button */}
      <div className="flex justify-end">
        <Button onClick={handleSave} disabled={updateMutation.isPending}>
          {updateMutation.isPending ? (
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
          ) : (
            <CheckCircle className="w-4 h-4 mr-2" />
          )}
          Guardar configuracion
        </Button>
      </div>
    </div>
  )
}
