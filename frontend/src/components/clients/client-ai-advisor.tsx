import { useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { Sparkles, ArrowRight } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { clientsApi } from "@/lib/api"
import { getErrorMessage } from "@/lib/utils"

interface Recommendation {
  priority: "high" | "medium" | "low"
  category: string
  title: string
  description: string
  action: string
}

interface Props {
  clientId: number
}

const PRIORITY_BADGE: Record<string, { label: string; variant: "destructive" | "warning" | "secondary" }> = {
  high: { label: "Alta", variant: "destructive" },
  medium: { label: "Media", variant: "warning" },
  low: { label: "Baja", variant: "secondary" },
}

const CATEGORY_LABELS: Record<string, string> = {
  comunicacion: "Comunicacion",
  facturacion: "Facturacion",
  tareas: "Tareas",
  rentabilidad: "Rentabilidad",
  estrategia: "Estrategia",
}

export function ClientAiAdvisor({ clientId }: Props) {
  const [recommendations, setRecommendations] = useState<Recommendation[]>([])

  const adviceMut = useMutation({
    mutationFn: () => clientsApi.aiAdvice(clientId),
    onSuccess: (data) => {
      setRecommendations(data.recommendations)
      toast.success(`${data.recommendations.length} recomendaciones generadas`)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-brand" /> Recomendaciones IA
        </h3>
        <Button
          size="sm"
          onClick={() => adviceMut.mutate()}
          disabled={adviceMut.isPending}
        >
          <Sparkles className="h-4 w-4 mr-1" />
          {adviceMut.isPending ? "Analizando..." : "Pedir recomendaciones"}
        </Button>
      </div>

      {recommendations.length === 0 && !adviceMut.isPending && (
        <p className="text-sm text-muted-foreground text-center py-6">
          Pulsa el boton para que la IA analice los datos del cliente y genere recomendaciones accionables.
        </p>
      )}

      {adviceMut.isPending && (
        <div className="text-center py-8">
          <div className="inline-flex items-center gap-2 text-sm text-muted-foreground">
            <div className="h-4 w-4 border-2 border-brand border-t-transparent rounded-full animate-spin" />
            Analizando datos del cliente...
          </div>
        </div>
      )}

      {recommendations.length > 0 && (
        <div className="grid gap-3">
          {recommendations.map((rec, i) => {
            const pBadge = PRIORITY_BADGE[rec.priority] ?? PRIORITY_BADGE.medium
            return (
              <Card key={i}>
                <CardContent className="p-4">
                  <div className="flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <Badge variant={pBadge.variant}>{pBadge.label}</Badge>
                        <Badge variant="outline" className="text-[10px]">
                          {CATEGORY_LABELS[rec.category] ?? rec.category}
                        </Badge>
                      </div>
                      <p className="font-medium">{rec.title}</p>
                      <p className="text-sm text-muted-foreground mt-1">{rec.description}</p>
                      <div className="flex items-center gap-1.5 mt-2 text-sm text-brand">
                        <ArrowRight className="h-3.5 w-3.5" />
                        <span>{rec.action}</span>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
