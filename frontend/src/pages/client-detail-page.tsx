import { useState } from "react"
import { useParams, Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { clientsApi, timeEntriesApi } from "@/lib/api"
import type { TaskStatus } from "@/lib/types"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { ArrowLeft, Clock } from "lucide-react"
import { TimerButton } from "@/components/timer/timer-button"
import { TimeLogDialog } from "@/components/timer/time-log-dialog"
import { CommunicationList } from "@/components/communications/communication-list"

function formatMinutes(m: number): string {
  const h = Math.floor(m / 60)
  const mins = m % 60
  if (h && mins) return `${h}h ${mins}m`
  if (h) return `${h}h`
  return `${mins}m`
}

const statusBadge = (status: string) => {
  const map: Record<string, { label: string; variant: "success" | "warning" | "secondary" }> = {
    active: { label: "Activo", variant: "success" },
    paused: { label: "Pausado", variant: "warning" },
    finished: { label: "Finalizado", variant: "secondary" },
  }
  const { label, variant } = map[status] || { label: status, variant: "secondary" as any }
  return <Badge variant={variant}>{label}</Badge>
}

const taskStatusBadge = (status: TaskStatus) => {
  const map: Record<TaskStatus, { label: string; variant: "secondary" | "warning" | "success" }> = {
    pending: { label: "Pendiente", variant: "secondary" },
    in_progress: { label: "En curso", variant: "warning" },
    completed: { label: "Completada", variant: "success" },
  }
  const { label, variant } = map[status]
  return <Badge variant={variant}>{label}</Badge>
}

export default function ClientDetailPage() {
  const { id } = useParams<{ id: string }>()
  const clientId = Number(id)
  const [timeLogTaskId, setTimeLogTaskId] = useState<{ id: number; title: string } | null>(null)

  const { data: summary, isLoading } = useQuery({
    queryKey: ["client-summary", clientId],
    queryFn: () => clientsApi.summary(clientId),
    enabled: !!clientId,
  })

  const { data: recentEntries = [] } = useQuery({
    queryKey: ["time-entries-client", clientId],
    queryFn: async () => {
      if (!summary?.tasks.length) return []
      const allEntries = await Promise.all(
        summary.tasks.slice(0, 10).map((t) => timeEntriesApi.list({ task_id: t.id }))
      )
      return allEntries.flat().sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()).slice(0, 10)
    },
    enabled: !!summary?.tasks.length,
  })

  if (isLoading) return <p className="text-muted-foreground">Cargando...</p>
  if (!summary) return <p className="text-muted-foreground">Cliente no encontrado</p>

  const { client, tasks } = summary

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link to="/clients">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold uppercase tracking-wide">{client.name}</h2>
            {statusBadge(client.status)}
          </div>
          {client.company && <p className="text-muted-foreground">{client.company}</p>}
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Total tareas</p>
            <p className="kpi-value mt-1">{summary.total_tasks}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Tiempo estimado</p>
            <p className="kpi-value mt-1">{formatMinutes(summary.total_estimated_minutes)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Tiempo real</p>
            <p className="kpi-value mt-1">{formatMinutes(summary.total_actual_minutes)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Tiempo tracked</p>
            <p className="kpi-value mt-1">{formatMinutes(summary.total_tracked_minutes)}</p>
          </CardContent>
        </Card>
      </div>

      {/* Tasks Table */}
      <Card>
        <CardHeader>
          <CardTitle>Tareas</CardTitle>
        </CardHeader>
        <CardContent className="pt-4">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Titulo</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Est.</TableHead>
                <TableHead>Real</TableHead>
                <TableHead>Timer</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tasks.map((t) => (
                <TableRow key={t.id}>
                  <TableCell className="font-medium">{t.title}</TableCell>
                  <TableCell>{taskStatusBadge(t.status)}</TableCell>
                  <TableCell className="mono">{t.estimated_minutes ? formatMinutes(t.estimated_minutes) : "-"}</TableCell>
                  <TableCell className="mono">{t.actual_minutes ? formatMinutes(t.actual_minutes) : "-"}</TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <TimerButton taskId={t.id} />
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setTimeLogTaskId({ id: t.id, title: t.title })}
                      >
                        <Clock className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {tasks.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                    No hay tareas
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Communications */}
      <Card>
        <CardContent className="p-6">
          <CommunicationList clientId={clientId} />
        </CardContent>
      </Card>

      {/* Recent Time Entries */}
      {recentEntries.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Entradas de tiempo recientes</CardTitle>
          </CardHeader>
          <CardContent className="pt-4">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Fecha</TableHead>
                  <TableHead>Tarea</TableHead>
                  <TableHead>Duracion</TableHead>
                  <TableHead>Notas</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentEntries.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="mono">{new Date(e.date).toLocaleDateString("es-ES")}</TableCell>
                    <TableCell>{e.task_title || "-"}</TableCell>
                    <TableCell className="mono">{e.minutes ? formatMinutes(e.minutes) : "-"}</TableCell>
                    <TableCell className="max-w-[200px] truncate">{e.notes || "-"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Time Log Dialog */}
      {timeLogTaskId && (
        <TimeLogDialog
          taskId={timeLogTaskId.id}
          taskTitle={timeLogTaskId.title}
          open={!!timeLogTaskId}
          onOpenChange={(open) => !open && setTimeLogTaskId(null)}
        />
      )}
    </div>
  )
}
