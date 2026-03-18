import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { capacityApi } from "@/lib/api"
import type { CapacityMemberDetail, CapacityTask } from "@/lib/types"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Users, ChevronDown, ChevronRight, AlertTriangle, Clock, Building2, FolderKanban } from "lucide-react"

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

const priorityConfig: Record<string, { label: string; className: string }> = {
  critical: { label: "Critica", className: "text-red-600 bg-red-100 dark:bg-red-900/30" },
  high: { label: "Alta", className: "text-orange-600 bg-orange-100 dark:bg-orange-900/30" },
  medium: { label: "Media", className: "text-blue-600 bg-blue-100 dark:bg-blue-900/30" },
  low: { label: "Baja", className: "text-slate-500 bg-slate-100 dark:bg-slate-800" },
}

const statusLabels: Record<string, string> = {
  backlog: "Backlog",
  pending: "Pendiente",
  in_progress: "En curso",
  waiting: "Esperando",
  in_review: "Revision",
}

function TaskRow({ task }: { task: CapacityTask }) {
  const prio = priorityConfig[task.priority] || priorityConfig.medium
  const todayStr = new Date().toISOString().slice(0, 10)
  const isOverdue = task.due_date && task.due_date < todayStr

  return (
    <div className="flex items-center justify-between py-1.5 px-2 rounded hover:bg-muted/40 group text-sm">
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${prio.className}`}>
          {prio.label[0]}
        </span>
        <span className="truncate">{task.title}</span>
        {task.project_name && (
          <span className="hidden sm:inline text-xs text-muted-foreground/60 shrink-0">
            <FolderKanban className="h-3 w-3 inline mr-0.5" />
            {task.project_name}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0 ml-2">
        <span className="text-xs text-muted-foreground">
          {statusLabels[task.status] || task.status}
        </span>
        {task.estimated_minutes > 0 && (
          <span className="text-xs mono text-muted-foreground flex items-center gap-0.5">
            <Clock className="h-3 w-3" />
            {formatMinutes(task.estimated_minutes)}
          </span>
        )}
        {task.estimated_minutes === 0 && (
          <span className="text-xs text-amber-500 flex items-center gap-0.5" title="Sin estimacion">
            <AlertTriangle className="h-3 w-3" />
          </span>
        )}
        {task.due_date && (
          <span className={`text-xs ${isOverdue ? "text-red-500 font-medium" : "text-muted-foreground"}`}>
            {new Date(task.due_date).toLocaleDateString("es-ES", { day: "2-digit", month: "short" })}
          </span>
        )}
      </div>
    </div>
  )
}

function MemberCard({ member }: { member: CapacityMemberDetail }) {
  const [expanded, setExpanded] = useState(false)
  const cfg = statusConfig[member.status]
  const barWidth = Math.min(member.load_percent, 150)
  const noEstimate = member.clients.flatMap((c) => c.tasks).filter((t) => t.estimated_minutes === 0).length

  return (
    <Card className={member.status === "overloaded" ? "border-red-300/50" : ""}>
      <CardContent className="p-4">
        {/* Header */}
        <div
          className="flex items-center justify-between cursor-pointer"
          onClick={() => setExpanded(!expanded)}
        >
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 rounded-full bg-muted flex items-center justify-center">
              <Users className="h-4 w-4 text-muted-foreground" />
            </div>
            <div>
              <span className="font-medium">{member.full_name}</span>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span>{member.task_count} tareas</span>
                <span>{member.clients.length} clientes</span>
                {noEstimate > 0 && (
                  <span className="text-amber-500 flex items-center gap-0.5">
                    <AlertTriangle className="h-3 w-3" />
                    {noEstimate} sin estimar
                  </span>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm mono">
              {formatMinutes(member.assigned_minutes)} / {member.weekly_hours}h
            </span>
            <Badge variant={cfg.variant}>{cfg.label}</Badge>
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </div>
        </div>

        {/* Capacity bar */}
        <div className="h-2.5 bg-muted rounded-full overflow-hidden mt-3">
          <div
            className={`h-full rounded-full transition-all ${cfg.color}`}
            style={{ width: `${Math.min(barWidth, 100)}%` }}
          />
        </div>
        <div className="flex justify-between mt-0.5">
          <span className="text-[10px] text-muted-foreground">0%</span>
          <span className={`text-xs font-bold ${member.load_percent > 90 ? "text-red-500" : member.load_percent > 70 ? "text-amber-500" : "text-green-600"}`}>
            {member.load_percent}%
          </span>
          <span className="text-[10px] text-muted-foreground">100%</span>
        </div>

        {/* Expanded: tasks grouped by client */}
        {expanded && member.clients.length > 0 && (
          <div className="mt-4 space-y-3">
            {member.clients.map((clientGroup) => (
              <div key={clientGroup.client_id ?? "none"} className="border border-border rounded-lg overflow-hidden">
                <div className="flex items-center justify-between px-3 py-2 bg-muted/30">
                  <div className="flex items-center gap-2">
                    <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-sm font-medium">{clientGroup.client_name}</span>
                    <span className="text-xs text-muted-foreground">({clientGroup.tasks.length})</span>
                  </div>
                  <span className="text-xs mono text-muted-foreground">{formatMinutes(clientGroup.total_minutes)}</span>
                </div>
                <div className="px-1 py-1 divide-y divide-border/30">
                  {clientGroup.tasks.map((task) => (
                    <TaskRow key={task.task_id} task={task} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {expanded && member.clients.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-4 mt-3">Sin tareas asignadas</p>
        )}
      </CardContent>
    </Card>
  )
}

export default function CapacityPage() {
  const { data: members = [], isLoading } = useQuery({
    queryKey: ["capacity-detail"],
    queryFn: () => capacityApi.detail(),
  })

  if (isLoading) return <p className="text-muted-foreground">Cargando capacidad del equipo...</p>

  const total = members.length
  const overloaded = members.filter((m) => m.status === "overloaded").length
  const available = members.filter((m) => m.status === "available").length
  const totalAssigned = members.reduce((s, m) => s + m.assigned_minutes, 0)
  const totalCapacity = members.reduce((s, m) => s + (m.weekly_hours * 60), 0)
  const teamLoad = totalCapacity > 0 ? Math.round((totalAssigned / totalCapacity) * 100) : 0

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold uppercase tracking-wide">Capacidad del equipo</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Carga de trabajo por miembro — basado en tiempo estimado de tareas activas
        </p>
      </div>

      {/* Summary KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Equipo</p>
            <p className="text-2xl font-bold mt-1">{total}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Disponibles</p>
            <p className="text-2xl font-bold mt-1 text-green-600">{available}</p>
          </CardContent>
        </Card>
        <Card className={overloaded > 0 ? "border-red-300" : ""}>
          <CardContent className="p-4 text-center">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Sobrecargados</p>
            <p className={`text-2xl font-bold mt-1 ${overloaded > 0 ? "text-red-500" : ""}`}>{overloaded}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Carga total</p>
            <p className={`text-2xl font-bold mt-1 ${teamLoad > 90 ? "text-red-500" : teamLoad > 70 ? "text-amber-500" : "text-green-600"}`}>{teamLoad}%</p>
          </CardContent>
        </Card>
      </div>

      {/* Team capacity bar */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">Capacidad total del equipo</span>
            <span className="text-sm mono">{formatMinutes(totalAssigned)} / {formatMinutes(totalCapacity)}</span>
          </div>
          <div className="h-4 bg-muted rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${teamLoad > 90 ? "bg-red-500" : teamLoad > 70 ? "bg-amber-500" : "bg-green-500"}`}
              style={{ width: `${Math.min(teamLoad, 100)}%` }}
            />
          </div>
        </CardContent>
      </Card>

      {/* Member cards */}
      <div className="space-y-3">
        {members.map((m) => (
          <MemberCard key={m.user_id} member={m} />
        ))}
      </div>

      {members.length === 0 && (
        <p className="text-muted-foreground text-center py-12">No hay miembros activos</p>
      )}
    </div>
  )
}
