import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ListChecks } from "lucide-react"
import { tasksApi } from "@/lib/api"
import { taskKeys } from "@/lib/query-keys"
import { formatCivilDate } from "@/lib/dates"
import { getErrorMessage, cn } from "@/lib/utils"
import { Card, CardContent } from "@/components/ui/card"

/**
 * Mi agenda: las subtareas que me tocan en tareas que lleva otra persona. Sin
 * esto, quien tiene un paso asignado no se entera hasta que abre la tarea.
 * Se ocultan si no hay ninguna.
 */
export function AgendaSubtasks({ today, userId, canWrite, onOpenTask }: {
  today: string
  userId: number | undefined
  canWrite: boolean
  onOpenTask: (taskId: number) => void
}) {
  const queryClient = useQueryClient()
  const { data: items = [] } = useQuery({
    queryKey: taskKeys.subtasks(today, userId),
    queryFn: () => tasksApi.agendaSubtasks(today),
    enabled: userId !== undefined,
  })
  const done = useMutation({
    mutationFn: ({ taskId, itemId }: { taskId: number; itemId: number }) =>
      tasksApi.checklist.update(taskId, itemId, { is_done: true }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: taskKeys.subtasks() })
      toast.success("Subtarea hecha")
    },
    onError: (error) => toast.error(getErrorMessage(error, "No se pudo marcar la subtarea")),
  })

  if (items.length === 0) return null
  return (
    <Card>
      <CardContent className="p-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <ListChecks className="h-4 w-4" /> Subtareas que te tocan
          <span className="text-muted-foreground font-normal">({items.length})</span>
        </h2>
        <ul className="mt-2 divide-y divide-border">
          {items.map((item) => {
            const overdue = !!item.due_date && item.due_date < today
            return (
              <li key={item.id} className="flex items-start gap-3 py-2">
                {canWrite && (
                  <input
                    type="checkbox"
                    className="mt-1"
                    aria-label={`Marcar como hecha: ${item.text}`}
                    disabled={done.isPending}
                    onChange={() => done.mutate({ taskId: item.task_id, itemId: item.id })}
                  />
                )}
                <div className="min-w-0 flex-1">
                  <p className="text-sm">{item.text}</p>
                  <button
                    type="button"
                    className="text-left text-xs text-muted-foreground hover:underline"
                    onClick={() => onOpenTask(item.task_id)}
                  >
                    En «{item.task_title}»
                    {item.client_name ? ` · ${item.client_name}` : ""}
                    {item.task_assignee_name ? ` · la lleva ${item.task_assignee_name}` : ""}
                  </button>
                </div>
                {item.due_date && (
                  <span className={cn("shrink-0 text-xs", overdue ? "text-destructive font-medium" : "text-muted-foreground")}>
                    {item.due_date === today ? "Hoy" : formatCivilDate(item.due_date, { day: "numeric", month: "short" })}
                  </span>
                )}
              </li>
            )
          })}
        </ul>
      </CardContent>
    </Card>
  )
}
