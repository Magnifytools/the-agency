import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Tooltip } from "@/components/ui/tooltip"
import type { ClientHealthScore } from "@/lib/types"

interface HealthGridProps {
  data: ClientHealthScore[]
}

const riskConfig = {
  healthy: { label: "Saludable", variant: "success" as const, color: "bg-green-500" },
  warning: { label: "Atención", variant: "warning" as const, color: "bg-yellow-500" },
  at_risk: { label: "En riesgo", variant: "destructive" as const, color: "bg-red-500" },
}

export function HealthGrid({ data }: HealthGridProps) {
  const sorted = [...data].sort((a, b) => a.score - b.score)

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {sorted.map((client) => {
        const cfg = riskConfig[client.risk_level] || riskConfig.warning
        return (
          <Card key={client.client_id} className="p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium truncate mr-2">{client.client_name}</span>
              <Badge variant={cfg.variant} className="shrink-0">{cfg.label}</Badge>
            </div>
            <div className="flex items-center gap-3">
              <Tooltip
                content={
                  <div className="space-y-1 text-xs">
                    <p className="font-semibold mb-1.5">Factores del score</p>
                    <p>Comunicación: <strong>{client.factors.communication}</strong>/25</p>
                    <p>Tareas: <strong>{client.factors.tasks}</strong>/25</p>
                    <p>Rentabilidad: <strong>{client.factors.profitability}</strong>/20</p>
                    <p>Digests: <strong>{client.factors.digests}</strong>/15</p>
                    <p>Seguimientos: <strong>{client.factors.followups}</strong>/15</p>
                  </div>
                }
                side="top"
              >
                <div className="text-2xl font-bold cursor-help">{client.score}</div>
              </Tooltip>
              <div className="flex-1">
                <div className="h-2 rounded-full bg-muted overflow-hidden">
                  <div
                    className={`h-full rounded-full ${cfg.color} transition-all`}
                    style={{ width: `${client.score}%` }}
                  />
                </div>
                <div className="flex justify-between mt-1.5 text-[10px] text-muted-foreground">
                  <span>Comm: {client.factors.communication}</span>
                  <span>Tareas: {client.factors.tasks}</span>
                  <span>Rent: {client.factors.profitability}</span>
                </div>
              </div>
            </div>
          </Card>
        )
      })}
    </div>
  )
}
