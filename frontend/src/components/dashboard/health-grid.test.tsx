import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { HealthGrid } from "./health-grid"
import type { ClientHealthScore } from "@/lib/types"

const noData: ClientHealthScore = {
  client_id: 1,
  client_name: "Cliente sin fuentes",
  score: null,
  factors: { communication: null, tasks: null, digests: null, profitability: null, followups: null },
  factor_max: { communication: 25, tasks: 25, digests: 15, profitability: 20, followups: 15 },
  observations: {
    communication: "Fuente no disponible",
    tasks: "Fuente no disponible",
    digests: "Fuente no disponible",
    profitability: "Presupuesto no configurado",
    followups: "Fuente no disponible",
  },
  available_weight: 0,
  available_source_count: 0,
  enough_information: false,
  risk_level: "no_data",
}

describe("HealthGrid", () => {
  it("shows insufficient information instead of a healthy or risk score", () => {
    render(<HealthGrid data={[noData]} />)

    expect(screen.getByText("Sin datos suficientes")).toBeInTheDocument()
    expect(screen.getByText("—")).toBeInTheDocument()
    expect(screen.queryByText("Saludable")).not.toBeInTheDocument()
    expect(screen.queryByText("En riesgo")).not.toBeInTheDocument()
  })

  it("shows a risk classification when it is backed by measured conditions", () => {
    render(<HealthGrid data={[{
      ...noData,
      client_name: "Cliente con riesgo real",
      score: 18,
      factors: { ...noData.factors, tasks: 0, digests: 3, profitability: 8 },
      observations: {
        ...noData.observations,
        tasks: "0/4 completadas · 3 vencidas",
        digests: "1 resumen en 4 semanas",
        profitability: "Coste estimado 920 de 1000",
      },
      available_weight: 60,
      available_source_count: 3,
      enough_information: true,
      risk_level: "at_risk",
    }]} />)

    expect(screen.getByText("En riesgo")).toBeInTheDocument()
    expect(screen.getByText("18")).toBeInTheDocument()
  })
})
