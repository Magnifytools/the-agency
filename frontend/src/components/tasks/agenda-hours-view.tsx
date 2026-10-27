import { useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react"
import {
  DndContext, PointerSensor, TouchSensor, pointerWithin, useDraggable, useDroppable, useSensor, useSensors,
  type DragEndEvent,
} from "@dnd-kit/core"
import { CSS } from "@dnd-kit/utilities"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ChevronLeft, ChevronRight, Clock3, Plus, X } from "lucide-react"
import { toast } from "sonner"
import type { Task } from "@/lib/types"
import { calendarApi, timeBlocksApi, type CalendarEvent, type TimeBlock } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Popover } from "@/components/ui/popover"
import { TimerButton } from "@/components/timer/timer-button"
import { addCivilDays, businessMinutes, formatCivilDate } from "@/lib/dates"
import { cn, getErrorMessage } from "@/lib/utils"
import {
  GRID_END, GRID_END_HOUR, GRID_START, GRID_START_HOUR, MIN_BLOCK, PX_PER_MINUTE,
  clockMinutes, dayOf, formatClock, layoutDay, minutesOf, newBlockMinutes, placeBlock, snap, stampAt, workWeek,
} from "@/lib/time-grid"

export type HoursMode = "day" | "week"

interface Props {
  mode: HoursMode
  /** Día que se enseña (o cuya semana se enseña). */
  anchor: string
  today: string
  onAnchorChange: (day: string) => void
  onModeChange: (mode: HoursMode) => void
  /** Tareas a las que se puede dar hora (las de hoy y el arrastre). */
  candidates: Task[]
  canWrite: boolean
  onOpenTask: (taskId: number) => void
}

type DragData = { kind: "block"; block: TimeBlock } | { kind: "task"; task: Task }

const blockKeys = (from: string, to: string) => ["time-blocks", from, to] as const
const blockEnd = (block: TimeBlock) => dayOf(block.ends_at) !== dayOf(block.starts_at) ? 1440 : minutesOf(block.ends_at)
const eventRange = (event: CalendarEvent) => {
  const start = minutesOf(event.start_time)
  const end = event.end_time && dayOf(event.end_time) === dayOf(event.start_time) ? minutesOf(event.end_time) : start + 30
  return { start, end: Math.max(end, start + MIN_BLOCK) }
}
const HOURS = Array.from({ length: GRID_END_HOUR - GRID_START_HOUR }, (_, index) => GRID_START_HOUR + index)
const GRID_HEIGHT = (GRID_END - GRID_START) * PX_PER_MINUTE

/**
 * Mi agenda con horas: reuniones de Google (sólo lectura) y bloques de trabajo
 * propios. Los bloques se arrastran (cambian de hora o de día), se estiran por
 * abajo y arrancan el cronómetro; las tareas sin hora se arrastran a un hueco.
 */
export function AgendaHoursView({ mode, anchor, today, onAnchorChange, onModeChange, candidates, canWrite, onOpenTask }: Props) {
  const queryClient = useQueryClient()
  const days = mode === "week" ? workWeek(anchor) : [anchor]
  const from = days[0]
  const to = days[days.length - 1]
  const key = blockKeys(from, to)
  const blocksQuery = useQuery({ queryKey: key, queryFn: () => timeBlocksApi.list(from, to) })
  const eventsQuery = useQuery({ queryKey: ["calendar-events", from, to], queryFn: () => calendarApi.events(from, to) })
  const blocks = blocksQuery.data ?? []

  // Cambios al momento en la cuadrícula; si el servidor dice que no, vuelve atrás.
  const optimistic = async (change: (current: TimeBlock[]) => TimeBlock[]) => {
    await queryClient.cancelQueries({ queryKey: key })
    const previous = queryClient.getQueryData<TimeBlock[]>(key)
    queryClient.setQueryData<TimeBlock[]>(key, (current = []) => change(current))
    return { previous }
  }
  const onFailure = (fallback: string) => (error: unknown, _vars: unknown, context?: { previous?: TimeBlock[] }) => {
    if (context?.previous) queryClient.setQueryData(key, context.previous)
    toast.error(getErrorMessage(error, fallback))
  }
  const settle = () => queryClient.invalidateQueries({ queryKey: ["time-blocks"] })
  const createBlock = useMutation({
    mutationFn: (data: { task: Task; starts_at: string; ends_at: string }) =>
      timeBlocksApi.create({ task_id: data.task.id, starts_at: data.starts_at, ends_at: data.ends_at }),
    onMutate: ({ task, starts_at, ends_at }) => optimistic((current) => [...current, {
      id: -Date.now(), task_id: task.id, starts_at, ends_at, task_title: task.title, task_status: task.status,
      task_estimated_minutes: task.estimated_minutes, client_name: task.client_name,
    }]),
    onError: onFailure("No se pudo crear el bloque"),
    onSettled: settle,
  })
  const moveBlock = useMutation({
    mutationFn: (data: { block: TimeBlock; starts_at: string; ends_at: string }) =>
      timeBlocksApi.update(data.block.id, { starts_at: data.starts_at, ends_at: data.ends_at }),
    onMutate: ({ block, starts_at, ends_at }) => optimistic((current) => current.map((item) => item.id === block.id ? { ...item, starts_at, ends_at } : item)),
    onError: onFailure("No se pudo mover el bloque"),
    onSettled: settle,
  })
  const deleteBlock = useMutation({
    mutationFn: (block: TimeBlock) => timeBlocksApi.delete(block.id),
    onMutate: (block) => optimistic((current) => current.filter((item) => item.id !== block.id)),
    onSuccess: () => toast.success("Bloque quitado. Se deshace con ⌘Z."),
    onError: onFailure("No se pudo quitar el bloque"),
    onSettled: settle,
  })

  const retime = (block: TimeBlock, day: string, start: number, end: number) => {
    if (start === minutesOf(block.starts_at) && end === blockEnd(block) && day === dayOf(block.starts_at)) return
    moveBlock.mutate({ block, starts_at: stampAt(day, start), ends_at: stampAt(day, end) })
  }
  const addAt = (task: Task, day: string, start: number) => {
    const { start: from, end } = placeBlock(start, newBlockMinutes(task.estimated_minutes))
    createBlock.mutate({ task, starts_at: stampAt(day, from), ends_at: stampAt(day, end) })
  }

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 5 } }),
  )
  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    const day = (over?.data.current as { day?: string } | undefined)?.day
    const data = active.data.current as DragData | undefined
    const dragged = active.rect.current.translated
    if (!day || !data || !over || !dragged) return
    // Dónde queda el borde de arriba de lo arrastrado dentro de la columna.
    const start = GRID_START + (dragged.top - over.rect.top) / PX_PER_MINUTE
    if (data.kind === "block") {
      const length = blockEnd(data.block) - minutesOf(data.block.starts_at)
      const placed = placeBlock(start, length)
      retime(data.block, day, placed.start, placed.end)
    } else {
      addAt(data.task, day, start)
    }
  }

  const blockedTaskIds = new Set(blocks.filter((block) => dayOf(block.starts_at) === today).map((block) => block.task_id))
  const unscheduled = candidates.filter((task) => task.status !== "completed" && !blockedTaskIds.has(task.id))
  const step = mode === "week" ? 7 : 1
  const nowMinutes = businessMinutes()

  return (
    <DndContext sensors={canWrite ? sensors : []} collisionDetection={pointerWithin} onDragEnd={canWrite ? handleDragEnd : undefined}>
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="Vista con horas" className="flex rounded-lg border border-border bg-muted/30 p-0.5">
            {(["day", "week"] as const).map((value) => (
              <Button key={value} type="button" size="sm" variant={mode === value ? "default" : "ghost"} aria-pressed={mode === value}
                className="h-7 px-3 text-xs" onClick={() => onModeChange(value)}>
                {value === "day" ? "Día" : "Semana"}
              </Button>
            ))}
          </div>
          <Button type="button" variant="ghost" size="icon" className="h-8 w-8" aria-label={mode === "week" ? "Semana anterior" : "Día anterior"} onClick={() => onAnchorChange(addCivilDays(anchor, -step))}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button type="button" variant="outline" size="sm" className="h-8" onClick={() => onAnchorChange(today)}>Hoy</Button>
          <Button type="button" variant="ghost" size="icon" className="h-8 w-8" aria-label={mode === "week" ? "Semana siguiente" : "Día siguiente"} onClick={() => onAnchorChange(addCivilDays(anchor, step))}>
            <ChevronRight className="h-4 w-4" />
          </Button>
          <p className="text-sm font-medium first-letter:uppercase">
            {mode === "week"
              ? `${formatCivilDate(from, { day: "numeric", month: "short" })} – ${formatCivilDate(to, { day: "numeric", month: "short" })}`
              : formatCivilDate(anchor, { weekday: "long", day: "numeric", month: "long" })}
          </p>
          {(blocksQuery.isError || eventsQuery.isError) && (
            <p role="alert" className="text-xs text-destructive">
              No se pudieron cargar {blocksQuery.isError ? "los bloques" : "las reuniones"}.{" "}
              <button type="button" className="underline" onClick={() => { void blocksQuery.refetch(); void eventsQuery.refetch() }}>Reintentar</button>
            </p>
          )}
        </div>

        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_16rem]">
          <div className="overflow-x-auto rounded-xl border border-border bg-card">
            <div className={cn("grid", mode === "week" && "min-w-[640px]")} style={{ gridTemplateColumns: `3rem repeat(${days.length}, minmax(0, 1fr))` }}>
              <div className="border-b border-border" />
              {days.map((day) => (
                <div key={day} className={cn("border-b border-l border-border px-2 py-1.5 text-xs font-medium first-letter:uppercase", day === today && "text-brand")}>
                  {formatCivilDate(day, { weekday: "short", day: "numeric" })}
                </div>
              ))}
              <div className="relative" style={{ height: GRID_HEIGHT }}>
                {HOURS.map((hour) => (
                  <span key={hour} className="absolute right-1.5 -translate-y-1/2 text-[10px] text-muted-foreground mono" style={{ top: (hour * 60 - GRID_START) * PX_PER_MINUTE }}>
                    {hour > GRID_START_HOUR ? `${hour}:00` : ""}
                  </span>
                ))}
              </div>
              {days.map((day) => (
                <DayColumn
                  key={day}
                  day={day}
                  isToday={day === today}
                  nowMinutes={nowMinutes}
                  events={(eventsQuery.data ?? []).filter((event) => !event.is_all_day && dayOf(event.start_time) === day)}
                  blocks={blocks.filter((block) => dayOf(block.starts_at) === day)}
                  canWrite={canWrite}
                  onOpenTask={onOpenTask}
                  onRetime={retime}
                  onDelete={(block) => deleteBlock.mutate(block)}
                />
              ))}
            </div>
          </div>

          <aside aria-label="Tareas sin hora" className="space-y-2">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Sin hora hoy ({unscheduled.length})</p>
            <p className="text-xs text-muted-foreground">
              {canWrite ? "Arrástralas a un hueco. El bloque dura lo estimado (una hora si no hay estimación)." : "Sin permiso para planificar."}
            </p>
            {unscheduled.map((task) => (
              <UnscheduledTask key={task.id} task={task} canWrite={canWrite} onOpen={() => onOpenTask(task.id)} onAdd={(start) => addAt(task, today, start)} />
            ))}
            {!unscheduled.length && <p className="rounded-lg border border-dashed border-border p-3 text-xs text-muted-foreground">Todo lo de hoy tiene hora.</p>}
          </aside>
        </div>
      </div>
    </DndContext>
  )
}

function DayColumn({ day, isToday, nowMinutes, events, blocks, canWrite, onOpenTask, onRetime, onDelete }: {
  day: string
  isToday: boolean
  nowMinutes: number
  events: CalendarEvent[]
  blocks: TimeBlock[]
  canWrite: boolean
  onOpenTask: (taskId: number) => void
  onRetime: (block: TimeBlock, day: string, start: number, end: number) => void
  onDelete: (block: TimeBlock) => void
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `col-${day}`, data: { day } })
  type Entry = { kind: "event"; event: CalendarEvent } | { kind: "block"; block: TimeBlock }
  const entries: Entry[] = [
    ...events.map((event) => ({ kind: "event" as const, event })),
    ...blocks.map((block) => ({ kind: "block" as const, block })),
  ]
  const placed = layoutDay(entries, (entry) => entry.kind === "event"
    ? eventRange(entry.event)
    : { start: minutesOf(entry.block.starts_at), end: blockEnd(entry.block) })
  return (
    <div
      ref={setNodeRef}
      role="region"
      aria-label={`Horas del ${formatCivilDate(day, { weekday: "long", day: "numeric" })}`}
      className={cn("relative border-l border-border", isOver && "bg-brand/5")}
      style={{ height: GRID_HEIGHT }}
    >
      {HOURS.map((hour) => (
        <div key={hour} className="absolute inset-x-0 border-t border-border/50" style={{ top: (hour * 60 - GRID_START) * PX_PER_MINUTE }} />
      ))}
      {placed.map(({ item, top, height, lane, lanes }) => {
        const style: CSSProperties = { top, height, left: `calc(${(lane / lanes) * 100}% + 2px)`, width: `calc(${100 / lanes}% - 4px)` }
        return item.kind === "event" ? (
          <div key={`e${item.event.id}`} style={style} title={item.event.title}
            className="absolute overflow-hidden rounded-md border border-border bg-muted/80 px-1.5 py-0.5 text-[11px] text-muted-foreground">
            <span className="font-medium text-foreground">{item.event.title}</span>{" "}
            <span className="mono">{formatClock(eventRange(item.event).start)}</span>
          </div>
        ) : (
          <BlockItem key={`b${item.block.id}`} block={item.block} style={style} canWrite={canWrite}
            onOpen={() => onOpenTask(item.block.task_id)} onRetime={(start, end) => onRetime(item.block, day, start, end)}
            onDelete={() => onDelete(item.block)} />
        )
      })}
      {isToday && nowMinutes >= GRID_START && nowMinutes <= GRID_END && (
        <div aria-hidden className="pointer-events-none absolute inset-x-0 z-10 border-t-2 border-red-500" style={{ top: (nowMinutes - GRID_START) * PX_PER_MINUTE }} />
      )}
    </div>
  )
}

function BlockItem({ block, style, canWrite, onOpen, onRetime, onDelete }: {
  block: TimeBlock
  style: CSSProperties
  canWrite: boolean
  onOpen: () => void
  onRetime: (start: number, end: number) => void
  onDelete: () => void
}) {
  const { setNodeRef, attributes, listeners, transform, isDragging } = useDraggable({
    id: `block-${block.id}`, data: { kind: "block", block } satisfies DragData, disabled: !canWrite || block.id < 0,
  })
  const start = minutesOf(block.starts_at)
  const [previewEnd, setPreviewEnd] = useState<number | null>(null)
  const end = previewEnd ?? blockEnd(block)
  const height = Math.max(MIN_BLOCK, Math.min(end, GRID_END) - Math.max(start, GRID_START)) * PX_PER_MINUTE

  // Estirar desde el borde de abajo (de 15 en 15 minutos).
  const startResize = (event: ReactPointerEvent) => {
    event.preventDefault()
    event.stopPropagation()
    const originY = event.clientY
    const originEnd = blockEnd(block)
    let latest = originEnd
    const move = (moveEvent: PointerEvent) => {
      latest = Math.min(GRID_END, Math.max(start + MIN_BLOCK, snap(originEnd + (moveEvent.clientY - originY) / PX_PER_MINUTE)))
      setPreviewEnd(latest)
    }
    const up = () => {
      window.removeEventListener("pointermove", move)
      setPreviewEnd(null)
      if (latest !== originEnd) onRetime(start, latest)
    }
    window.addEventListener("pointermove", move)
    window.addEventListener("pointerup", up, { once: true })
  }

  return (
    <div
      ref={setNodeRef}
      data-time-block={block.id}
      style={{ ...style, height, transform: CSS.Translate.toString(transform), zIndex: isDragging ? 30 : undefined }}
      className={cn(
        "group absolute flex flex-col overflow-hidden rounded-md border border-brand/50 bg-brand/15 text-[11px] text-foreground shadow-sm",
        isDragging && "opacity-80 shadow-lg",
        block.task_status === "completed" && "opacity-60",
      )}
    >
      <div
        {...(canWrite ? attributes : {})}
        {...(canWrite ? listeners : {})}
        className={cn("min-h-0 flex-1 px-1.5 py-0.5", canWrite && "cursor-grab active:cursor-grabbing touch-none")}
        aria-label={`Bloque de ${block.task_title}, de ${formatClock(start)} a ${formatClock(end)}`}
      >
        <button type="button" onClick={onOpen} onPointerDown={(event) => event.stopPropagation()}
          className="block max-w-full truncate text-left font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm">
          {block.task_title}
        </button>
        <span className="block truncate text-muted-foreground">
          <span className="mono">{formatClock(start)}–{formatClock(end)}</span>
          {block.client_name && <span> · {block.client_name}</span>}
        </span>
      </div>
      {canWrite && block.id > 0 && (
        // Al pasar el ratón o al tocar/enfocar el bloque (en el móvil no hay hover).
        <div className="absolute right-0.5 top-0.5 flex items-center gap-0.5 rounded bg-card/90 opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100">
          <TimerButton taskId={block.task_id} taskTitle={block.task_title} />
          <RetimePopover block={block} start={start} end={blockEnd(block)} onSave={onRetime} />
          <button type="button" aria-label={`Quitar el bloque de ${block.task_title}`} title="Quitar bloque"
            onClick={onDelete} className="rounded p-1 text-muted-foreground hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
            <X className="h-3 w-3" />
          </button>
        </div>
      )}
      {canWrite && block.id > 0 && (
        <div role="separator" aria-label="Estirar el bloque" onPointerDown={startResize}
          className="absolute inset-x-0 bottom-0 h-2 cursor-ns-resize touch-none hover:bg-brand/40" />
      )}
    </div>
  )
}

/** Cambiar la hora a mano (con teclado o en el móvil). */
function RetimePopover({ block, start, end, onSave }: { block: TimeBlock; start: number; end: number; onSave: (start: number, end: number) => void }) {
  return (
    <Popover
      label={`Hora del bloque de ${block.task_title}`}
      trigger={({ ref, props }) => (
        <button ref={ref} type="button" aria-label={`Cambiar la hora del bloque de ${block.task_title}`} title="Cambiar hora"
          className="rounded p-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand" {...props}>
          <Clock3 className="h-3 w-3" />
        </button>
      )}
    >
      {(close) => (
        <form
          className="space-y-2 p-2"
          onSubmit={(event) => {
            event.preventDefault()
            const data = new FormData(event.currentTarget)
            const from = clockMinutes(String(data.get("start")))
            const to = clockMinutes(String(data.get("end"))) || 1440
            if (!(to > from)) {
              toast.error("La hora de fin tiene que ser posterior a la de inicio")
              return
            }
            close()
            onSave(from, to)
          }}
        >
          <div className="flex items-center gap-2 text-xs">
            <label className="flex flex-col gap-1">De<input name="start" type="time" step={900} defaultValue={formatClock(start)} className="h-8 rounded-md border border-border bg-background px-2 text-sm [color-scheme:dark]" /></label>
            <label className="flex flex-col gap-1">A<input name="end" type="time" step={900} defaultValue={formatClock(end % 1440)} className="h-8 rounded-md border border-border bg-background px-2 text-sm [color-scheme:dark]" /></label>
          </div>
          <Button type="submit" size="sm" className="w-full">Guardar</Button>
        </form>
      )}
    </Popover>
  )
}

function UnscheduledTask({ task, canWrite, onOpen, onAdd }: {
  task: Task
  canWrite: boolean
  onOpen: () => void
  onAdd: (start: number) => void
}) {
  const { setNodeRef, attributes, listeners, transform, isDragging } = useDraggable({
    id: `task-${task.id}`, data: { kind: "task", task } satisfies DragData, disabled: !canWrite,
  })
  const suggested = Math.min(GRID_END - MIN_BLOCK, Math.max(GRID_START, snap(businessMinutes() + 15)))
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), zIndex: isDragging ? 40 : undefined }}
      className={cn("relative flex items-center gap-2 rounded-lg border border-border bg-card p-2 text-sm", isDragging && "shadow-lg")}
    >
      <div {...(canWrite ? attributes : {})} {...(canWrite ? listeners : {})}
        aria-label={`Dar hora a ${task.title}`}
        className={cn("min-w-0 flex-1", canWrite && "cursor-grab touch-none active:cursor-grabbing")}>
        <button type="button" onClick={onOpen} onPointerDown={(event) => event.stopPropagation()} className="block max-w-full truncate text-left font-medium hover:underline">
          {task.title}
        </button>
        <span className="text-[11px] text-muted-foreground">
          {task.client_name ? `${task.client_name} · ` : ""}{newBlockMinutes(task.estimated_minutes)} min
        </span>
      </div>
      {canWrite && (
        <Popover
          label={`Hora para ${task.title}`}
          trigger={({ ref, props }) => (
            <button ref={ref} type="button" aria-label={`Poner hora a ${task.title}`} title="Poner hora"
              className="rounded p-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand" {...props}>
              <Plus className="h-4 w-4" />
            </button>
          )}
        >
          {(close) => (
            <form className="space-y-2 p-2" onSubmit={(event) => {
              event.preventDefault()
              const value = new FormData(event.currentTarget).get("start")
              close()
              onAdd(clockMinutes(String(value)))
            }}>
              <label className="flex flex-col gap-1 text-xs">Hoy a las
                <input name="start" type="time" step={900} defaultValue={formatClock(suggested)} className="h-8 rounded-md border border-border bg-background px-2 text-sm [color-scheme:dark]" />
              </label>
              <Button type="submit" size="sm" className="w-full">Añadir bloque</Button>
            </form>
          )}
        </Popover>
      )}
    </div>
  )
}
