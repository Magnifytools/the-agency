import { describe, it, expect } from "vitest"
import { PROFITABILITY_STATUS, profitabilityStatus } from "@/lib/profitability"

/**
 * Antes había cuatro mapas de estado (dashboard, executive, ficha de cliente
 * x2). Al añadir `no_data` en el backend, uno habría pintado el identificador
 * crudo "no_data" y los otros tres habrían caído en su `else` anunciando
 * "No rentable" a cualquier cliente sin tarifa configurada.
 *
 * Estos tests protegen esa costura: todo estado que exista en el backend tiene
 * etiqueta aquí, y ninguna ruta devuelve el identificador sin traducir.
 */
describe("mapa de estados de rentabilidad", () => {
  // Debe coincidir con ProfitabilityStatus en backend/schemas/dashboard.py
  const ESTADOS_DEL_BACKEND = [
    "profitable",
    "at_risk",
    "unprofitable",
    "no_data",
  ] as const

  it("cubre todos los estados que emite el backend", () => {
    for (const estado of ESTADOS_DEL_BACKEND) {
      expect(PROFITABILITY_STATUS).toHaveProperty(estado)
    }
    expect(Object.keys(PROFITABILITY_STATUS).sort()).toEqual(
      [...ESTADOS_DEL_BACKEND].sort()
    )
  })

  it("nunca devuelve el identificador crudo", () => {
    for (const estado of ESTADOS_DEL_BACKEND) {
      expect(profitabilityStatus(estado).label).not.toBe(estado)
    }
  })

  it("'sin tarifa' no se anuncia como 'no rentable'", () => {
    const sinTarifa = profitabilityStatus("no_data")
    expect(sinTarifa.label).toBe("Sin tarifa")
    expect(sinTarifa.isLosingMoney).toBe(false)
    expect(sinTarifa.variant).not.toBe("destructive")
  })

  it("solo 'unprofitable' marca pérdida real de dinero", () => {
    const perdiendo = ESTADOS_DEL_BACKEND.filter(
      (e) => profitabilityStatus(e).isLosingMoney
    )
    expect(perdiendo).toEqual(["unprofitable"])
  })

  it("degrada a un texto legible ante un estado desconocido", () => {
    const desconocido = profitabilityStatus("estado_futuro")
    expect(desconocido.label).toBe("Sin datos")
    expect(desconocido.label).not.toBe("estado_futuro")
  })

  it("tolera null y undefined", () => {
    expect(profitabilityStatus(null).label).toBe("Sin datos")
    expect(profitabilityStatus(undefined).label).toBe("Sin datos")
  })
})
