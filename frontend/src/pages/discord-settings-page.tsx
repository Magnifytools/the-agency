import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { discordApi } from "@/lib/api"
import type { DiscordSettings } from "@/lib/types"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Loader2, Send, CheckCircle, Bell, Bot, Eye, Pencil } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

export default function DiscordSettingsPage() {
  const queryClient = useQueryClient()
  const [webhookInput, setWebhookInput] = useState("")
  const [botTokenInput, setBotTokenInput] = useState("")
  const [summaryTimeInput, setSummaryTimeInput] = useState("18:00")
  const [autoSendInput, setAutoSendInput] = useState(false)
  const [includeAiInput, setIncludeAiInput] = useState(true)
  const [initialized, setInitialized] = useState(false)

  // Preview/edit state for daily summary
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewContent, setPreviewContent] = useState("")
  const [isEditing, setIsEditing] = useState(false)

  const { data: settings, isLoading } = useQuery({
    queryKey: ["discord-settings"],
    queryFn: discordApi.settings,
  })

  // Initialize form when settings load
  if (settings && !initialized) {
    setWebhookInput("")
    setSummaryTimeInput(settings.summary_time || "18:00")
    setAutoSendInput(settings.auto_daily_summary)
    setIncludeAiInput(settings.include_ai_note)
    setInitialized(true)
  }

  const updateMutation = useMutation({
    mutationFn: (data: Partial<DiscordSettings>) => discordApi.updateSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["discord-settings"] })
      toast.success("Configuración guardada")
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

  const previewMutation = useMutation({
    mutationFn: () => discordApi.preview(),
    onSuccess: (data) => {
      setPreviewContent(data.summary)
      setIsEditing(false)
      setPreviewOpen(true)
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al generar preview")),
  })

  const sendCustomMutation = useMutation({
    mutationFn: (content: string) => discordApi.sendCustom(content),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["discord-settings"] })
      if (data.success) {
        toast.success(data.message)
        setPreviewOpen(false)
      } else {
        toast.error(data.message)
      }
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al enviar resumen")),
  })

  const handleSave = () => {
    const data: Record<string, unknown> = {
      webhook_url: webhookInput,
      auto_daily_summary: autoSendInput,
      summary_time: summaryTimeInput,
      include_ai_note: includeAiInput,
    }
    // Only send bot_token if user typed something (avoid clearing existing token)
    if (botTokenInput.trim()) {
      data.bot_token = botTokenInput.trim()
    }
    updateMutation.mutate(data as Partial<DiscordSettings>)
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
          <p className="text-muted-foreground">Configuración de integración con Discord</p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => previewMutation.mutate()}
            disabled={previewMutation.isPending || !settings?.webhook_configured}
          >
            {previewMutation.isPending ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Eye className="w-4 h-4 mr-2" />
            )}
            Previsualizar resumen de hoy
          </Button>
        </div>
      </div>

      {/* Connection status */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Estado de conexión
            {settings?.webhook_configured ? (
              <Badge variant="success">Conectado</Badge>
            ) : (
              <Badge variant="destructive">No configurado</Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2 text-sm">
            <p className="text-muted-foreground">
              Hilos: {settings?.bot_token_configured ? "✅ Activados (bot token configurado)" : "❌ Desactivados (sin bot token)"}
            </p>
            {settings?.last_sent_at ? (
              <p className="text-muted-foreground">
                Último envío: {new Date(settings.last_sent_at).toLocaleString("es-ES")}
              </p>
            ) : (
              <p className="text-muted-foreground">No se ha enviado ningún mensaje aún</p>
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
                autoComplete="off"
                placeholder={settings?.webhook_configured ? "••••••• (configurado)" : "https://discord.com/api/webhooks/..."}
                value={webhookInput}
                onChange={(e) => setWebhookInput(e.target.value)}
                className="flex-1"
              />
              <Button
                variant="outline"
                onClick={() => testMutation.mutate()}
                disabled={testMutation.isPending || (!webhookInput.trim() && !settings?.webhook_configured)}
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
              Crea un webhook en Discord: Configuración del canal → Integraciones → Webhooks → Nuevo webhook
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Bot Token for threads */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bot className="w-5 h-5" />
            Bot Token
            {settings?.bot_token_configured ? (
              <Badge variant="success">Configurado</Badge>
            ) : (
              <Badge variant="outline">No configurado</Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="bot-token">Token del bot de Discord</Label>
            <Input
              id="bot-token"
              type="password"
              placeholder={settings?.bot_token_configured ? "••••••••••••••••" : "Pega el token del bot aquí..."}
              value={botTokenInput}
              onChange={(e) => setBotTokenInput(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Necesario para enviar dailys como hilos. Crea un bot en{" "}
              <a href="https://discord.com/developers/applications" target="_blank" rel="noopener noreferrer" className="text-brand underline">
                discord.com/developers
              </a>
              {" "}y copia el token. El bot necesita permisos de "Create Public Threads" y "Send Messages in Threads".
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
            <Label htmlFor="auto-send">Enviar resumen diario automáticamente</Label>
          </div>

          <div className="space-y-2">
            <Label htmlFor="summary-time">Hora de envío</Label>
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
          Guardar configuración
        </Button>
      </div>

      {/* Preview/Edit Daily Summary Dialog */}
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogHeader>
          <DialogTitle>Resumen diario — Preview</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 pt-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              {isEditing ? "Edita el contenido antes de enviar a Discord" : "Revisa el contenido antes de enviar a Discord"}
            </p>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsEditing(!isEditing)}
            >
              <Pencil className="w-4 h-4 mr-1" />
              {isEditing ? "Vista previa" : "Editar"}
            </Button>
          </div>

          {isEditing ? (
            <textarea
              className="w-full min-h-[300px] rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono"
              value={previewContent}
              onChange={(e) => setPreviewContent(e.target.value)}
            />
          ) : (
            <pre className="bg-muted p-4 rounded-lg text-sm whitespace-pre-wrap max-h-[60vh] overflow-auto">
              {previewContent}
            </pre>
          )}

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setPreviewOpen(false)}>
              Cancelar
            </Button>
            <Button
              onClick={() => sendCustomMutation.mutate(previewContent)}
              disabled={!previewContent.trim() || sendCustomMutation.isPending}
            >
              {sendCustomMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Send className="w-4 h-4 mr-2" />
              )}
              Enviar a Discord
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  )
}
