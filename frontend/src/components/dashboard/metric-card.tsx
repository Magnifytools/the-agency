import { Card, CardContent } from "@/components/ui/card"
import { InfoTooltip } from "@/components/ui/tooltip"
import type { LucideIcon } from "lucide-react"

interface MetricCardProps {
  icon: LucideIcon
  label: string
  value: string | number
  subtitle?: string
  tooltip?: string
  delta?: number
}

export function MetricCard({ icon: Icon, label, value, subtitle, tooltip, delta }: MetricCardProps) {
  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-1.5">
              {label}
              {tooltip && <InfoTooltip content={tooltip} />}
            </p>
            <p className="kpi-value">{value}</p>
            {delta !== undefined && (
              <p className={`text-xs mt-1 font-medium ${delta >= 0 ? "text-green-500" : "text-red-500"}`}>
                {delta >= 0 ? "↑" : "↓"} {Math.abs(delta).toLocaleString("es-ES", { style: "currency", currency: "EUR" })} vs mes ant.
              </p>
            )}
            {subtitle && <p className="text-xs text-muted-foreground mt-1 mono">{subtitle}</p>}
          </div>
          <div className="p-2.5 rounded-[10px] bg-brand/10">
            <Icon className="h-5 w-5 text-brand" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
