import type { ReactNode } from "react"
import { useDroppable, type DraggableAttributes, type DraggableSyntheticListeners } from "@dnd-kit/core"
import { useSortable } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { GripVertical } from "lucide-react"
import type { Task } from "@/lib/types"
import { cn } from "@/lib/utils"
import { formatCivilDate } from "@/lib/dates"

export type AgendaSection = "planned" | "carryover" | "unplanned"
export type AgendaDropData = { task?: Task; section?: AgendaSection; day?: string }

export interface DragHandleProps {
  setActivator: (element: HTMLElement | null) => void
  attributes: DraggableAttributes
  listeners: DraggableSyntheticListeners
}

/** Tarjeta de Mi agenda que se ordena arrastrando su asa. */
export function SortableAgendaItem({ task, section, disabled, children }: {
  task: Task
  section: AgendaSection
  disabled: boolean
  children: (handle: DragHandleProps | null) => ReactNode
}) {
  const { setNodeRef, setActivatorNodeRef, attributes, listeners, transform, transition, isDragging } = useSortable({
    id: task.id,
    data: { task, section } satisfies AgendaDropData,
    disabled,
  })
  return (
    <div ref={setNodeRef} style={{ transform: CSS.Translate.toString(transform), transition }} className={cn(isDragging && "opacity-40")}>
      {children(disabled ? null : { setActivator: setActivatorNodeRef, attributes, listeners })}
    </div>
  )
}

export function DragHandle({ handle: { setActivator, attributes, listeners }, title }: { handle: DragHandleProps; title: string }) {
  return (
    <button
      ref={setActivator}
      type="button"
      {...attributes}
      {...listeners}
      aria-label={`Mover ${title}`}
      title="Arrastra para ordenar o llevar a otro día"
      onClick={(event) => event.stopPropagation()}
      className="-ml-1 shrink-0 cursor-grab touch-none rounded-sm p-1.5 sm:p-0.5 text-muted-foreground/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand active:cursor-grabbing"
    >
      <GripVertical className="h-4 w-4" aria-hidden />
    </button>
  )
}

/** Hueco de una sección donde se puede soltar aunque esté vacía. */
export function AgendaDropZone({ section, children }: { section: AgendaSection; children: ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: `section-${section}`, data: { section } satisfies AgendaDropData })
  return (
    <div ref={setNodeRef} className={cn("rounded-lg transition-shadow", isOver && "ring-2 ring-brand ring-offset-2 ring-offset-background")}>
      {children}
    </div>
  )
}

function DayTarget({ day, label }: { day: string; label: string }) {
  const { setNodeRef, isOver } = useDroppable({ id: `day-${day}`, data: { day } satisfies AgendaDropData })
  return (
    <div
      ref={setNodeRef}
      className={cn(
        "flex-1 rounded-lg border-2 border-dashed px-3 py-2 text-center text-xs font-medium transition-colors",
        isOver ? "border-brand bg-brand/10 text-brand" : "border-border text-muted-foreground",
      )}
    >
      {label}
    </div>
  )
}

/** Mientras se arrastra (fija abajo, para no mover la lista): soltar en un día la planifica entonces. */
export function DayStrip({ days, tomorrow }: { days: string[]; tomorrow: string }) {
  return (
    <div role="group" aria-label="Llevar a otro día" className="fixed bottom-4 left-1/2 z-40 w-[min(40rem,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border border-border bg-card/95 p-2 shadow-2xl backdrop-blur">
      <p className="mb-1.5 px-1 text-[11px] text-muted-foreground">Suelta en un día para planificarla entonces</p>
      <div className="flex gap-2 overflow-x-auto">
        {days.map((day) => (
          <DayTarget key={day} day={day} label={day === tomorrow ? "Mañana" : formatCivilDate(day, { weekday: "short", day: "numeric" })} />
        ))}
      </div>
    </div>
  )
}
