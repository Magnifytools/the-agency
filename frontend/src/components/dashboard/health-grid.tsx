import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import type { ClientHealthScore } from "@/lib/types"
import { clientHealthPresentation } from "@/components/dashboard/client-health-presentation"

interface HealthGridProps {
  data: ClientHealthScore[]
}

export function HealthGrid({ data }: HealthGridProps) {
  const sorted = [...data].sort((a, b) => {
    const riskDifference = b.risk_signals.length - a.risk_signals.length
    return riskDifference || a.client_name.localeCompare(b.client_name, "es")
  })

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {sorted.map((client) => {
        const presentation = clientHealthPresentation(client)
        return (
          <Card key={client.client_id} className="p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium truncate mr-2">{client.client_name}</span>
              <Badge variant={presentation.variant} className="shrink-0">{presentation.label}</Badge>
            </div>
            <p className="text-xs text-muted-foreground">{presentation.detail}</p>
            {client.risk_signals.length > 0 && <ul className="mt-2 space-y-1 text-xs text-destructive">
              {client.risk_signals.map((signal) => <li key={signal}>{signal}</li>)}
            </ul>}
            <div className="mt-2 space-y-1 text-xs text-muted-foreground">
              {(Object.keys(client.observations) as Array<keyof typeof client.observations>).map((factor) => (
                <p key={factor}>{client.observations[factor]}</p>
              ))}
            </div>
            {client.score != null && <details className="mt-2 text-xs text-muted-foreground"><summary className="cursor-pointer">Índice orientativo legado</summary><p className="mt-1">{client.score} puntos</p></details>}
          </Card>
        )
      })}
    </div>
  )
}
