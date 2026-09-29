import type { ProjectTaskItem } from "@/lib/project-work"
import { plannedDate, projectWork } from "@/lib/project-work"
import { formatCivilDate } from "@/lib/dates"
import { Button } from "@/components/ui/button"

interface Props {
  tasks: ProjectTaskItem[]
  today: string
  canWrite: boolean
  onOpen: (id: number) => void
  onAdd: () => void
}

export function ProjectWorkSummary({ tasks, today, canWrite, onOpen, onAdd }: Props) {
  const { next, waiting, unplanned } = projectWork(tasks)
  return <section aria-label="Seguimiento del proyecto" className="space-y-4 rounded-xl border border-border p-4">
    <div>
      <h2 className="font-semibold">Próxima acción planificada</h2>
      {next ? <button type="button" onClick={() => onOpen(next.id)} className="mt-2 w-full text-left rounded-lg py-2 focus-visible:ring-2 focus-visible:ring-brand">
        <span className="block text-sm font-medium break-words">{next.title}</span>
        <span className="block text-xs text-muted-foreground mt-1">
          {next.assigned_user_name || "Sin responsable"} · {formatCivilDate(plannedDate(next)!)}
          {plannedDate(next)! < today ? " · Atrasada: revisar planificación" : plannedDate(next) === today ? " · Hoy" : ""}
        </span>
      </button> : <div className="mt-2 space-y-2">
        <p className="text-sm text-muted-foreground">No hay una próxima acción planificada.{unplanned > 0 ? ` Hay ${unplanned} ${unplanned === 1 ? "tarea sin planificar" : "tareas sin planificar"}. ${canWrite ? "Abre una del listado para concretar el siguiente paso." : "Puedes consultar su detalle en la lista."}` : ""}</p>
        {canWrite && <Button variant="outline" onClick={onAdd}>Añadir una acción</Button>}
      </div>}
    </div>
    {waiting.length > 0 && <details>
      <summary className="cursor-pointer min-h-10 py-2 text-sm font-medium">En espera ({waiting.length}) · {waiting.filter(task => task.follow_up_date && task.follow_up_date <= today).length} por revisar</summary>
      <ul className="space-y-1">
        {waiting.map(task => <li key={task.id}>
          <button type="button" onClick={() => onOpen(task.id)} className="w-full rounded-lg py-2 text-left focus-visible:ring-2 focus-visible:ring-brand">
            <span className="block text-sm break-words">{task.title}</span>
            <span className="block text-xs text-muted-foreground">{task.waiting_for ? `Esperando a ${task.waiting_for}` : "Falta indicar qué se espera"} · {task.follow_up_date ? `Revisar ${formatCivilDate(task.follow_up_date)}${task.follow_up_date <= today ? " · Pendiente de revisión" : ""}` : "Sin fecha de revisión"}</span>
          </button>
        </li>)}
      </ul>
    </details>}
  </section>
}
