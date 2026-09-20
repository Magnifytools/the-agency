import type { ClientHealthScore } from "@/lib/types"

export function clientHealthPresentation(client: ClientHealthScore) {
  if (client.risk_signals.length > 0) return {
    label: client.risk_signals.length === 1 ? "1 riesgo" : `${client.risk_signals.length} riesgos`,
    detail: "Necesita atención",
    variant: "destructive" as const,
  }
  if (!client.enough_information) return {
    label: "Información incompleta",
    detail: "Faltan fuentes para valorar las condiciones",
    variant: "secondary" as const,
  }
  return {
    label: "Sin riesgos observados",
    detail: "En las fuentes disponibles",
    variant: "success" as const,
  }
}
