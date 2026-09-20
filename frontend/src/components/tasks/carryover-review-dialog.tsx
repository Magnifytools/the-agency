import { useState } from "react"
import axios from "axios"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { tasksApi } from "@/lib/api"
import type { Task } from "@/lib/types"
import { invalidateTaskChange, taskKeys } from "@/lib/query-keys"
import { getErrorMessage } from "@/lib/utils"
import { formatCivilDate } from "@/lib/dates"
import { useBusinessDate } from "@/hooks/use-business-date"
import { Button } from "@/components/ui/button"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

type Action = "reschedule" | "wait" | "complete" | "retire"

export function CarryoverReviewDialog({ task, open, onOpenChange }: {
  task: Task | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [action, setAction] = useState<Action>("reschedule")
  const [scheduledDate, setScheduledDate] = useState("")
  const [waitingFor, setWaitingFor] = useState("")
  const [followUpDate, setFollowUpDate] = useState("")
  const [reason, setReason] = useState("")
  const [latest, setLatest] = useState<Task | null>(null)
  const [mustReviewConflict, setMustReviewConflict] = useState(false)
  const [conflictDetail, setConflictDetail] = useState<string | null>(null)
  const businessToday = useBusinessDate()
  const current = latest ?? task

  const decision = useMutation({
    mutationFn: () => {
      if (!current) throw new Error("No se encontró la tarea")
      return tasksApi.carryoverDecision(current.id, {
        action,
        expected_updated_at: current.updated_at,
        ...(action === "reschedule" ? { scheduled_date: scheduledDate } : {}),
        ...(action === "wait" ? { waiting_for: waitingFor, follow_up_date: followUpDate } : {}),
        ...(action === "retire" ? { reason } : {}),
      })
    },
    onSuccess: async (updated) => {
      queryClient.setQueryData(taskKeys.detail(updated.id), updated)
      await invalidateTaskChange(queryClient, { projectId: updated.project_id, clientId: updated.client_id })
      toast.success(action === "complete" ? "Tarea completada" : "Cambio guardado")
      onOpenChange(false)
    },
    onError: async (error) => {
      if (axios.isAxiosError(error) && error.response?.status === 409 && task) {
        setConflictDetail(getErrorMessage(error, "La tarea cambió en otro sitio."))
        try {
          const fresh = await tasksApi.get(task.id)
          setLatest(fresh)
          queryClient.setQueryData(taskKeys.detail(fresh.id), fresh)
          await invalidateTaskChange(queryClient, { projectId: fresh.project_id, clientId: fresh.client_id })
          setMustReviewConflict(true)
        } catch {
          toast.error("La tarea cambió en otro sitio y no se pudo actualizar. Reintenta antes de decidir.")
        }
        return
      }
      toast.error(getErrorMessage(error, "No se pudo guardar la decisión. Puedes reintentarla."))
    },
  })

  const valid = action === "complete"
    || (action === "reschedule" && !!scheduledDate)
    || (action === "wait" && !!waitingFor.trim() && !!followUpDate)
    || (action === "retire" && !!reason.trim())

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader><DialogTitle>Revisar arrastre</DialogTitle></DialogHeader>
      {current && <div className="space-y-4">
        <p className="text-sm font-medium">{current.title}</p>
        {current.due_date && <p className="rounded-md border border-warning/30 bg-warning/5 p-3 text-sm text-muted-foreground">Fecha límite: {formatCivilDate(current.due_date.slice(0, 10), { day: "numeric", month: "long", year: "numeric" })}. Se conserva aunque reprogrames o dejes la tarea en espera.</p>}
        {mustReviewConflict && <div role="alert" className="rounded-md border border-warning/30 bg-warning/5 p-3 text-sm"><p>{conflictDetail ?? "Esta tarea cambió en otro sitio."} Tus datos siguen aquí; revisa la versión actual antes de volver a guardar.</p><Button className="mt-2" size="sm" variant="outline" onClick={() => setMustReviewConflict(false)}>Continuar con mi decisión</Button></div>}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {(["reschedule", "wait", "complete", "retire"] as Action[]).map((candidate) => <Button key={candidate} type="button" size="sm" variant={action === candidate ? "default" : "outline"} onClick={() => setAction(candidate)}>{({ reschedule: "Reprogramar", wait: "Esperar", complete: "Completar", retire: "Retirar" })[candidate]}</Button>)}
        </div>
        {action === "reschedule" && <div><Label htmlFor="carryover-date">Nueva fecha</Label><Input id="carryover-date" type="date" value={scheduledDate} onChange={(event) => setScheduledDate(event.target.value)} /><p className="mt-1 text-xs text-muted-foreground">Sólo cambia la planificación. Una fecha límite vencida puede mantener la tarea en Arrastre.</p></div>}
        {action === "wait" && <div className="space-y-3"><div><Label htmlFor="carryover-waiting">Esperando a</Label><Input id="carryover-waiting" maxLength={255} value={waitingFor} onChange={(event) => setWaitingFor(event.target.value)} /></div><div><Label htmlFor="carryover-follow-up">Revisar el</Label><Input id="carryover-follow-up" type="date" min={businessToday} value={followUpDate} onChange={(event) => setFollowUpDate(event.target.value)} /></div><p className="text-xs text-muted-foreground">La planificación se limpia, pero una fecha límite vencida sigue siendo una deuda visible.</p></div>}
        {action === "complete" && <p className="text-sm text-muted-foreground">Marcarás la tarea como completada. Podrás deshacer el cambio desde Cambios recientes.</p>}
        {action === "retire" && <div><Label htmlFor="carryover-reason">Motivo</Label><Textarea id="carryover-reason" maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} /><p className="mt-1 text-xs text-muted-foreground">La tarea se conserva en Retiradas y se puede restaurar.</p></div>}
        <div className="flex justify-end gap-2"><Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button><Button type="button" disabled={!valid || mustReviewConflict || decision.isPending} onClick={() => decision.mutate()}>{decision.isPending ? "Guardando…" : "Guardar decisión"}</Button></div>
      </div>}
    </Dialog>
  )
}
