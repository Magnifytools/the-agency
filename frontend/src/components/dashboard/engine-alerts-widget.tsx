import { Link } from "react-router-dom"
import type { Client, EngineAlert } from "@/lib/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { AlertTriangle, AlertCircle, ArrowRight } from "lucide-react"

interface Props {
  clients: Client[]
}

interface FlatAlert extends EngineAlert {
  clientId: number
  clientName: string
}

export function EngineAlertsWidget({ clients }: Props) {
  // Flatten alerts from all clients, attach client info
  const allAlerts: FlatAlert[] = []
  for (const client of clients) {
    const alerts = client.engine_alerts_data?.alerts
    if (!alerts?.length) continue
    for (const alert of alerts) {
      if (alert.severity === "critical" || alert.severity === "warning") {
        allAlerts.push({
          ...alert,
          clientId: client.id,
          clientName: client.name,
        })
      }
    }
  }

  if (allAlerts.length === 0) return null

  // Sort: critical first, then by date
  const severityOrder: Record<string, number> = { critical: 0, warning: 1 }
  allAlerts.sort((a, b) => {
    const sa = severityOrder[a.severity] ?? 2
    const sb = severityOrder[b.severity] ?? 2
    if (sa !== sb) return sa - sb
    return (b.detected_at || "").localeCompare(a.detected_at || "")
  })

  const displayed = allAlerts.slice(0, 5)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-500" /> Alertas SEO Engine
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {displayed.map((alert) => (
            <Link
              key={`${alert.clientId}-${alert.type}-${alert.detected_at}`}
              to={`/clients/${alert.clientId}?tab=seo`}
              className="flex items-start gap-3 p-2 rounded-md border hover:bg-muted/50 transition-colors"
            >
              {alert.severity === "critical" ? (
                <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
              ) : (
                <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
              )}
              <div className="flex-1 min-w-0">
                <p className="text-sm">
                  <span className="font-medium">{alert.clientName}:</span>{" "}
                  {alert.title}
                </p>
              </div>
              <Badge variant={alert.severity === "critical" ? "destructive" : "warning"} className="shrink-0">
                {alert.severity}
              </Badge>
              <ArrowRight className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-0.5" />
            </Link>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
