import { Badge } from "@/components/ui/badge"
import type { SeoTrend } from "@/lib/types/client"
import { formatChangePct } from "./seo-trend"

const PRESENTATION: Record<SeoTrend, { variant: "success" | "secondary" | "warning" | "destructive"; label: string }> = {
  up: { variant: "success", label: "Sube" },
  stable: { variant: "secondary", label: "Estable" },
  down: { variant: "warning", label: "Baja" },
  drop_alert: { variant: "destructive", label: "Caída" },
}

interface SeoTrendBadgeProps {
  linked: boolean
  trend: SeoTrend | null
  changePct: number | null
}

/** Semáforo SEO: clics orgánicos de 30 días frente a los 30 anteriores (Engine). */
export function SeoTrendBadge({ linked, trend, changePct }: SeoTrendBadgeProps) {
  if (!linked) return <span className="text-xs text-muted-foreground">Sin Engine</span>
  if (!trend || changePct == null) return <span className="text-xs text-muted-foreground">Sin periodo anterior</span>
  const { variant, label } = PRESENTATION[trend]
  return (
    <Badge variant={variant} className="mono whitespace-nowrap" title={`${label}: clics de los últimos 30 días frente a los 30 anteriores`}>
      {formatChangePct(changePct)}
    </Badge>
  )
}
