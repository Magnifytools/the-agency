import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { CheckCircle2, ChevronDown, ChevronUp } from "lucide-react"
import { DeliveryReceipts } from "@/components/delivery-receipts"
import { dailysApi } from "@/lib/api"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useBusinessDate } from "@/hooks/use-business-date"

interface DailyUpdateWidgetProps {
  userId: number
  readOnly?: boolean
}

export function DailyUpdateWidget({ userId, readOnly = false }: DailyUpdateWidgetProps) {
  const [expanded, setExpanded] = useState(false)
  const today = useBusinessDate()
  const dailyQuery = useQuery({
    queryKey: ["dailys", userId, "today", today],
    queryFn: () => dailysApi.list({ user_id: userId, date_from: today, date_to: today, limit: 1 }),
  })
  const daily = dailyQuery.data?.[0]

  return (
    <Card>
      <CardContent className="space-y-3 pt-4 pb-4">
        {dailyQuery.isPending ? (
          <p role="status" className="text-sm text-muted-foreground">Consultando el resumen de hoy…</p>
        ) : dailyQuery.isError ? (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p role="alert" className="text-sm">No se pudo consultar el resumen de hoy.</p>
            <Button size="sm" variant="outline" onClick={() => void dailyQuery.refetch()}>Reintentar</Button>
          </div>
        ) : daily ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="flex items-center gap-2 text-sm font-medium">
                <CheckCircle2 aria-hidden className="size-4" />
                {daily.status === "sent" ? "Resumen de hoy enviado" : "Resumen de hoy guardado como borrador"}
              </p>
              <Button size="sm" variant="ghost" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
                {expanded ? <ChevronUp aria-hidden className="mr-1 size-3" /> : <ChevronDown aria-hidden className="mr-1 size-3" />}
                {expanded ? "Ocultar texto" : "Ver texto"}
              </Button>
            </div>
            {expanded && <p className="whitespace-pre-wrap break-words rounded-lg bg-muted/50 p-3 text-sm">{daily.raw_text}</p>}
            {!readOnly && <DeliveryReceipts sourceKind="daily" sourceId={daily.id} />}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">{readOnly ? "Sin resumen guardado hoy." : "Revisa los hechos del día y añade tus notas al cierre."}</p>
        )}
        {!readOnly && (
          <Link to="/dailys" className="inline-flex rounded-lg border border-border px-3 py-2 text-sm font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
            {daily ? "Abrir mi resumen diario" : "Cerrar el día"}
          </Link>
        )}
      </CardContent>
    </Card>
  )
}
