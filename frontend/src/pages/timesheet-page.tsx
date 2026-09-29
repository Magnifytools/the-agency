import { useState, useEffect, useMemo, Fragment } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { timeEntriesApi, tasksApi, timerApi, clientsApi, projectsApi } from "@/lib/api"
import { invalidateTimeChange, projectKeys, taskKeys, timeKeys } from "@/lib/query-keys"
import { useAuth } from "@/context/auth-context"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Select } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import { Clock, Download, ChevronDown, ChevronRight, Users, FolderKanban, Building2, Pencil, Check, X, Play, Square, ChevronLeft, AlertTriangle, User as UserIcon, CheckSquare, CalendarDays } from "lucide-react"
import { Input } from "@/components/ui/input"
import { EmptyState, EmptyTableState } from "@/components/ui/empty-state"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import { formatCurrency } from "@/lib/format"
import type { ProjectTimeReport, ClientTimeReport, WeeklyTimesheetTask } from "@/lib/types"
import { agencyTimezoneLabel, civilDateRangeUtc, parseCivilDate } from "@/lib/dates"
import { useBusinessDate } from "@/hooks/use-business-date"
import { elapsedSeconds, formatElapsedSeconds } from "@/lib/timer"

/** Parse "YYYY-MM-DD" as local date (not UTC) to avoid timezone shift */
const parseLocalDate = parseCivilDate

function getMonday(date: Date) {
  const d = new Date(date)
  const day = d.getDay()
  const diff = (day === 0 ? -6 : 1) - day
  d.setDate(d.getDate() + diff)
  d.setHours(0, 0, 0, 0)
  return d
}

function toInputDate(d: Date) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
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

function fmtMin(m: number) {
  if (!m) return "—"
  const h = Math.floor(m / 60)
  const min = m % 60
  return h > 0 ? (min > 0 ? `${h}h ${min}m` : `${h}h`) : `${min}m`
}

function RecoveryNotice({ onRetry, label }: { onRetry: () => void; label: string }) {
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-2 text-sm text-destructive">
      <span>No se pudo cargar {label}.</span>
      <Button type="button" variant="outline" size="sm" onClick={onRetry}>Reintentar</Button>
    </div>
  )
}

const TABS = [
  { key: "resumen", label: "Resumen", icon: Clock },
  { key: "trabajador", label: "Por Trabajador", icon: UserIcon },
  { key: "tarea", label: "Por Tarea", icon: CheckSquare },
  { key: "cliente", label: "Por Cliente", icon: Building2 },
  { key: "proyecto", label: "Por Proyecto", icon: FolderKanban },
] as const

type TabKey = typeof TABS[number]["key"]

type PeriodType = "esta-semana" | "semana-pasada" | "este-mes" | "mes-pasado" | "este-año" | "personalizado"

const PERIOD_OPTIONS: { value: PeriodType; label: string }[] = [
  { value: "esta-semana", label: "Esta semana" },
  { value: "semana-pasada", label: "Semana pasada" },
  { value: "este-mes", label: "Este mes" },
  { value: "mes-pasado", label: "Mes pasado" },
  { value: "este-año", label: "Este año" },
  { value: "personalizado", label: "Personalizado" },
]

function computePeriodDates(period: PeriodType, todayValue: string): { from: string; to: string } {
  const today = parseCivilDate(todayValue)
  switch (period) {
    case "esta-semana": {
      const mon = getMonday(today)
      const sun = new Date(mon)
      sun.setDate(sun.getDate() + 6)
      return { from: toInputDate(mon), to: toInputDate(sun) }
    }
    case "semana-pasada": {
      const mon = getMonday(today)
      mon.setDate(mon.getDate() - 7)
      const sun = new Date(mon)
      sun.setDate(sun.getDate() + 6)
      return { from: toInputDate(mon), to: toInputDate(sun) }
    }
    case "este-mes": {
      const first = new Date(today.getFullYear(), today.getMonth(), 1)
      const last = new Date(today.getFullYear(), today.getMonth() + 1, 0)
      return { from: toInputDate(first), to: toInputDate(last) }
    }
    case "mes-pasado": {
      const first = new Date(today.getFullYear(), today.getMonth() - 1, 1)
      const last = new Date(today.getFullYear(), today.getMonth(), 0)
      return { from: toInputDate(first), to: toInputDate(last) }
    }
    case "este-año": {
      const first = new Date(today.getFullYear(), 0, 1)
      return { from: toInputDate(first), to: toInputDate(today) }
    }
    default:
      return { from: toInputDate(getMonday(today)), to: toInputDate(today) }
  }
}

// ─── Subcomponents ───────────────────────────────────────────

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


function ClientReportRow({ client }: { client: ClientTimeReport }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <>
      <TableRow className="cursor-pointer hover:bg-muted/50" onClick={() => setExpanded(!expanded)}>
        <TableCell className="font-medium">
          <span className="inline-flex items-center gap-1">
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            {client.client_name}
          </span>
        </TableCell>
        <TableCell className="text-right mono">{formatMinutes(client.total_minutes)}</TableCell>
        <TableCell className="text-right mono">{formatCurrency(client.cost_eur)}</TableCell>
        <TableCell className="text-right">{client.entries_count}</TableCell>
        <TableCell className="text-right">{client.team_breakdown.length}</TableCell>
      </TableRow>
      {expanded && client.team_breakdown.map((t) => (
        <TableRow key={t.user_id} className="bg-muted/30">
          <TableCell className="pl-10 text-sm text-muted-foreground">{t.user_name}</TableCell>
          <TableCell className="text-right mono text-sm">{formatMinutes(t.total_minutes)}</TableCell>
          <TableCell className="text-right mono text-sm">{formatCurrency(t.cost_eur)}</TableCell>
          <TableCell />
          <TableCell />
        </TableRow>
      ))}
    </>
  )
}

function TimerWidget({ tasks, tasksError, canReadTasks, canReadClients, canReadProjects, onRetryTasks, onTimerChange }: { tasks: { id: number; title: string; status?: string; client_id?: number | null; client_name?: string | null; project_id?: number | null; project_name?: string | null; scheduled_date?: string | null; due_date?: string | null }[]; tasksError: boolean; canReadTasks: boolean; canReadClients: boolean; canReadProjects: boolean; onRetryTasks: () => void; onTimerChange: () => void }) {
  const queryClient = useQueryClient()
  const [filterClient, setFilterClient] = useState("")
  const [filterProject, setFilterProject] = useState("")
  const [selectedTask, setSelectedTask] = useState("")
  const [elapsed, setElapsed] = useState("")

  const activeTimerQuery = useQuery({
    queryKey: ["active-timer"],
    queryFn: () => timerApi.active(),
    refetchInterval: 10_000,
  })
  const activeTimer = activeTimerQuery.isError ? undefined : activeTimerQuery.data
  const timerUnknown = (activeTimerQuery.isPending || activeTimerQuery.isError) && !activeTimer

  // Source of truth for the Cliente dropdown: ALL active clients (not just those
  // with tasks assigned to the current user). Fixes the bug where only Taxfix +
  // Kinetic Digital appeared.
  const clientsQuery = useQuery({
    queryKey: ["clients-active"],
    queryFn: () => clientsApi.listAll("active"),
    staleTime: 60_000,
    enabled: canReadClients,
  })
  const allActiveClients = !canReadClients || clientsQuery.isError ? [] : (clientsQuery.data ?? [])

  // Active projects for the selected client (or all if none selected)
  const filterClientNum = filterClient ? parseInt(filterClient, 10) : undefined
  const projectsQuery = useQuery({
    queryKey: projectKeys.list(["active", "client", filterClientNum]),
    queryFn: () => projectsApi.listAll({ client_id: filterClientNum, status: "active" }),
    enabled: !!filterClientNum && canReadProjects,
    staleTime: 30_000,
  })
  const allActiveProjects = !canReadProjects || projectsQuery.isError ? [] : (projectsQuery.data ?? [])

  // eslint-disable-next-line react-hooks/set-state-in-effect -- Timer tick requires setInterval in effect
  useEffect(() => {
    if (!activeTimer?.started_at) { setElapsed(""); return }
    const tick = () => {
      setElapsed(formatElapsedSeconds(elapsedSeconds(
        activeTimer.started_at,
        activeTimer.accumulated_seconds || 0,
        activeTimer.is_paused || false,
      )))
    }
    tick()
    if (activeTimer.is_paused) return
    const iv = setInterval(tick, 1000)
    return () => clearInterval(iv)
  }, [activeTimer?.started_at, activeTimer?.accumulated_seconds, activeTimer?.is_paused])

  // Cliente: SIEMPRE todos los activos (no derivado de tareas del usuario).
  const clients: [number, string][] = allActiveClients.map((c) => [c.id, c.name])
  // Proyecto: si hay cliente seleccionado, todos sus proyectos activos; si no,
  // los derivados de tareas (legacy fallback para no romper el flujo sin cliente).
  const projects: [number, string][] = filterClient
    ? allActiveProjects.map((p) => [p.id, p.name])
    : Array.from(new Map(tasks.filter((t) => t.project_id).map((t) => [t.project_id, t.project_name])).entries()) as [number, string][]
  const filteredTasks = tasks.filter((t) => {
    if (t.status === "completed") return false
    if (filterClient && String(t.client_id) !== filterClient) return false
    if (filterProject && String(t.project_id) !== filterProject) return false
    return true
  })

  const handleStart = async () => {
    if (!selectedTask) {
      toast.error("Selecciona una tarea para iniciar el timer")
      return
    }
    try {
      await timerApi.start({ task_id: Number(selectedTask) })
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
      onTimerChange()
      toast.success("Timer iniciado")
    } catch (err) {
      toast.error(getErrorMessage(err, "Error al iniciar timer"))
    }
  }

  const handleStop = async () => {
    try {
      if (!activeTimer) return
      await timerApi.stop(activeTimer.id)
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
      onTimerChange()
      toast.success("Timer detenido")
    } catch (err) {
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
      toast.error(getErrorMessage(err, "Error al detener timer"))
    }
  }

  return (
    <Card className={activeTimer ? "border-green-500/30 bg-green-500/5" : ""}>
      <CardContent className="py-3">
        {timerUnknown && activeTimerQuery.isPending ? (
          <p role="status" className="text-sm text-muted-foreground">Comprobando el cronómetro…</p>
        ) : timerUnknown ? (
          <RecoveryNotice label="el estado del cronómetro" onRetry={() => void activeTimerQuery.refetch()} />
        ) : activeTimer ? (
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 flex-1">
              <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
              <span className="font-mono text-lg font-semibold">{elapsed}</span>
              <span className="text-sm text-muted-foreground truncate">
                {activeTimer.task_title || "Sin tarea"}
                {activeTimer.client_name && <span className="ml-1 text-xs">({activeTimer.client_name})</span>}
              </span>
            </div>
            <Button size="sm" variant="destructive" onClick={handleStop} className="gap-1.5">
              <Square className="h-3.5 w-3.5" />
              Parar
            </Button>
          </div>
        ) : (
          <div className="space-y-2">
            {(tasksError || (canReadClients && clientsQuery.isError) || (canReadProjects && projectsQuery.isError)) && (
              <RecoveryNotice
                label="los selectores del cronómetro"
                onRetry={() => {
                  if (canReadTasks) void onRetryTasks()
                  if (canReadClients) void clientsQuery.refetch()
                  if (canReadProjects && filterClientNum) void projectsQuery.refetch()
                }}
              />
            )}
          <div className="flex items-center gap-2 flex-wrap">
            <Clock className="h-4 w-4 text-muted-foreground shrink-0" />
            <Select aria-label="Cliente del cronómetro" value={filterClient} onChange={(e) => { setFilterClient(e.target.value); setFilterProject(""); setSelectedTask("") }} className="h-8 text-xs w-36" disabled={!canReadClients || (clientsQuery.isError && allActiveClients.length === 0)}>
              <option value="">Cliente...</option>
              {clients.map(([id, name]) => <option key={id} value={String(id)}>{name}</option>)}
            </Select>
            <Select aria-label="Proyecto del cronómetro" value={filterProject} onChange={(e) => { setFilterProject(e.target.value); setSelectedTask("") }} className="h-8 text-xs w-36" disabled={!!filterClient && (!canReadProjects || (projectsQuery.isError && allActiveProjects.length === 0))}>
              <option value="">Proyecto...</option>
              {projects.map(([id, name]) => <option key={id} value={String(id)}>{name}</option>)}
            </Select>
            <Select aria-label="Tarea del cronómetro" value={selectedTask} onChange={(e) => setSelectedTask(e.target.value)} className="h-8 text-xs flex-1 min-w-[180px]" disabled={!canReadTasks || (tasksError && tasks.length === 0)}>
              <option value="">Selecciona una tarea...</option>
              {filteredTasks.slice(0, 50).map((t) => (
                <option key={t.id} value={String(t.id)}>
                  {t.title.length > 60 ? t.title.slice(0, 60) + "…" : t.title}
                </option>
              ))}
            </Select>
            <Button size="sm" onClick={handleStart} disabled={!canReadTasks || !selectedTask || (tasksError && tasks.length === 0)} className="gap-1.5 shrink-0">
              <Play className="h-3.5 w-3.5" />
              Iniciar
            </Button>
          </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}


// ─── Task Tab ────────────────────────────────────────────────

interface TaskTabProps {
  weeklyData: WorkerTabProps["weeklyData"]
  weekLoading: boolean
}

function TaskTab({ weeklyData, weekLoading }: TaskTabProps) {
  const taskMap = useMemo(() => {
    const map = new Map<number | string, {
      task_id: number | null
      task_title: string
      client_name: string | null
      users: string[]
      daily_minutes: Record<string, number>
      total_minutes: number
    }>()
    for (const u of weeklyData?.users || []) {
      for (const t of u.tasks) {
        const key = t.task_id ?? `noTask-${u.user_id}`
        const existing = map.get(key)
        if (existing) {
          if (!existing.users.includes(u.full_name)) existing.users.push(u.full_name)
          existing.total_minutes += t.total_minutes
          for (const [day, mins] of Object.entries(t.daily_minutes)) {
            existing.daily_minutes[day] = (existing.daily_minutes[day] || 0) + mins
          }
        } else {
          map.set(key, {
            task_id: t.task_id,
            task_title: t.task_title || "Sin tarea",
            client_name: t.client_name || null,
            users: [u.full_name],
            daily_minutes: { ...t.daily_minutes },
            total_minutes: t.total_minutes,
          })
        }
      }
    }
    return [...map.values()].sort((a, b) => b.total_minutes - a.total_minutes)
  }, [weeklyData])

  if (weekLoading) return <div className="text-sm text-muted-foreground p-4">Cargando...</div>
  if (!taskMap.length) return <EmptyState icon={CheckSquare} title="Sin datos por tarea" description="Registra tiempo en tareas para ver el desglose." />

  const days = weeklyData?.days || []

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CheckSquare className="h-5 w-5" />
          Por Tarea
        </CardTitle>
        <p className="text-sm text-muted-foreground">Horas agrupadas por tarea para la semana seleccionada.</p>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Tarea</TableHead>
                <TableHead>Cliente</TableHead>
                {days.map((d) => (
                  <TableHead key={d} className="text-right w-16 text-xs">
                    {parseLocalDate(d).toLocaleDateString("es-ES", { weekday: "short", day: "numeric" })}
                  </TableHead>
                ))}
                <TableHead className="text-right font-bold">Total</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {taskMap.map((t, i) => (
                <TableRow key={i}>
                  <TableCell className="font-medium max-w-[200px] truncate" title={t.task_title}>
                    {t.task_title}
                    {t.users.length > 1 && (
                      <span className="text-[10px] text-muted-foreground ml-1">({t.users.length} personas)</span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-sm">{t.client_name || "—"}</TableCell>
                  {days.map((d) => (
                    <TableCell key={d} className="text-right mono text-sm">
                      {t.daily_minutes[d] ? fmtMin(t.daily_minutes[d]) : "—"}
                    </TableCell>
                  ))}
                  <TableCell className="text-right font-bold mono">{fmtMin(t.total_minutes)}</TableCell>
                </TableRow>
              ))}
              <TableRow className="font-bold border-t-2">
                <TableCell>Total</TableCell>
                <TableCell />
                {days.map((d) => {
                  const total = taskMap.reduce((sum, t) => sum + (t.daily_minutes[d] || 0), 0)
                  return <TableCell key={d} className="text-right mono">{fmtMin(total)}</TableCell>
                })}
                <TableCell className="text-right mono">{fmtMin(taskMap.reduce((sum, t) => sum + t.total_minutes, 0))}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}

// ─── Worker Tab ──────────────────────────────────────────────

interface WorkerTabProps {
  weeklyData: { days: string[]; users: { user_id: number; full_name: string; daily_minutes: Record<string, number>; total_minutes: number; tasks: WeeklyTimesheetTask[] }[] } | undefined
  weekLoading: boolean
  assignedTasks: { id: number; title: string; client_name?: string | null; assigned_to?: number | null; status?: string }[]
  onEditEntry?: (entry: { taskId: number | null; taskTitle: string; userId: number; userName: string }) => void
}

function WorkerTab({ weeklyData, weekLoading, assignedTasks }: WorkerTabProps) {
  const [expandedWorkers, setExpandedWorkers] = useState<Set<number>>(new Set())

  // Build a map of task IDs that have time entries this week per user
  const userTasksWithTime = useMemo(() => {
    const map = new Map<number, Set<number>>()
    for (const u of weeklyData?.users || []) {
      const taskIds = new Set<number>()
      for (const t of u.tasks) {
        if (t.task_id && t.total_minutes > 0) taskIds.add(t.task_id)
      }
      map.set(u.user_id, taskIds)
    }
    return map
  }, [weeklyData])

  // Find assigned tasks without time entries per user
  const tasksWithoutTime = useMemo(() => {
    const map = new Map<number, typeof assignedTasks>()
    for (const u of weeklyData?.users || []) {
      const withTime = userTasksWithTime.get(u.user_id) || new Set()
      const missing = assignedTasks.filter(
        (t) => t.assigned_to === u.user_id && !withTime.has(t.id) && t.status !== "done" && t.status !== "cancelled"
      )
      if (missing.length > 0) map.set(u.user_id, missing)
    }
    return map
  }, [weeklyData, assignedTasks, userTasksWithTime])

  if (weekLoading) return <div className="text-sm text-muted-foreground p-4">Cargando...</div>
  if (!weeklyData?.users.length) return <div className="text-sm text-muted-foreground p-4">Sin datos para esta semana.</div>

  const toggleWorker = (uid: number) => {
    setExpandedWorkers((prev) => {
      const next = new Set(prev)
      if (next.has(uid)) next.delete(uid)
      else next.add(uid)
      return next
    })
  }

  const days = weeklyData.days

  return (
    <div className="space-y-4">
      {weeklyData.users.map((u) => {
        const isExpanded = expandedWorkers.has(u.user_id)
        const noTimeTasks = tasksWithoutTime.get(u.user_id) || []
        const avgDaily = u.total_minutes / Math.max(days.filter((d) => (u.daily_minutes[d] || 0) > 0).length, 1)

        return (
          <Card key={u.user_id} className="overflow-hidden">
            <div
              className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-muted/30 transition-colors"
              onClick={() => toggleWorker(u.user_id)}
            >
              <div className="flex items-center gap-3">
                <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center">
                  <UserIcon className="h-4 w-4 text-primary" />
                </div>
                <div>
                  <span className="font-semibold">{u.full_name}</span>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span>{fmtMin(u.total_minutes)} total</span>
                    <span>{u.tasks.length} tareas</span>
                    <span>~{fmtMin(Math.round(avgDaily))}/dia</span>
                    {noTimeTasks.length > 0 && (
                      <span className="text-amber-500 flex items-center gap-1">
                        <AlertTriangle className="h-3 w-3" />
                        {noTimeTasks.length} sin tiempo
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-4">
                {/* Mini sparkline of daily hours */}
                <div className="hidden sm:flex items-end gap-0.5 h-6">
                  {days.slice(0, 5).map((d) => {
                    const mins = u.daily_minutes[d] || 0
                    const maxMins = Math.max(...days.map((dd) => u.daily_minutes[dd] || 0), 1)
                    const pct = Math.max((mins / maxMins) * 100, 4)
                    return (
                      <div
                        key={d}
                        className={`w-3 rounded-t transition-all ${mins > 0 ? "bg-primary/60" : "bg-muted"}`}
                        style={{ height: `${pct}%` }}
                        title={`${new Date(d + "T12:00:00").toLocaleDateString("es-ES", { weekday: "short" })}: ${fmtMin(mins)}`}
                      />
                    )
                  })}
                </div>
                <span className="font-mono font-semibold text-sm">{fmtMin(u.total_minutes)}</span>
                {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              </div>
            </div>

            {isExpanded && (
              <CardContent className="pt-0 pb-4">
                {/* Daily breakdown header */}
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[40%]">Tarea</TableHead>
                      {days.map((d) => (
                        <TableHead key={d} className="text-right text-xs w-[8%]">
                          {new Date(d + "T12:00:00").toLocaleDateString("es-ES", { weekday: "short", day: "2-digit" }).toUpperCase()}
                        </TableHead>
                      ))}
                      <TableHead className="text-right">Total</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {u.tasks.map((t: WeeklyTimesheetTask) => (
                      <TableRow key={t.task_id ?? "none"}>
                        <TableCell className="text-sm">
                          <span>{t.task_title}</span>
                          {t.client_name && <span className="text-xs text-muted-foreground ml-1.5">— {t.client_name}</span>}
                        </TableCell>
                        {days.map((d) => (
                          <TableCell key={d} className="text-right mono text-sm text-muted-foreground">
                            {fmtMin(t.daily_minutes[d] || 0)}
                          </TableCell>
                        ))}
                        <TableCell className="text-right mono text-sm font-medium">{fmtMin(t.total_minutes)}</TableCell>
                      </TableRow>
                    ))}
                    {u.tasks.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={days.length + 2} className="text-center text-sm text-muted-foreground py-4">
                          Sin registros de tiempo esta semana
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>

                {/* Tasks without time entries */}
                {noTimeTasks.length > 0 && (
                  <div className="mt-4 border border-amber-500/20 rounded-lg bg-amber-500/5 p-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-amber-600 mb-2">
                      <AlertTriangle className="h-4 w-4" />
                      Tareas asignadas sin tiempo registrado ({noTimeTasks.length})
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-1">
                      {noTimeTasks.slice(0, 10).map((t) => (
                        <div key={t.id} className="text-xs text-muted-foreground flex items-center gap-1.5 py-0.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
                          <span className="truncate">{t.title}</span>
                          {t.client_name && <span className="text-muted-foreground/50 shrink-0">({t.client_name})</span>}
                        </div>
                      ))}
                      {noTimeTasks.length > 10 && (
                        <div className="text-xs text-muted-foreground/60">+{noTimeTasks.length - 10} mas...</div>
                      )}
                    </div>
                  </div>
                )}
              </CardContent>
            )}
          </Card>
        )
      })}
    </div>
  )
}


// ─── Main Page ───────────────────────────────────────────────

export default function TimesheetPage() {
  const { user, isAdmin, hasPermission } = useAuth()
  const canWriteTime = hasPermission("timesheet") && hasPermission("timesheet", true)
  const canReadTasks = hasPermission("tasks")
  const canReadClients = hasPermission("clients")
  const canReadProjects = hasPermission("projects")
  const queryClient = useQueryClient()
  const businessToday = useBusinessDate()
  const [weekStart, setWeekStart] = useState(() => toInputDate(getMonday(parseCivilDate(businessToday))))
  const [activeTab, setActiveTab] = useState<TabKey>("resumen")
  const [period, setPeriod] = useState<PeriodType>("esta-semana")
  const [customFrom, setCustomFrom] = useState("")
  const [customTo, setCustomTo] = useState("")
  const todayDate = businessToday

  const weekEnd = (() => {
    const d = parseLocalDate(weekStart)
    d.setDate(d.getDate() + 6)
    return toInputDate(d)
  })()

  // Compute effective date range based on period
  const isWeekPeriod = period === "esta-semana" || period === "semana-pasada"
  const { dateFrom, dateTo } = useMemo(() => {
    if (isWeekPeriod) {
      return { dateFrom: weekStart, dateTo: weekEnd }
    }
    if (period === "personalizado") {
      return { dateFrom: customFrom || weekStart, dateTo: customTo || weekEnd }
    }
    const { from, to } = computePeriodDates(period, businessToday)
    return { dateFrom: from, dateTo: to }
  }, [period, weekStart, weekEnd, customFrom, customTo, isWeekPeriod, businessToday])

  // When period changes (non-custom, non-week), also sync weekStart for the weekly query
  useEffect(() => {
    if (period === "esta-semana") {
      setWeekStart(toInputDate(getMonday(parseCivilDate(businessToday))))
    } else if (period === "semana-pasada") {
      const d = getMonday(parseCivilDate(businessToday))
      d.setDate(d.getDate() - 7)
      setWeekStart(toInputDate(d))
    }
    // For non-week periods, switch away from resumen if needed
    if (!isWeekPeriod && activeTab === "resumen") {
      setActiveTab("trabajador")
    }
  }, [period, businessToday]) // eslint-disable-line react-hooks/exhaustive-deps

  const { data: weeklyData, isLoading: weekLoading, error: weekError, refetch: weekRefetch } = useQuery({
    queryKey: timeKeys.week(weekStart),
    queryFn: () => timeEntriesApi.weekly(weekStart),
  })

  const todaysEntriesQuery = useQuery({
    queryKey: timeKeys.today(user?.id, todayDate),
    queryFn: () => {
      const range = civilDateRangeUtc(todayDate, todayDate)
      return timeEntriesApi.list({ user_id: user?.id, date_from: range.start, date_to: range.endInclusive })
    },
    enabled: !!user?.id,
  })
  const todaysEntries = todaysEntriesQuery.isError ? [] : (todaysEntriesQuery.data ?? [])

  const myTasksQuery = useQuery({
    queryKey: taskKeys.assigned("timesheet", user?.id),
    queryFn: () => tasksApi.listAll({ assigned_to: user!.id }),
    enabled: !!user?.id && canWriteTime && canReadTasks,
  })
  const myTasks = !canReadTasks || !canWriteTime || myTasksQuery.isError ? [] : (myTasksQuery.data ?? [])

  const activeTimersQuery = useQuery({
    queryKey: ["admin-active-timers"],
    queryFn: () => timeEntriesApi.adminTimers(),
    enabled: isAdmin,
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
  })
  const activeTimers = activeTimersQuery.isError ? [] : (activeTimersQuery.data ?? [])

  const projectReportQuery = useQuery({
    queryKey: [...timeKeys.reports(), "project", dateFrom, dateTo],
    queryFn: () => {
      const range = civilDateRangeUtc(dateFrom, dateTo)
      return timeEntriesApi.byProject({ date_from: range.start, date_to: range.endInclusive })
    },
    enabled: activeTab === "proyecto",
  })
  const projectReport = projectReportQuery.isError ? [] : (projectReportQuery.data ?? [])

  const clientReportQuery = useQuery({
    queryKey: [...timeKeys.reports(), "client", dateFrom, dateTo],
    queryFn: () => {
      const range = civilDateRangeUtc(dateFrom, dateTo)
      return timeEntriesApi.byClient({ date_from: range.start, date_to: range.endInclusive })
    },
    enabled: activeTab === "cliente",
  })
  const clientReport = clientReportQuery.isError ? [] : (clientReportQuery.data ?? [])

  const [editingId, setEditingId] = useState<number | null>(null)
  const [editHours, setEditHours] = useState(0)
  const [editMins, setEditMins] = useState(0)
  const [editNotes, setEditNotes] = useState("")

  const invalidateTimeEntries = () => invalidateTimeChange(queryClient)

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { task_id?: number; minutes?: number; notes?: string } }) =>
      timeEntriesApi.update(id, data),
    onSuccess: () => {
      invalidateTimeEntries()
      setEditingId(null)
      toast.success("Entrada actualizada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar")),
  })

  const startEditEntry = (e: { id: number; minutes: number | null; notes: string | null }) => {
    const m = e.minutes || 0
    setEditingId(e.id)
    setEditHours(Math.floor(m / 60))
    setEditMins(m % 60)
    setEditNotes(e.notes || "")
  }

  const saveEditEntry = () => {
    if (editingId === null) return
    const totalMinutes = editHours * 60 + editMins
    if (totalMinutes <= 0) {
      toast.error("Introduce al menos 1 minuto")
      return
    }
    updateMutation.mutate({
      id: editingId,
      data: { minutes: totalMinutes, notes: editNotes || undefined },
    })
  }

  const handleExportCsv = async () => {
    try {
      const blob = await timeEntriesApi.exportCsv({
        date_from: dateFrom + "T00:00:00Z",
        date_to: dateTo + "T23:59:59Z",
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `timesheet-${dateFrom}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast.error(getErrorMessage(err, "No se pudo exportar el CSV"))
    }
  }

  const days = weeklyData?.days || []
  const [expandedUsers, setExpandedUsers] = useState<Set<number>>(new Set())

  const toggleUser = (uid: number) => {
    setExpandedUsers((prev) => {
      const next = new Set(prev)
      if (next.has(uid)) next.delete(uid)
      else next.add(uid)
      return next
    })
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold uppercase tracking-wide">Horas</h2>
          <p className="text-sm text-muted-foreground mt-1">{PERIOD_OPTIONS.find(o => o.value === period)?.label} · {todaysEntriesQuery.isPending ? "cargando registros…" : todaysEntriesQuery.isError ? "registros de hoy no disponibles" : `${todaysEntries.length} registros hoy`} · {agencyTimezoneLabel()}</p>
        </div>
        <Button variant="outline" size="sm" onClick={handleExportCsv}>
          <Download className="h-4 w-4 mr-2" />
          Exportar CSV
        </Button>
      </div>

      {/* Quick Timer */}
      {canWriteTime && <TimerWidget
        tasks={myTasks}
        tasksError={myTasksQuery.isError}
        canReadTasks={canReadTasks}
        canReadClients={canReadClients}
        canReadProjects={canReadProjects}
        onRetryTasks={() => void myTasksQuery.refetch()}
        onTimerChange={() => {
          invalidateTimeEntries()
          queryClient.invalidateQueries({ queryKey: ["admin-active-timers"] })
        }}
      />}

      {/* Admin: Active Timers */}
      {isAdmin && activeTimersQuery.isError && (
        <Card><CardContent className="pt-6"><RecoveryNotice label="los timers activos del equipo" onRetry={() => void activeTimersQuery.refetch()} /></CardContent></Card>
      )}
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

      {/* Today's entries */}
      <Card>
        <CardHeader>
          <CardTitle>Mis registros de hoy</CardTitle>
          <p className="text-sm text-muted-foreground">Revisa las horas de hoy y asígnalas a tareas cuando corresponda.</p>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Registro</TableHead>
                <TableHead>Duración</TableHead>
                <TableHead>Tarea / Proyecto</TableHead>
                <TableHead className="w-16"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {todaysEntriesQuery.isPending && (
                <TableRow><TableCell colSpan={4}><p role="status" className="py-4 text-center text-sm text-muted-foreground">Cargando registros…</p></TableCell></TableRow>
              )}
              {todaysEntriesQuery.isError && (
                <TableRow><TableCell colSpan={4}><RecoveryNotice label="los registros de hoy" onRetry={() => void todaysEntriesQuery.refetch()} /></TableCell></TableRow>
              )}
              {!todaysEntriesQuery.isPending && !todaysEntriesQuery.isError && todaysEntries.length === 0 && (
                <EmptyTableState colSpan={4} icon={Clock} title="Sin registros hoy" description="Usa el timer desde cualquier tarea para registrar tiempo." />
              )}
              {todaysEntries.map((e) => (
                <TableRow key={e.id}>
                  {editingId === e.id ? (
                    <>
                      <TableCell>
                        <Input
                          value={editNotes}
                          onChange={(ev) => setEditNotes(ev.target.value)}
                          className="h-7 text-xs"
                          placeholder="Notas..."
                        />
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <Input type="number" min="0" value={editHours} onChange={(ev) => setEditHours(Number(ev.target.value))} className="w-14 h-7 text-xs" />
                          <span className="text-xs text-muted-foreground">h</span>
                          <Input type="number" min="0" max="59" value={editMins} onChange={(ev) => setEditMins(Number(ev.target.value))} className="w-14 h-7 text-xs" />
                          <span className="text-xs text-muted-foreground">m</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        {e.task_id ? (
                          <span className="text-sm text-muted-foreground">✓ {e.task_title}</span>
                        ) : (
                          <Select
                            value=""
                            onChange={(ev) => {
                              if (ev.target.value) updateMutation.mutate({ id: e.id, data: { task_id: Number(ev.target.value) } })
                            }}
                            className="w-full max-w-xs h-8 text-xs"
                            disabled={!canWriteTime || !canReadTasks || myTasksQuery.isError}
                          >
                            <option value="">+ Seleccionar Tarea...</option>
                            {myTasks.map(t => (
                              <option key={t.id} value={t.id}>{t.client_name ? `[${t.client_name}] ` : ''}{t.title}</option>
                            ))}
                          </Select>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={saveEditEntry} disabled={updateMutation.isPending}>
                            <Check className="h-3.5 w-3.5 text-green-600" />
                          </Button>
                          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setEditingId(null)}>
                            <X className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </>
                  ) : (
                    <>
                      <TableCell className="font-medium">
                        {e.notes || e.task_title || "Registro sin nombre"}
                        {e.client_name && <span className="text-muted-foreground text-xs ml-2">— {e.client_name}</span>}
                      </TableCell>
                      <TableCell className="mono">{formatMinutes(e.minutes)}</TableCell>
                      <TableCell>
                        {e.task_id ? (
                          <span className="text-sm text-muted-foreground">✓ Asignado a &quot;{e.task_title}&quot;</span>
                        ) : (
                          <Select
                            value=""
                            onChange={(ev) => {
                              if (ev.target.value) updateMutation.mutate({ id: e.id, data: { task_id: Number(ev.target.value) } })
                            }}
                            className="w-full max-w-xs h-8 text-xs"
                            disabled={!canWriteTime || !canReadTasks || myTasksQuery.isError}
                          >
                            <option value="">+ Seleccionar Tarea...</option>
                            {myTasks.map(t => (
                              <option key={t.id} value={t.id}>{t.client_name ? `[${t.client_name}] ` : ''}{t.title}</option>
                            ))}
                          </Select>
                        )}
                      </TableCell>
                      <TableCell>
                          {canWriteTime && <Button variant="ghost" size="icon" aria-label="Editar registro" className="h-7 w-7" onClick={() => startEditEntry(e)}>
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>}
                      </TableCell>
                    </>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Period selector + Week navigation + Tabs */}
      <div className="flex flex-col gap-3 pt-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex items-center gap-1.5">
              <CalendarDays className="h-4 w-4 text-muted-foreground" />
              <Select
                aria-label="Período de horas"
                value={period}
                onChange={(e) => setPeriod(e.target.value as PeriodType)}
                className="h-9 text-sm w-auto"
              >
                {PERIOD_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </Select>
            </div>
            {isWeekPeriod && (
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="icon" aria-label="Semana anterior" className="h-8 w-8" onClick={() => {
                  const d = parseLocalDate(weekStart)
                  d.setDate(d.getDate() - 7)
                  setWeekStart(toInputDate(getMonday(d)))
                  setPeriod(period) // keep current period type
                }}>
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <input
                  aria-label="Inicio de la semana"
                  type="date"
                  value={weekStart}
                  onChange={(e) => {
                    setWeekStart(toInputDate(getMonday(parseLocalDate(e.target.value))))
                    setPeriod("esta-semana")
                  }}
                  className="border border-border rounded-md px-3 py-2 text-sm bg-background"
                />
                <Button variant="ghost" size="icon" aria-label="Semana siguiente" className="h-8 w-8" onClick={() => {
                  const d = parseLocalDate(weekStart)
                  d.setDate(d.getDate() + 7)
                  setWeekStart(toInputDate(getMonday(d)))
                  setPeriod(period)
                }}>
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            )}
            {period === "personalizado" && (
              <div className="flex items-center gap-2">
                <input
                  aria-label="Desde"
                  type="date"
                  value={customFrom}
                  onChange={(e) => setCustomFrom(e.target.value)}
                  className="border border-border rounded-md px-3 py-2 text-sm bg-background"
                  placeholder="Desde"
                />
                <span className="text-muted-foreground text-sm">–</span>
                <input
                  aria-label="Hasta"
                  type="date"
                  value={customTo}
                  onChange={(e) => setCustomTo(e.target.value)}
                  className="border border-border rounded-md px-3 py-2 text-sm bg-background"
                  placeholder="Hasta"
                />
              </div>
            )}
            {!isWeekPeriod && period !== "personalizado" && (
              <span className="text-xs text-muted-foreground">{dateFrom} → {dateTo}</span>
            )}
          </div>
          <div className="flex items-center gap-1 bg-muted p-1 rounded-lg overflow-x-auto">
            {TABS.filter(({ key }) => isWeekPeriod || key !== "resumen").map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors whitespace-nowrap ${
                  activeTab === key
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Tab Content */}
      {activeTab === "resumen" && (
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
                      <TableHead key={d} className="text-right text-xs">
                        {new Date(d + "T12:00:00").toLocaleDateString("es-ES", { weekday: "short", day: "2-digit" }).toUpperCase()}
                      </TableHead>
                    ))}
                    <TableHead className="text-right">Total</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {weeklyData.users.map((u) => {
                    const isExpanded = expandedUsers.has(u.user_id)
                    const hasTasks = u.tasks && u.tasks.length > 0
                    return (
                      <Fragment key={u.user_id}>{/* User summary row */}
                        <TableRow
                          className={hasTasks ? "cursor-pointer hover:bg-muted/50" : ""}
                          onClick={() => hasTasks && toggleUser(u.user_id)}
                        >
                          <TableCell className="font-medium">
                            <span className="inline-flex items-center gap-1">
                              {hasTasks && (isExpanded ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />)}
                              {u.full_name}
                              {hasTasks && <span className="text-xs text-muted-foreground ml-1">({u.tasks.length})</span>}
                            </span>
                          </TableCell>
                          {days.map((d) => (
                            <TableCell key={d} className="text-right mono">{fmtMin(u.daily_minutes[d] || 0)}</TableCell>
                          ))}
                          <TableCell className="text-right mono font-semibold">{fmtMin(u.total_minutes || 0)}</TableCell>
                        </TableRow>
                        {/* Expanded task rows */}
                        {isExpanded && u.tasks.map((t: WeeklyTimesheetTask) => (
                          <TableRow key={`${u.user_id}-${t.task_id ?? "none"}`} className="bg-muted/20">
                            <TableCell className="pl-8 text-sm">
                              <span className="text-muted-foreground">{t.task_title}</span>
                              {t.client_name && <span className="text-xs text-muted-foreground/60 ml-1.5">— {t.client_name}</span>}
                            </TableCell>
                            {days.map((d) => (
                              <TableCell key={d} className="text-right mono text-sm text-muted-foreground">{fmtMin(t.daily_minutes[d] || 0)}</TableCell>
                            ))}
                            <TableCell className="text-right mono text-sm">{fmtMin(t.total_minutes)}</TableCell>
                          </TableRow>
                        ))}
                      </Fragment>
                    )
                  })}
                  {weeklyData.users.length > 1 && (
                    <TableRow className="bg-muted/50 font-semibold">
                      <TableCell>Total equipo</TableCell>
                      {days.map((d) => {
                        const total = weeklyData.users.reduce((sum, u) => sum + (u.daily_minutes[d] || 0), 0)
                        return <TableCell key={d} className="text-right mono">{fmtMin(total)}</TableCell>
                      })}
                      <TableCell className="text-right mono">
                        {fmtMin(weeklyData.users.reduce((sum, u) => sum + (u.total_minutes || 0), 0))}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      {activeTab === "tarea" && (
        <TaskTab weeklyData={weeklyData} weekLoading={weekLoading} />
      )}

      {activeTab === "trabajador" && (
        <WorkerTab
          weeklyData={weeklyData}
          weekLoading={weekLoading}
          assignedTasks={myTasks}
        />
      )}

      {activeTab === "cliente" && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Building2 className="h-5 w-5" />
              Por Cliente
            </CardTitle>
            <p className="text-sm text-muted-foreground">Horas y coste agrupados por cliente para el periodo seleccionado.</p>
          </CardHeader>
          <CardContent>
            {clientReportQuery.isLoading ? (
              <div className="text-sm text-muted-foreground">Cargando...</div>
            ) : clientReportQuery.isError && clientReport.length === 0 ? (
              <RecoveryNotice label="el informe por cliente" onRetry={() => void clientReportQuery.refetch()} />
            ) : <>
              {clientReportQuery.isError && <div className="mb-3"><RecoveryNotice label="el informe por cliente" onRetry={() => void clientReportQuery.refetch()} /></div>}
              {clientReport.length === 0 ? (
              <EmptyState icon={Building2} title="Sin datos por cliente" description="Asigna tareas a tus registros de tiempo para ver el desglose por cliente." />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Cliente</TableHead>
                    <TableHead className="text-right">Horas</TableHead>
                    <TableHead className="text-right">Coste EUR</TableHead>
                    <TableHead className="text-right">Registros</TableHead>
                    <TableHead className="text-right">Personas</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {clientReport.map((c) => (
                    <ClientReportRow key={c.client_id ?? "null"} client={c} />
                  ))}
                </TableBody>
              </Table>
              )}
            </>}
          </CardContent>
        </Card>
      )}

      {activeTab === "proyecto" && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FolderKanban className="h-5 w-5" />
              Por Proyecto
            </CardTitle>
            <p className="text-sm text-muted-foreground">Horas agrupadas por proyecto para el periodo seleccionado.</p>
          </CardHeader>
          <CardContent>
            {projectReportQuery.isLoading ? (
              <div className="text-sm text-muted-foreground">Cargando...</div>
            ) : projectReportQuery.isError && projectReport.length === 0 ? (
              <RecoveryNotice label="el informe por proyecto" onRetry={() => void projectReportQuery.refetch()} />
            ) : <>
              {projectReportQuery.isError && <div className="mb-3"><RecoveryNotice label="el informe por proyecto" onRetry={() => void projectReportQuery.refetch()} /></div>}
              {projectReport.length === 0 ? (
              <EmptyState icon={FolderKanban} title="Sin datos por proyecto" description="Asigna tareas a tus registros de tiempo para ver el desglose por proyecto." />
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
            </>}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
