import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { timeEntriesApi, tasksApi } from "@/lib/api"
import { useAuth } from "@/context/auth-context"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Select } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import { Clock, Download, ChevronDown, ChevronRight, Users, FolderKanban } from "lucide-react"
import { EmptyTableState } from "@/components/ui/empty-state"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import type { ProjectTimeReport } from "@/lib/types"

function getMonday(date: Date) {
  const d = new Date(date)
  const day = d.getDay()
  const diff = (day === 0 ? -6 : 1) - day
  d.setDate(d.getDate() + diff)
  d.setHours(0, 0, 0, 0)
  return d
}

function toInputDate(d: Date) {
  return d.toISOString().slice(0, 10)
}

function formatMinutes(minutes: number | null) {
  if (minutes === null) return "En curso..."
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return `${h > 0 ? `${h}h ` : ""}${m}m`
}

function formatElapsed(seconds: number) {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return `${h}h ${m}m`
}

function ProjectReportRow({ project }: { project: ProjectTimeReport }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <>
      <TableRow className="cursor-pointer hover:bg-muted/50" onClick={() => setExpanded(!expanded)}>
        <TableCell className="font-medium">
          <span className="inline-flex items-center gap-1">
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            {project.project_name}
          </span>
          <span className="text-muted-foreground text-xs ml-2">- {project.client_name}</span>
        </TableCell>
        <TableCell className="text-right mono">{formatMinutes(project.total_minutes)}</TableCell>
        <TableCell className="text-right">{project.entries_count}</TableCell>
        <TableCell className="text-right">{project.team_breakdown.length}</TableCell>
      </TableRow>
      {expanded && project.team_breakdown.map((t) => (
        <TableRow key={t.user_id} className="bg-muted/30">
          <TableCell className="pl-10 text-sm text-muted-foreground">{t.user_name}</TableCell>
          <TableCell className="text-right mono text-sm">{formatMinutes(t.total_minutes)}</TableCell>
          <TableCell className="text-right text-sm">{t.entries_count}</TableCell>
          <TableCell />
        </TableRow>
      ))}
    </>
  )
}

export default function TimesheetPage() {
  const { user, isAdmin } = useAuth()
  const queryClient = useQueryClient()
  const [weekStart, setWeekStart] = useState(() => toInputDate(getMonday(new Date())))
  const todayDate = toInputDate(new Date())

  const weekEnd = (() => {
    const d = new Date(weekStart)
    d.setDate(d.getDate() + 6)
    return toInputDate(d)
  })()

  const { data: weeklyData, isLoading: weekLoading, error: weekError, refetch: weekRefetch } = useQuery({
    queryKey: ["timesheet-week", weekStart],
    queryFn: () => timeEntriesApi.weekly(weekStart),
  })

  // Obtener los time entries de hoy para el usuario actual
  const { data: todaysEntries = [] } = useQuery({
    queryKey: ["time-entries", "today", user?.id],
    queryFn: () => timeEntriesApi.list({ user_id: user?.id, date_from: todayDate + "T00:00:00Z", date_to: todayDate + "T23:59:59Z" }),
    enabled: !!user?.id,
  })

  // Obtener tareas para el selector
  const { data: myTasks = [] } = useQuery({
    queryKey: ["tasks-all", "my-tasks"],
    queryFn: () => tasksApi.listAll(),
  })

  // Admin: active timers
  const { data: activeTimers = [] } = useQuery({
    queryKey: ["admin-active-timers"],
    queryFn: () => timeEntriesApi.adminTimers(),
    enabled: isAdmin,
    refetchInterval: 10_000,
  })

  // Project report
  const { data: projectReport = [], isLoading: projectLoading } = useQuery({
    queryKey: ["time-entries-by-project", weekStart, weekEnd],
    queryFn: () => timeEntriesApi.byProject({ date_from: weekStart + "T00:00:00Z", date_to: weekEnd + "T23:59:59Z" }),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, task_id }: { id: number; task_id: number }) =>
      timeEntriesApi.update(id, { task_id }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["time-entries"] })
      toast.success("Entrada asignada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al asignar tarea")),
  })

  const handleExportCsv = async () => {
    try {
      const blob = await timeEntriesApi.exportCsv({
        date_from: weekStart + "T00:00:00Z",
        date_to: weekEnd + "T23:59:59Z",
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `timesheet-${weekStart}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast.error(getErrorMessage(err, "No se pudo exportar el CSV"))
    }
  }

  const days = weeklyData?.days || []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold uppercase tracking-wide">Timesheet</h2>
          <p className="text-sm text-muted-foreground mt-1">Semana actual · {todaysEntries.length} registros hoy</p>
        </div>
        <Button variant="outline" size="sm" onClick={handleExportCsv}>
          <Download className="h-4 w-4 mr-2" />
          Exportar CSV
        </Button>
      </div>

      {/* Admin: Active Timers */}
      {isAdmin && activeTimers.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Users className="h-5 w-5" />
              Timers Activos ({activeTimers.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Usuario</TableHead>
                  <TableHead>Tarea</TableHead>
                  <TableHead>Cliente</TableHead>
                  <TableHead className="text-right">Tiempo</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activeTimers.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-medium">{t.user_name}</TableCell>
                    <TableCell>{t.task_title || "Sin tarea"}</TableCell>
                    <TableCell className="text-muted-foreground">{t.client_name || "-"}</TableCell>
                    <TableCell className="text-right mono">{formatElapsed(t.elapsed_seconds)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Mis Registros de Hoy</CardTitle>
          <p className="text-sm text-muted-foreground">Revisa tus tiempos rápidos y asígnalos a tareas para facturar.</p>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Registro</TableHead>
                <TableHead>Duración</TableHead>
                <TableHead>Tarea / Proyecto</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {todaysEntries.length === 0 && (
                <EmptyTableState colSpan={3} icon={Clock} title="Sin registros hoy" description="Usa el timer desde cualquier tarea para registrar tiempo." />
              )}
              {todaysEntries.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="font-medium">
                    {e.notes || e.task_title || "Registro sin nombre"}
                    {e.client_name && <span className="text-muted-foreground text-xs ml-2">— {e.client_name}</span>}
                  </TableCell>
                  <TableCell className="mono">{formatMinutes(e.minutes)}</TableCell>
                  <TableCell>
                    {e.task_id ? (
                      <span className="text-sm text-muted-foreground">
                        ✓ Asignado a &quot;{e.task_title}&quot;
                      </span>
                    ) : (
                      <Select
                        value=""
                        onChange={(ev) => {
                          if (ev.target.value) {
                            updateMutation.mutate({ id: e.id, task_id: Number(ev.target.value) })
                          }
                        }}
                        className="w-full max-w-xs h-8 text-xs"
                      >
                        <option value="">+ Seleccionar Tarea...</option>
                        {myTasks.map(t => (
                          <option key={t.id} value={t.id}>{t.client_name ? `[${t.client_name}] ` : ''}{t.title}</option>
                        ))}
                      </Select>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <div className="flex items-center justify-between pt-4">
        <h3 className="text-xl font-bold">Resumen Semanal</h3>
        <input
          type="date"
          value={weekStart}
          onChange={(e) => setWeekStart(e.target.value)}
          className="border border-border rounded-md px-3 py-2 text-sm bg-background"
        />
      </div>

      <Card>
        <CardContent className="pt-4">
          {weekLoading ? (
            <div className="text-sm text-muted-foreground">Cargando...</div>
          ) : weekError ? (
            <div className="text-red-500 text-sm">Error al cargar datos. <button className="underline ml-1" onClick={() => weekRefetch()}>Reintentar</button></div>
          ) : !weeklyData ? (
            <div className="text-sm text-muted-foreground">Sin datos</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Miembro</TableHead>
                  {days.map((d) => (
                    <TableHead key={d} className="text-right">
                      {new Date(d).toLocaleDateString("es-ES", { weekday: "short", day: "2-digit" })}
                    </TableHead>
                  ))}
                  <TableHead className="text-right">Total</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {weeklyData.users.map((u) => (
                  <TableRow key={u.user_id}>
                    <TableCell className="font-medium">{u.full_name}</TableCell>
                    {days.map((d) => (
                      <TableCell key={d} className="text-right mono">
                        {Math.round((u.daily_minutes[d] || 0) / 60)}h
                      </TableCell>
                    ))}
                    <TableCell className="text-right mono font-semibold">
                      {Math.round((u.total_minutes || 0) / 60)}h
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Project Report */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FolderKanban className="h-5 w-5" />
            Por Proyecto
          </CardTitle>
          <p className="text-sm text-muted-foreground">Horas agrupadas por proyecto para la semana seleccionada.</p>
        </CardHeader>
        <CardContent>
          {projectLoading ? (
            <div className="text-sm text-muted-foreground">Cargando...</div>
          ) : projectReport.length === 0 ? (
            <EmptyTableState colSpan={4} icon={FolderKanban} title="Sin datos por proyecto" description="No hay registros de tiempo vinculados a proyectos en esta semana." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Proyecto</TableHead>
                  <TableHead className="text-right">Horas</TableHead>
                  <TableHead className="text-right">Registros</TableHead>
                  <TableHead className="text-right">Personas</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {projectReport.map((p) => (
                  <ProjectReportRow key={p.project_id} project={p} />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
