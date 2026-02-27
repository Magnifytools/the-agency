import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { FileText, Plus, Sparkles, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { reportsApi } from "@/lib/api"
import type { ReportNarrative } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { getErrorMessage } from "@/lib/utils"

interface Props {
  clientId: number
  clientName: string
}

export function ClientReportsTab({ clientId, clientName }: Props) {
  const qc = useQueryClient()
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [narrative, setNarrative] = useState<ReportNarrative | null>(null)

  const { data: reports = [], isLoading } = useQuery({
    queryKey: ["client-reports", clientId],
    queryFn: () => reportsApi.list({ client_id: clientId, limit: 20 }),
  })

  const generateMut = useMutation({
    mutationFn: () =>
      reportsApi.generate({
        type: "client_status",
        client_id: clientId,
        period: "month",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client-reports", clientId] })
      toast.success("Informe generado")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const narrativeMut = useMutation({
    mutationFn: (id: number) => reportsApi.aiNarrative(id),
    onSuccess: (data) => setNarrative(data),
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  if (isLoading) return <p className="text-sm text-muted-foreground">Cargando informes...</p>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Informes de {clientName}</h3>
        <Button
          size="sm"
          onClick={() => generateMut.mutate()}
          disabled={generateMut.isPending}
        >
          {generateMut.isPending ? (
            <><Loader2 className="h-4 w-4 mr-1 animate-spin" /> Generando...</>
          ) : (
            <><Plus className="h-4 w-4 mr-1" /> Generar informe mensual</>
          )}
        </Button>
      </div>

      {reports.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-8">
          No hay informes generados para este cliente. Pulsa el boton para crear uno.
        </p>
      ) : (
        <div className="space-y-3">
          {reports.map((report) => (
            <Card key={report.id}>
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div
                    className="flex-1 cursor-pointer"
                    onClick={() => setExpandedId(expandedId === report.id ? null : report.id)}
                  >
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-muted-foreground" />
                      <span className="font-medium">{report.title}</span>
                      <Badge variant="secondary" className="text-[10px]">{report.type}</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">
                      {new Date(report.generated_at).toLocaleDateString("es-ES", {
                        day: "numeric",
                        month: "long",
                        year: "numeric",
                      })}
                      {report.period_start && report.period_end && (
                        <> — {new Date(report.period_start).toLocaleDateString("es-ES")} a {new Date(report.period_end).toLocaleDateString("es-ES")}</>
                      )}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setNarrative(null)
                      narrativeMut.mutate(report.id)
                    }}
                    disabled={narrativeMut.isPending}
                  >
                    <Sparkles className="h-4 w-4 mr-1" />
                    {narrativeMut.isPending ? "..." : "IA"}
                  </Button>
                </div>

                {/* Expanded sections */}
                {expandedId === report.id && (
                  <div className="mt-3 border-t pt-3 space-y-3">
                    {report.summary && (
                      <p className="text-sm">{report.summary}</p>
                    )}
                    {report.sections.map((s, i) => (
                      <div key={i}>
                        <h4 className="text-sm font-medium">{s.title}</h4>
                        <p className="text-sm text-muted-foreground whitespace-pre-wrap">{s.content}</p>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* AI Narrative */}
      {narrative && (
        <Card className="border-brand/30">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-brand" /> Narrativa IA
            </CardTitle>
          </CardHeader>
          <CardContent>
            {narrative.executive_summary && (
              <p className="text-sm font-medium mb-3">{narrative.executive_summary}</p>
            )}
            <p className="text-sm text-muted-foreground whitespace-pre-wrap">{narrative.narrative}</p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
