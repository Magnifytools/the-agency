import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { dailysApi } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { MessageSquare, Send, CheckCircle2, ChevronDown, ChevronUp } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

interface DailyUpdateWidgetProps {
  userId: number
  readOnly?: boolean
}

export function DailyUpdateWidget({ userId, readOnly = false }: DailyUpdateWidgetProps) {
  const [text, setText] = useState("")
  const [expanded, setExpanded] = useState(false)
  const queryClient = useQueryClient()

  const today = new Date().toISOString().slice(0, 10)

  const { data: todayDailys } = useQuery({
    queryKey: ["daily-today", userId, today],
    queryFn: () => dailysApi.list({ user_id: userId, date_from: today, date_to: today, limit: 1 }),
  })
  const todayDaily = todayDailys?.[0]

  const submitMutation = useMutation({
    mutationFn: async (rawText: string) => {
      const daily = await dailysApi.submit({ raw_text: rawText })
      try {
        await dailysApi.sendDiscord(daily.id)
      } catch {}
      return daily
    },
    onSuccess: () => {
      toast.success("Daily enviado a Discord ✓")
      setText("")
      setExpanded(false)
      queryClient.invalidateQueries({ queryKey: ["daily-today", userId] })
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al enviar el daily")),
  })

  if (todayDaily) {
    return (
      <Card className="border-green-500/20 bg-green-500/5">
        <CardContent className="pt-4 pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-green-400">
              <CheckCircle2 className="h-4 w-4" />
              <span className="font-medium">Daily enviado hoy</span>
              {todayDaily.status === "sent" && (
                <Badge variant="success" className="text-xs">Discord ✓</Badge>
              )}
            </div>
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
            >
              {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
              {expanded ? "Ocultar" : "Ver"}
            </button>
          </div>
          {expanded && (
            <div className="mt-3 text-xs text-muted-foreground bg-muted/50 rounded-lg p-3 whitespace-pre-wrap font-mono leading-relaxed">
              {todayDaily.raw_text}
            </div>
          )}
        </CardContent>
      </Card>
    )
  }

  if (readOnly) {
    return (
      <Card className="border-muted/30">
        <CardContent className="pt-4 pb-3">
          <p className="text-sm text-muted-foreground italic">Sin daily hoy.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="border-brand/20">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-brand" />
          Daily Update
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!expanded ? (
          <Button
            variant="outline"
            className="w-full border-dashed border-brand/30 text-brand hover:bg-brand/5"
            onClick={() => setExpanded(true)}
          >
            <MessageSquare className="h-4 w-4 mr-2" />
            Enviar daily de hoy
          </Button>
        ) : (
          <div className="space-y-3">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={`Qué has hecho hoy por cliente/proyecto:\n\nCliente Acme:\n- Redacté los posts del mes\n- Revisé analytics\n\nMañana: terminar informe de mayo`}
              className="w-full min-h-[150px] rounded-lg border border-border bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-brand"
              autoFocus
            />
            <div className="flex gap-2">
              <Button
                onClick={() => submitMutation.mutate(text)}
                disabled={!text.trim() || submitMutation.isPending}
                className="flex-1"
              >
                <Send className="h-4 w-4 mr-2" />
                {submitMutation.isPending ? "Enviando..." : "Publicar en Discord"}
              </Button>
              <Button variant="outline" onClick={() => { setExpanded(false); setText("") }}>
                Cancelar
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
