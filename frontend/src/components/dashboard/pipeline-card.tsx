import type { PipelineSummary } from "@/lib/types"

interface PipelineCardProps {
  data: PipelineSummary
}

const stageLabels: Record<string, { label: string; color: string }> = {
  new: { label: "Nuevo", color: "bg-blue-500" },
  contacted: { label: "Contactado", color: "bg-cyan-500" },
  discovery: { label: "Discovery", color: "bg-purple-500" },
  proposal: { label: "Propuesta", color: "bg-yellow-500" },
  negotiation: { label: "Negociación", color: "bg-orange-500" },
  won: { label: "Ganado", color: "bg-green-500" },
  lost: { label: "Perdido", color: "bg-red-500" },
}

const fmt = (n: number) => n.toLocaleString("es-ES", { style: "currency", currency: "EUR" })

export function PipelineCard({ data }: PipelineCardProps) {
  const activeStages = data.stages.filter((s) => s.status !== "won" && s.status !== "lost")
  const totalActive = activeStages.reduce((sum, s) => sum + s.count, 0)

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <div>
          <span className="text-2xl font-bold text-brand">{fmt(data.total_value)}</span>
          <span className="text-xs text-muted-foreground ml-2">valor pipeline</span>
        </div>
        <span className="text-sm text-muted-foreground">{data.total_leads} leads totales</span>
      </div>

      {/* Segmented bar */}
      {totalActive > 0 && (
        <div className="flex h-4 rounded-full overflow-hidden gap-0.5">
          {activeStages.map((stage) => {
            const cfg = stageLabels[stage.status] || { label: stage.status, color: "bg-gray-500" }
            const widthPct = (stage.count / totalActive) * 100
            return (
              <div
                key={stage.status}
                className={`${cfg.color} transition-all`}
                style={{ width: `${widthPct}%` }}
                title={`${cfg.label}: ${stage.count}`}
              />
            )
          })}
        </div>
      )}

      {/* Stage list */}
      <div className="space-y-2">
        {data.stages.map((stage) => {
          const cfg = stageLabels[stage.status] || { label: stage.status, color: "bg-gray-500" }
          return (
            <div key={stage.status} className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2">
                <div className={`w-2.5 h-2.5 rounded-full ${cfg.color}`} />
                <span>{cfg.label}</span>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-muted-foreground">{stage.count}</span>
                <span className="font-mono w-24 text-right">{fmt(stage.total_value)}</span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
