import { TrendingDown, TrendingUp } from "lucide-react"

/**
 * Variación con flecha y color. `invert`: un valor negativo es bueno.
 * `suffix`: "%" por defecto; "" para posiciones, " pp" para puntos de CTR.
 * `digits`: decimales fijos con formato español (sin él, el valor tal cual).
 */
export function DeltaBadge({
  value,
  invert,
  suffix = "%",
  digits,
}: {
  value: number | null | undefined
  invert?: boolean
  suffix?: string
  digits?: number
}) {
  if (value == null) return null
  const positive = invert ? value < 0 : value > 0
  const shown = digits == null
    ? String(value)
    : value.toLocaleString("es-ES", { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-medium ${positive ? "text-green-600" : value === 0 ? "text-muted-foreground" : "text-red-500"}`}>
      {value > 0 ? <TrendingUp className="h-3 w-3" /> : value < 0 ? <TrendingDown className="h-3 w-3" /> : null}
      {value > 0 ? "+" : ""}{shown}{suffix}
    </span>
  )
}
