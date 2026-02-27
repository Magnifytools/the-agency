import type { CapacityMember } from "@/lib/types"

interface CapacityBarsProps {
  data: CapacityMember[]
}

const statusConfig = {
  available: { label: "Disponible", color: "bg-green-500", text: "text-green-400" },
  busy: { label: "Ocupado", color: "bg-yellow-500", text: "text-yellow-400" },
  overloaded: { label: "Sobrecargado", color: "bg-red-500", text: "text-red-400" },
}

export function CapacityBars({ data }: CapacityBarsProps) {
  return (
    <div className="space-y-4">
      {data.map((member) => {
        const cfg = statusConfig[member.status] || statusConfig.available
        const pct = Math.min(member.load_percent, 100)
        return (
          <div key={member.user_id}>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm font-medium">{member.full_name}</span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">{member.task_count} tareas</span>
                <span className={`text-sm font-bold ${cfg.text}`}>{member.load_percent}%</span>
              </div>
            </div>
            <div className="h-3 rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full ${cfg.color} transition-all`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <div className="flex justify-between mt-1 text-[10px] text-muted-foreground">
              <span>{Math.round(member.assigned_minutes / 60)}h asignadas</span>
              <span>{member.weekly_hours}h/semana</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
