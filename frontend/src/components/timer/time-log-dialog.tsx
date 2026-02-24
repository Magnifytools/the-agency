import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { timeEntriesApi } from "@/lib/api"
import type { TimeEntry } from "@/lib/types"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Trash2 } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

interface TimeLogDialogProps {
  taskId: number
  taskTitle: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

function formatMinutes(m: number): string {
  const h = Math.floor(m / 60)
  const mins = m % 60
  if (h && mins) return `${h}h ${mins}m`
  if (h) return `${h}h`
  return `${mins}m`
}

export function TimeLogDialog({ taskId, taskTitle, open, onOpenChange }: TimeLogDialogProps) {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)

  const { data: entries = [] } = useQuery({
    queryKey: ["time-entries", taskId],
    queryFn: () => timeEntriesApi.list({ task_id: taskId }),
    enabled: open,
  })

  const createMutation = useMutation({
    mutationFn: (data: { minutes: number; task_id: number; notes?: string }) =>
      timeEntriesApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["time-entries", taskId] })
      setShowForm(false)
      toast.success("Entrada de tiempo creada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear entrada")),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => timeEntriesApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["time-entries", taskId] })
      toast.success("Entrada eliminada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar entrada")),
  })

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    const hours = Number(fd.get("hours") || 0)
    const mins = Number(fd.get("mins") || 0)
    const totalMinutes = hours * 60 + mins
    if (totalMinutes <= 0) return
    createMutation.mutate({
      minutes: totalMinutes,
      task_id: taskId,
      notes: (fd.get("notes") as string) || undefined,
    })
  }

  const totalMinutes = entries.reduce((sum: number, e: TimeEntry) => sum + (e.minutes || 0), 0)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Registro de tiempo — {taskTitle}</DialogTitle>
      </DialogHeader>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            Total: <span className="font-bold text-brand mono">{formatMinutes(totalMinutes)}</span>
          </p>
          <Button size="sm" onClick={() => setShowForm(!showForm)}>
            {showForm ? "Cancelar" : "Añadir manual"}
          </Button>
        </div>

        {showForm && (
          <form onSubmit={handleSubmit} className="border border-brand/20 p-3 space-y-3">
            <div className="flex gap-3">
              <div className="space-y-1">
                <Label htmlFor="hours">Horas</Label>
                <Input id="hours" name="hours" type="number" min="0" placeholder="0" className="w-20" />
              </div>
              <div className="space-y-1">
                <Label htmlFor="mins">Minutos</Label>
                <Input id="mins" name="mins" type="number" min="0" max="59" placeholder="0" className="w-20" />
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="notes">Notas</Label>
              <Textarea id="notes" name="notes" rows={2} />
            </div>
            <Button type="submit" size="sm">Guardar</Button>
          </form>
        )}

        {entries.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Fecha</TableHead>
                <TableHead>Duración</TableHead>
                <TableHead>Notas</TableHead>
                <TableHead className="w-12"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.map((e: TimeEntry) => (
                <TableRow key={e.id}>
                  <TableCell className="mono">{new Date(e.date).toLocaleDateString("es-ES")}</TableCell>
                  <TableCell className="mono">{e.minutes ? formatMinutes(e.minutes) : "-"}</TableCell>
                  <TableCell className="max-w-[200px] truncate">{e.notes || "-"}</TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => deleteMutation.mutate(e.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="text-sm text-muted-foreground text-center py-4">
            No hay entradas de tiempo
          </p>
        )}
      </div>
    </Dialog>
  )
}
