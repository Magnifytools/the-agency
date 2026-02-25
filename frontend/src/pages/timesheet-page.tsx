import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { timeEntriesApi, tasksApi } from "@/lib/api"
import { useAuth } from "@/context/auth-context"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Select } from "@/components/ui/select"
import { Clock } from "lucide-react"
import { EmptyTableState } from "@/components/ui/empty-state"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

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

export default function TimesheetPage() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [weekStart, setWeekStart] = useState(() => toInputDate(getMonday(new Date())))
  const todayDate = toInputDate(new Date())

  const { data: weeklyData } = useQuery({
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

  const updateMutation = useMutation({
    mutationFn: ({ id, task_id }: { id: number; task_id: number }) =>
      timeEntriesApi.update(id, { task_id }), // Necesitamos que el endpoint sorpote esto, lo comprobaremos
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["time-entries"] })
      toast.success("Entrada asignada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al asignar tarea")),
  })

  const days = weeklyData?.days || []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold uppercase tracking-wide">Timesheet</h2>
          <p className="text-sm text-muted-foreground mt-1">Semana actual · {todaysEntries.length} registros hoy</p>
        </div>
      </div>

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
                        ✓ Asignado a "{e.task_title}"
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
          {!weeklyData ? (
            <div className="text-sm text-muted-foreground">Cargando...</div>
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
    </div>
  )
}
