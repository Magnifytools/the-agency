import { useQuery } from "@tanstack/react-query"
import { capacityApi } from "@/lib/api"
import type { CapacityMember } from "@/lib/types"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Users } from "lucide-react"

function formatMinutes(m: number): string {
  const h = Math.floor(m / 60)
  const mins = m % 60
  if (h && mins) return `${h}h ${mins}m`
  if (h) return `${h}h`
  return `${mins}m`
}

const statusConfig = {
  available: { label: "Disponible", variant: "success" as const, color: "bg-green-500" },
  busy: { label: "Ocupado", variant: "warning" as const, color: "bg-amber-500" },
  overloaded: { label: "Sobrecargado", variant: "destructive" as const, color: "bg-red-500" },
}

export default function CapacityPage() {
  const { data: members = [], isLoading } = useQuery({
    queryKey: ["capacity"],
    queryFn: () => capacityApi.get(),
  })

  if (isLoading) return <p className="text-muted-foreground">Cargando capacidad del equipo...</p>

  // Summary
  const total = members.length
  const overloaded = members.filter((m: CapacityMember) => m.status === "overloaded").length
  const available = members.filter((m: CapacityMember) => m.status === "available").length

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold uppercase tracking-wide">Capacidad del equipo</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Carga de trabajo semanal por miembro — basado en tiempo estimado de tareas activas
        </p>
      </div>

      {/* Summary KPIs */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Miembros</p>
            <p className="kpi-value mt-1">{total}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Disponibles</p>
            <p className="kpi-value mt-1 text-green-600">{available}</p>
          </CardContent>
        </Card>
        <Card className={overloaded > 0 ? "border-red-300" : ""}>
          <CardContent className="p-4 text-center">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Sobrecargados</p>
            <p className={`kpi-value mt-1 ${overloaded > 0 ? "text-red-500" : ""}`}>{overloaded}</p>
          </CardContent>
        </Card>
      </div>

      {/* Capacity bars */}
      <div className="space-y-3">
        {members.map((m: CapacityMember) => {
          const cfg = statusConfig[m.status]
          const barWidth = Math.min(m.load_percent, 150) // cap visual at 150%

          return (
            <Card key={m.user_id}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3">
                    <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center">
                      <Users className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <div>
                      <span className="font-medium">{m.full_name}</span>
                      <span className="text-xs text-muted-foreground ml-2">{m.task_count} tareas</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm mono">
                      {formatMinutes(m.assigned_minutes)} / {m.weekly_hours}h
                    </span>
                    <Badge variant={cfg.variant}>{cfg.label}</Badge>
                  </div>
                </div>
                <div className="h-3 bg-muted rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${cfg.color}`}
                    style={{ width: `${Math.min(barWidth, 100)}%` }}
                  />
                </div>
                <div className="flex justify-between mt-1">
                  <span className="text-[10px] text-muted-foreground">0%</span>
                  <span className={`text-xs font-bold ${m.load_percent > 90 ? "text-red-500" : m.load_percent > 70 ? "text-amber-500" : "text-green-600"}`}>
                    {m.load_percent}%
                  </span>
                  <span className="text-[10px] text-muted-foreground">100%</span>
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>

      {members.length === 0 && (
        <p className="text-muted-foreground text-center py-12">No hay miembros activos</p>
      )}
    </div>
  )
}
