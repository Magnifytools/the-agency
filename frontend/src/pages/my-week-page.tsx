import { useState, useMemo, useCallback } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { myWeekApi, tasksApi } from "@/lib/api"
import type { MyWeekResponse, MyWeekTask, MyWeekDay, EventResponse } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import {
  ChevronLeft, ChevronRight, Calendar, Plus, X,
  Clock, AlertTriangle, MapPin, Palmtree, Thermometer,
  PartyPopper, Check, MessageSquare,
  ChevronDown, ChevronUp, Send,
} from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

// ── Helpers ────────────────────────────────────────────────

function parseLocalDate(str: string) {
  const [y, m, d] = str.split("-").map(Number)
  return new Date(y, m - 1, d)
}

function toDateStr(d: Date) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

function getMonday(d: Date) {
  const date = new Date(d)
  const day = date.getDay()
  const diff = (day === 0 ? -6 : 1) - day
  date.setDate(date.getDate() + diff)
  date.setHours(0, 0, 0, 0)
  return date
}

function fmtMin(m: number | null) {
  if (!m) return ""
  const h = Math.floor(m / 60)
  const min = m % 60
  return h > 0 ? (min > 0 ? `${h}h ${min}m` : `${h}h`) : `${min}m`
}

const DAY_STATUS_OPTIONS = [
  { value: "available", label: "Normal", icon: null },
  { value: "away", label: "Fuera", icon: MapPin },
  { value: "vacation", label: "Vacaciones", icon: Palmtree },
  { value: "sick", label: "Baja", icon: Thermometer },
  { value: "holiday", label: "Festivo", icon: PartyPopper },
]

const STATUS_COLORS: Record<string, string> = {
  away: "bg-amber-500/10 border-amber-500/30",
  vacation: "bg-blue-500/10 border-blue-500/30",
  sick: "bg-red-500/10 border-red-500/30",
  holiday: "bg-purple-500/10 border-purple-500/30",
}

const STATUS_BADGES: Record<string, string> = {
  away: "bg-amber-500/20 text-amber-400",
  vacation: "bg-blue-500/20 text-blue-400",
  sick: "bg-red-500/20 text-red-400",
  holiday: "bg-purple-500/20 text-purple-400",
}

// ── Task Card ──────────────────────────────────────────────

function TaskCard({
  task,
  onComplete,
  onAddComment,
  compact = false,
}: {
  task: MyWeekTask
  onComplete: (id: number) => void
  onAddComment: (id: number, content: string) => void
  compact?: boolean
}) {
  const [showComment, setShowComment] = useState(false)
  const [comment, setComment] = useState("")

  const handleSubmitComment = () => {
    if (!comment.trim()) return
    onAddComment(task.id, comment.trim())
    setComment("")
    setShowComment(false)
  }

  return (
    <div
      className={`group border border-border rounded-md p-2 hover:border-primary/30 transition-colors ${
        task.status === "waiting" ? "opacity-60" : ""
      }`}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("task-id", String(task.id))
        e.dataTransfer.effectAllowed = "move"
      }}
    >
      <div className="flex items-start gap-2">
        <button
          onClick={() => onComplete(task.id)}
          className="mt-0.5 h-4 w-4 shrink-0 rounded border border-muted-foreground/40 hover:border-primary hover:bg-primary/10 flex items-center justify-center transition-colors"
          title="Completar tarea"
        >
          {task.status === "completed" && <Check className="h-3 w-3 text-primary" />}
        </button>
        <div className="flex-1 min-w-0">
          <p className={`text-sm font-medium leading-tight ${compact ? "truncate" : ""}`}>
            {task.title}
          </p>
          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
            {task.client_name && (
              <span className="text-[10px] text-muted-foreground">{task.client_name}</span>
            )}
            {task.estimated_minutes && (
              <span className="text-[10px] text-muted-foreground flex items-center gap-0.5">
                <Clock className="h-2.5 w-2.5" />
                {fmtMin(task.estimated_minutes)}
              </span>
            )}
            {task.weeks_open > 1 && (
              <span className="text-[10px] text-red-400 flex items-center gap-0.5">
                <AlertTriangle className="h-2.5 w-2.5" />
                {task.weeks_open}sem
              </span>
            )}
            {task.checklist_total > 0 && (
              <span className="text-[10px] text-muted-foreground">
                ✓ {task.checklist_done}/{task.checklist_total}
              </span>
            )}
            {task.status === "waiting" && (
              <Badge variant="outline" className="text-[9px] px-1 py-0">esperando</Badge>
            )}
          </div>
          {/* Last comment */}
          {task.last_comment && !compact && (
            <p className="text-[10px] text-muted-foreground/70 mt-1 italic truncate">
              → {task.last_comment}
            </p>
          )}
        </div>
        <button
          onClick={() => setShowComment(!showComment)}
          className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-muted"
          title="Añadir nota"
        >
          <MessageSquare className="h-3 w-3 text-muted-foreground" />
        </button>
      </div>

      {/* Inline comment input */}
      {showComment && (
        <div className="flex items-center gap-1 mt-2">
          <Input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Nota rápida..."
            className="h-6 text-xs flex-1"
            onKeyDown={(e) => e.key === "Enter" && handleSubmitComment()}
            autoFocus
          />
          <Button size="icon" variant="ghost" className="h-6 w-6 shrink-0" onClick={handleSubmitComment}>
            <Send className="h-3 w-3" />
          </Button>
        </div>
      )}
    </div>
  )
}

// ── Event Row ──────────────────────────────────────────────

function EventRow({ event, onDelete }: { event: EventResponse; onDelete: (id: number) => void }) {
  return (
    <div className="flex items-center gap-2 text-xs group">
      <span className="text-muted-foreground mono w-10 shrink-0">{event.time || "—"}</span>
      <span className="font-medium truncate flex-1">{event.title}</span>
      {event.client_name && <span className="text-muted-foreground/60 text-[10px]">{event.client_name}</span>}
      <button
        onClick={() => onDelete(event.id)}
        className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-destructive/10"
      >
        <X className="h-3 w-3 text-destructive" />
      </button>
    </div>
  )
}

// ── Day Column ─────────────────────────────────────────────

function DayColumn({
  day,
  isToday,
  onStatusChange,
  onDeleteEvent,
  onAddEvent,
  onCompleteTask,
  onAddComment,
  onDropTask,
}: {
  day: MyWeekDay
  isToday: boolean
  onStatusChange: (date: string, status: string, label?: string) => void
  onDeleteEvent: (id: number) => void
  onAddEvent: (date: string) => void
  onCompleteTask: (id: number) => void
  onAddComment: (id: number, content: string) => void
  onDropTask: (taskId: number, date: string) => void
}) {
  const [showStatusSelect, setShowStatusSelect] = useState(false)
  const [statusLabel, setStatusLabel] = useState("")

  const d = parseLocalDate(day.date)
  const dayNum = d.getDate()
  const isWeekend = d.getDay() === 0 || d.getDay() === 6

  const dayStatus = day.status?.status || (day.is_holiday ? "holiday" : "available")
  const statusColor = STATUS_COLORS[dayStatus] || ""
  const isUnavailable = ["away", "vacation", "sick", "holiday"].includes(dayStatus)

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = "move"
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const taskId = e.dataTransfer.getData("task-id")
    if (taskId) {
      onDropTask(Number(taskId), day.date)
    }
  }

  return (
    <div
      className={`flex flex-col min-h-[400px] border border-border rounded-lg overflow-hidden ${statusColor} ${
        isToday ? "ring-2 ring-primary/40" : ""
      } ${isWeekend ? "opacity-50" : ""}`}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Day Header */}
      <div className={`px-2 py-1.5 border-b border-border flex items-center justify-between ${isToday ? "bg-primary/5" : "bg-muted/30"}`}>
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-bold uppercase">{day.weekday}</span>
          <span className={`text-sm font-bold ${isToday ? "text-primary" : ""}`}>{dayNum}</span>
        </div>
        <button
          onClick={() => setShowStatusSelect(!showStatusSelect)}
          className="p-0.5 rounded hover:bg-muted transition-colors"
          title="Estado del día"
        >
          {dayStatus === "away" && <MapPin className="h-3.5 w-3.5 text-amber-500" />}
          {dayStatus === "vacation" && <Palmtree className="h-3.5 w-3.5 text-blue-500" />}
          {dayStatus === "sick" && <Thermometer className="h-3.5 w-3.5 text-red-500" />}
          {dayStatus === "holiday" && <PartyPopper className="h-3.5 w-3.5 text-purple-500" />}
          {dayStatus === "available" && <Calendar className="h-3.5 w-3.5 text-muted-foreground/40" />}
        </button>
      </div>

      {/* Status selector dropdown */}
      {showStatusSelect && (
        <div className="px-2 py-1.5 border-b border-border bg-background space-y-1">
          <div className="flex gap-1 flex-wrap">
            {DAY_STATUS_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => {
                  if (opt.value === "available") {
                    // Remove status
                    onStatusChange(day.date, "available")
                  } else {
                    onStatusChange(day.date, opt.value, statusLabel || undefined)
                  }
                  setShowStatusSelect(false)
                }}
                className={`text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
                  dayStatus === opt.value ? "border-primary bg-primary/10" : "border-border hover:border-primary/30"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <Input
            value={statusLabel}
            onChange={(e) => setStatusLabel(e.target.value)}
            placeholder="Etiqueta (Madrid, Evento...)"
            className="h-6 text-[10px]"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                onStatusChange(day.date, dayStatus === "available" ? "away" : dayStatus, statusLabel)
                setShowStatusSelect(false)
              }
            }}
          />
        </div>
      )}

      {/* Status label */}
      {(day.status?.label || day.is_holiday?.name) && (
        <div className={`px-2 py-0.5 text-[10px] font-medium ${STATUS_BADGES[dayStatus] || "text-muted-foreground"}`}>
          {day.status?.label || day.is_holiday?.name}
        </div>
      )}

      {/* Events */}
      {day.events.length > 0 && (
        <div className="px-2 py-1 border-b border-border/50 space-y-0.5">
          {day.events.map((ev) => (
            <EventRow key={ev.id} event={ev} onDelete={onDeleteEvent} />
          ))}
        </div>
      )}

      {/* Tasks */}
      <div className="flex-1 p-1.5 space-y-1 overflow-y-auto">
        {isUnavailable && day.tasks.length === 0 ? (
          <p className="text-[10px] text-muted-foreground/50 text-center py-4 italic">
            {dayStatus === "vacation" ? "De vacaciones" : dayStatus === "away" ? "Fuera" : dayStatus === "sick" ? "De baja" : "Festivo"}
          </p>
        ) : (
          day.tasks.map((t) => (
            <TaskCard
              key={t.id}
              task={t}
              onComplete={onCompleteTask}
              onAddComment={onAddComment}
              compact
            />
          ))
        )}
      </div>

      {/* Add event button */}
      {!isWeekend && (
        <div className="px-2 py-1 border-t border-border/30">
          <button
            onClick={() => onAddEvent(day.date)}
            className="text-[10px] text-muted-foreground/50 hover:text-primary flex items-center gap-0.5 transition-colors"
          >
            <Plus className="h-3 w-3" /> evento
          </button>
        </div>
      )}

      {/* Notes */}
      {day.status?.note && (
        <div className="px-2 py-1 border-t border-border/30 bg-muted/20">
          <p className="text-[10px] text-muted-foreground italic">{day.status.note}</p>
        </div>
      )}
    </div>
  )
}

// ── Add Event Dialog (inline) ──────────────────────────────

function AddEventInline({
  date,
  onSave,
  onCancel,
}: {
  date: string
  onSave: (data: { date: string; time: string; title: string; duration_minutes?: number }) => void
  onCancel: () => void
}) {
  const [time, setTime] = useState("10:00")
  const [title, setTitle] = useState("")
  const [duration, setDuration] = useState("60")

  return (
    <Card className="border-primary/30">
      <CardContent className="p-3 space-y-2">
        <p className="text-xs font-bold">Nuevo evento — {parseLocalDate(date).toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "short" })}</p>
        <div className="flex gap-2">
          <Input value={time} onChange={(e) => setTime(e.target.value)} type="time" className="h-7 text-xs w-24" />
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Título del evento"
            className="h-7 text-xs flex-1"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter" && title.trim()) {
                onSave({ date, time, title: title.trim(), duration_minutes: Number(duration) || undefined })
              }
              if (e.key === "Escape") onCancel()
            }}
          />
          <Input value={duration} onChange={(e) => setDuration(e.target.value)} placeholder="min" className="h-7 text-xs w-16" type="number" />
        </div>
        <div className="flex gap-1 justify-end">
          <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={onCancel}>Cancelar</Button>
          <Button
            size="sm"
            className="h-6 text-xs"
            onClick={() => title.trim() && onSave({ date, time, title: title.trim(), duration_minutes: Number(duration) || undefined })}
          >
            Guardar
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ── Backlog Section ────────────────────────────────────────

function BacklogSection({
  tasks,
  onComplete,
  onAddComment,
}: {
  tasks: MyWeekTask[]
  onComplete: (id: number) => void
  onAddComment: (id: number, content: string) => void
}) {
  const [expanded, setExpanded] = useState(true)

  // Group by client
  const grouped = useMemo(() => {
    const map = new Map<string, MyWeekTask[]>()
    for (const t of tasks) {
      const key = t.client_name || "Sin cliente"
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(t)
    }
    return Array.from(map.entries()).sort((a, b) => b[1].length - a[1].length)
  }, [tasks])

  if (tasks.length === 0) return null

  return (
    <Card>
      <CardHeader className="py-2 px-4 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <CardTitle className="text-sm flex items-center gap-2">
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          Backlog — Tareas sin programar ({tasks.length})
        </CardTitle>
      </CardHeader>
      {expanded && (
        <CardContent className="px-4 pb-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {grouped.map(([clientName, clientTasks]) => (
              <div key={clientName}>
                <p className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-1.5">
                  {clientName} ({clientTasks.length})
                </p>
                <div className="space-y-1">
                  {clientTasks.map((t) => (
                    <TaskCard
                      key={t.id}
                      task={t}
                      onComplete={onComplete}
                      onAddComment={onAddComment}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      )}
    </Card>
  )
}

// ── Summary Panel ──────────────────────────────────────────

function SummaryPanel({ data }: { data: MyWeekResponse }) {
  const s = data.summary
  const estHours = Math.round(s.estimated_minutes / 60 * 10) / 10

  return (
    <div className="space-y-4">
      {/* Load */}
      <div>
        <p className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-1">Carga</p>
        <div className="flex items-baseline gap-1">
          <span className="text-2xl font-bold">{estHours}h</span>
          <span className="text-sm text-muted-foreground">/ {s.available_hours}h</span>
        </div>
        <div className="h-2 bg-muted rounded-full mt-1 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              estHours / s.available_hours > 0.9 ? "bg-red-500" : estHours / s.available_hours > 0.7 ? "bg-amber-500" : "bg-green-500"
            }`}
            style={{ width: `${Math.min((estHours / (s.available_hours || 1)) * 100, 100)}%` }}
          />
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-2">
        <div className="text-center p-2 bg-muted/30 rounded">
          <p className="text-lg font-bold">{s.total_tasks}</p>
          <p className="text-[10px] text-muted-foreground">tareas</p>
        </div>
        <div className="text-center p-2 bg-muted/30 rounded">
          <p className="text-lg font-bold">{s.tasks_no_date}</p>
          <p className="text-[10px] text-muted-foreground">sin fecha</p>
        </div>
        {s.tasks_dragging > 0 && (
          <div className="text-center p-2 bg-red-500/10 rounded col-span-2">
            <p className="text-lg font-bold text-red-400">{s.tasks_dragging}</p>
            <p className="text-[10px] text-red-400">arrastrándose (&gt;1 sem)</p>
          </div>
        )}
        {s.tasks_no_estimate > 0 && (
          <div className="text-center p-2 bg-amber-500/10 rounded col-span-2">
            <p className="text-lg font-bold text-amber-400">{s.tasks_no_estimate}</p>
            <p className="text-[10px] text-amber-400">sin estimación</p>
          </div>
        )}
      </div>

      {/* By Client */}
      {s.by_client.length > 0 && (
        <div>
          <p className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-1">Por cliente</p>
          <div className="space-y-1">
            {s.by_client.map((c) => (
              <div key={c.client_id ?? "null"} className="flex items-center justify-between text-xs">
                <span className="truncate">{c.client_name}</span>
                <span className="font-bold ml-2 shrink-0">{c.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────

export default function MyWeekPage() {
  const queryClient = useQueryClient()
  const [weekStart, setWeekStart] = useState(() => toDateStr(getMonday(new Date())))
  const [addEventDate, setAddEventDate] = useState<string | null>(null)

  const todayStr = toDateStr(new Date())

  const { data, isLoading, error } = useQuery({
    queryKey: ["my-week", weekStart],
    queryFn: () => myWeekApi.get(weekStart),
  })

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["my-week"] })
  }, [queryClient])

  // Mutations
  const statusMutation = useMutation({
    mutationFn: (vars: { date: string; status: string; label?: string }) =>
      vars.status === "available"
        ? myWeekApi.deleteDayStatus(vars.date)
        : myWeekApi.updateDayStatus({ date: vars.date, status: vars.status, label: vars.label }),
    onSuccess: invalidate,
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar estado")),
  })

  const eventMutation = useMutation({
    mutationFn: (data: { date: string; time: string; title: string; duration_minutes?: number }) =>
      myWeekApi.createEvent(data),
    onSuccess: () => { invalidate(); setAddEventDate(null); toast.success("Evento creado") },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear evento")),
  })

  const deleteEventMutation = useMutation({
    mutationFn: (id: number) => myWeekApi.deleteEvent(id),
    onSuccess: () => { invalidate(); toast.success("Evento eliminado") },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar evento")),
  })

  const scheduleMutation = useMutation({
    mutationFn: (vars: { taskId: number; date: string | null }) =>
      myWeekApi.scheduleTask(vars.taskId, vars.date),
    onSuccess: invalidate,
    onError: (err) => toast.error(getErrorMessage(err, "Error al programar tarea")),
  })

  const completeMutation = useMutation({
    mutationFn: (taskId: number) =>
      tasksApi.update(taskId, { status: "completed" }),
    onSuccess: () => { invalidate(); toast.success("Tarea completada") },
    onError: (err) => toast.error(getErrorMessage(err, "Error al completar tarea")),
  })

  const commentMutation = useMutation({
    mutationFn: (vars: { taskId: number; content: string }) =>
      myWeekApi.addTaskComment(vars.taskId, vars.content),
    onSuccess: () => { invalidate(); toast.success("Nota añadida") },
    onError: (err) => toast.error(getErrorMessage(err, "Error al añadir nota")),
  })

  // Handlers
  const handleStatusChange = (date: string, status: string, label?: string) => {
    statusMutation.mutate({ date, status, label })
  }

  const handleCompleteTask = (id: number) => completeMutation.mutate(id)
  const handleAddComment = (id: number, content: string) => commentMutation.mutate({ taskId: id, content })

  const handleDropTask = (taskId: number, date: string) => {
    scheduleMutation.mutate({ taskId, date })
  }

  // Navigation
  const goBack = () => {
    const d = parseLocalDate(weekStart)
    d.setDate(d.getDate() - 7)
    setWeekStart(toDateStr(getMonday(d)))
  }

  const goForward = () => {
    const d = parseLocalDate(weekStart)
    d.setDate(d.getDate() + 7)
    setWeekStart(toDateStr(getMonday(d)))
  }

  const goToday = () => setWeekStart(toDateStr(getMonday(new Date())))

  // Only show Mon-Fri
  const weekDays = data?.days.filter((_, i) => i < 5) || []

  const weekLabel = data
    ? `${parseLocalDate(data.week_start).toLocaleDateString("es-ES", { day: "numeric", month: "short" })} — ${parseLocalDate(data.week_end).toLocaleDateString("es-ES", { day: "numeric", month: "short" })}`
    : ""

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold uppercase tracking-wide">Mi Semana</h2>
          <p className="text-sm text-muted-foreground mt-0.5">{weekLabel}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={goBack}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" className="text-xs h-8" onClick={goToday}>
            Hoy
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={goForward}>
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {isLoading && (
        <div className="text-sm text-muted-foreground animate-pulse py-12 text-center">
          Cargando semana...
        </div>
      )}

      {error && (
        <div className="text-sm text-red-500 py-4">
          Error al cargar datos.{" "}
          <button className="underline" onClick={() => queryClient.invalidateQueries({ queryKey: ["my-week"] })}>
            Reintentar
          </button>
        </div>
      )}

      {data && (
        <div className="flex gap-4">
          {/* Calendar grid: 5 day columns */}
          <div className="flex-1 grid grid-cols-5 gap-2">
            {weekDays.map((day) => (
              <DayColumn
                key={day.date}
                day={day}
                isToday={day.date === todayStr}
                onStatusChange={handleStatusChange}
                onDeleteEvent={(id) => deleteEventMutation.mutate(id)}
                onAddEvent={(date) => setAddEventDate(date)}
                onCompleteTask={handleCompleteTask}
                onAddComment={handleAddComment}
                onDropTask={handleDropTask}
              />
            ))}
          </div>

          {/* Summary sidebar */}
          <div className="w-48 shrink-0 hidden lg:block">
            <Card>
              <CardHeader className="py-2 px-3">
                <CardTitle className="text-xs uppercase tracking-wider">Resumen</CardTitle>
              </CardHeader>
              <CardContent className="px-3 pb-3">
                <SummaryPanel data={data} />
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* Add event inline */}
      {addEventDate && (
        <AddEventInline
          date={addEventDate}
          onSave={(data) => eventMutation.mutate(data)}
          onCancel={() => setAddEventDate(null)}
        />
      )}

      {/* Backlog */}
      {data && (
        <BacklogSection
          tasks={data.backlog}
          onComplete={handleCompleteTask}
          onAddComment={handleAddComment}
        />
      )}
    </div>
  )
}
