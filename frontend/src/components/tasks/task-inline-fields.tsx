import { useState, type ReactNode } from "react"
import { Pencil } from "lucide-react"
import type { Task, TaskPriority, User } from "@/lib/types"
import { Badge } from "@/components/ui/badge"
import { InlineDate, InlineMinutes, InlineSelect, InlineTextInput } from "@/components/ui/inline-edit"
import type { TaskQuickUpdate } from "@/hooks/use-task-quick-update"
import { formatCivilDate } from "@/lib/dates"
import { formatMinutes } from "@/lib/inline-edit"
import { cn } from "@/lib/utils"

/** Lo que cada celda manda al guardar; la tarea la pone quien la pinta. */
export type TaskFieldUpdate = (update: Omit<TaskQuickUpdate, "task">) => void

const PRIORITIES: Record<TaskPriority, { label: string; variant: "destructive" | "warning" | "secondary" | "outline" }> = {
  urgent: { label: "Urgente", variant: "destructive" },
  high: { label: "Alta", variant: "warning" },
  medium: { label: "Media", variant: "secondary" },
  low: { label: "Baja", variant: "outline" },
}

export function TaskPriorityBadge({ priority, className }: { priority: TaskPriority; className?: string }) {
  const { label, variant } = PRIORITIES[priority] ?? { label: priority, variant: "secondary" as const }
  return <Badge variant={variant} dot={false} className={className}>{label}</Badge>
}

interface FieldProps {
  task: Task
  canWrite: boolean
  onUpdate: TaskFieldUpdate
}

export function TaskPriorityField({ task, canWrite, onUpdate, className }: FieldProps & { className?: string }) {
  return (
    <InlineSelect
      label={`Prioridad de ${task.title}`}
      valueText={PRIORITIES[task.priority]?.label ?? task.priority}
      disabled={!canWrite}
      value={task.priority}
      options={(Object.keys(PRIORITIES) as TaskPriority[]).map((priority) => ({
        value: priority,
        label: PRIORITIES[priority].label,
        content: <TaskPriorityBadge priority={priority} className={className} />,
      }))}
      onChange={(priority) => onUpdate({ data: { priority }, success: `Prioridad: ${PRIORITIES[priority].label}` })}
    >
      <TaskPriorityBadge priority={task.priority} className={className} />
    </InlineSelect>
  )
}

export function TaskAssigneeField({ task, canWrite, onUpdate, users, emptyText = "-" }: FieldProps & { users: User[]; emptyText?: string }) {
  const options = users.filter((user) => user.is_active || user.id === task.assigned_to)
  return (
    <InlineSelect<number | null>
      label={`Responsable de ${task.title}`}
      valueText={task.assigned_user_name ?? "Sin asignar"}
      disabled={!canWrite}
      value={task.assigned_to}
      options={[
        { value: null, label: "Sin asignar" },
        ...options.map((user) => ({ value: user.id, label: user.full_name })),
      ]}
      onChange={(assigned_to) => {
        const name = options.find((user) => user.id === assigned_to)?.full_name ?? null
        onUpdate({
          data: { assigned_to },
          display: { assigned_user_name: name },
          success: name ? `Responsable: ${name}` : "Sin responsable",
        })
      }}
    >
      {task.assigned_user_name ?? <span className="text-muted-foreground">{emptyText}</span>}
    </InlineSelect>
  )
}

const shortDate = (date: string) => formatCivilDate(date, { day: "numeric", month: "short" })

export function TaskDateField({ task, canWrite, onUpdate, field, today, emptyText = "-", className }: FieldProps & {
  field: "due_date" | "scheduled_date"
  today: string
  emptyText?: string
  className?: string
}) {
  const value = task[field]?.slice(0, 10) ?? null
  const name = field === "due_date" ? "Fecha límite" : "Planificada"
  return (
    <InlineDate
      label={`${name} de ${task.title}`}
      valueText={value ? formatCivilDate(value) : "sin fecha"}
      disabled={!canWrite}
      value={value}
      today={today}
      clearLabel={field === "due_date" ? "Sin fecha límite" : "Sin planificar"}
      onChange={(date) => onUpdate({
        data: field === "due_date" ? { due_date: date } : { scheduled_date: date },
        success: date ? `${name}: ${shortDate(date)}` : field === "due_date" ? "Sin fecha límite" : "Sin planificar",
      })}
      className={className}
    >
      {value ? formatCivilDate(value, value.slice(0, 4) === today.slice(0, 4)
        ? { day: "numeric", month: "short" }
        : { day: "numeric", month: "short", year: "numeric" }) : <span className="text-muted-foreground">{emptyText}</span>}
    </InlineDate>
  )
}

export function TaskEstimateField({ task, canWrite, onUpdate }: FieldProps) {
  return (
    <InlineMinutes
      label={`Estimación de ${task.title}`}
      valueText={task.estimated_minutes ? formatMinutes(task.estimated_minutes) : "sin estimar"}
      disabled={!canWrite}
      value={task.estimated_minutes}
      onChange={(estimated_minutes) => onUpdate({
        data: { estimated_minutes },
        success: estimated_minutes ? `Estimación: ${formatMinutes(estimated_minutes)}` : "Sin estimación",
      })}
    >
      {task.estimated_minutes ? formatMinutes(task.estimated_minutes) : <span className="text-muted-foreground">-</span>}
    </InlineMinutes>
  )
}

/** Título que abre la tarea y, al lado, un lápiz para cambiarlo sin abrirla. */
export function TaskTitleField({ task, canWrite, onUpdate, onOpen, children }: FieldProps & { onOpen: () => void; children?: ReactNode }) {
  const [editing, setEditing] = useState(false)
  if (editing) {
    return (
      <InlineTextInput
        label={`Título de ${task.title}`}
        value={task.title}
        maxLength={255}
        onSubmit={(title) => { setEditing(false); onUpdate({ data: { title }, success: "Título cambiado" }) }}
        onCancel={() => setEditing(false)}
      />
    )
  }
  return (
    <span className="group/title inline-flex items-start gap-1">
      <button type="button" onClick={onOpen} className="inline-flex items-center gap-1 text-left hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded-sm">
        {children}
        {task.title}
      </button>
      {canWrite && (
        <button
          type="button"
          aria-label={`Cambiar título de ${task.title}`}
          title="Cambiar título"
          onClick={() => setEditing(true)}
          className={cn("mt-0.5 shrink-0 rounded-sm p-0.5 text-muted-foreground transition-opacity duration-150 hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand",
            "sm:opacity-0 sm:group-hover/title:opacity-100")}
        >
          <Pencil className="h-3 w-3" aria-hidden />
        </button>
      )}
    </span>
  )
}
