import type { ProfitabilityStatus } from "@/lib/types/common"

/**
 * Mapa único de estados de rentabilidad.
 *
 * Antes había cuatro (dashboard, executive, ficha de cliente x2) y cada uno
 * resolvía el estado desconocido a su manera: uno pintaba el identificador
 * crudo, los otros tres caían en "No rentable" por el `else`. Al añadir
 * `no_data` eso habría anunciado como "No rentable" a cualquier cliente sin
 * tarifa configurada. Un estado nuevo se añade AQUÍ y las cuatro pantallas
 * lo heredan.
 */
export const PROFITABILITY_STATUS: Record<
  ProfitabilityStatus,
  {
    label: string
    variant: "success" | "warning" | "destructive" | "secondary"
    /** Color para las barras de Recharts en el dashboard ejecutivo. */
    chartColor: string
    /** true = el cliente pierde dinero de verdad, no es falta de datos. */
    isLosingMoney: boolean
  }
> = {
  profitable: {
    label: "Rentable",
    variant: "success",
    chartColor: "#22c55e",
    isLosingMoney: false,
  },
  at_risk: {
    label: "En riesgo",
    variant: "warning",
    chartColor: "#eab308",
    isLosingMoney: false,
  },
  unprofitable: {
    label: "No rentable",
    variant: "destructive",
    chartColor: "#ef4444",
    isLosingMoney: true,
  },
  no_data: {
    label: "Sin tarifa",
    variant: "secondary",
    chartColor: "#94a3b8",
    isLosingMoney: false,
  },
}

const FALLBACK = {
  label: "Sin datos",
  variant: "secondary" as const,
  chartColor: "#94a3b8",
  isLosingMoney: false,
}

/** Resuelve un estado; nunca devuelve el identificador crudo. */
export function profitabilityStatus(status: string | null | undefined) {
  return PROFITABILITY_STATUS[status as ProfitabilityStatus] ?? FALLBACK
}
