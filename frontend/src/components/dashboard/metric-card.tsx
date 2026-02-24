import { Card, CardContent } from "@/components/ui/card"
import type { LucideIcon } from "lucide-react"

interface MetricCardProps {
  icon: LucideIcon
  label: string
  value: string | number
  subtitle?: string
}

export function MetricCard({ icon: Icon, label, value, subtitle }: MetricCardProps) {
  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-2">{label}</p>
            <p className="kpi-value">{value}</p>
            {subtitle && <p className="text-xs text-muted-foreground mt-2 mono">{subtitle}</p>}
          </div>
          <div className="p-2.5 rounded-[10px] bg-brand/10">
            <Icon className="h-5 w-5 text-brand" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
