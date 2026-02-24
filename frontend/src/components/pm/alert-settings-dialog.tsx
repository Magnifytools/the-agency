import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Settings } from "lucide-react"
import { toast } from "sonner"
import { pmApi } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useState } from "react"
import { getErrorMessage } from "@/lib/utils"

export function AlertSettingsDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()

  const { data: settings, isLoading } = useQuery({
    queryKey: ["alert-settings"],
    queryFn: () => pmApi.alertSettings(),
    enabled: open,
  })

  const mutation = useMutation({
    mutationFn: pmApi.updateAlertSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alert-settings"] })
      toast.success("Configuración guardada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al guardar")),
  })

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const formData = new FormData(e.currentTarget)
    mutation.mutate({
      days_without_activity: Number(formData.get("days_without_activity")),
      days_before_deadline: Number(formData.get("days_before_deadline")),
      days_without_contact: Number(formData.get("days_without_contact")),
      max_tasks_per_week: Number(formData.get("max_tasks_per_week")),
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Configurar alertas</DialogTitle>
      </DialogHeader>

      {isLoading ? (
        <div className="py-8 text-center text-muted-foreground">Cargando...</div>
      ) : settings ? (
        <form onSubmit={handleSubmit} className="space-y-4 mt-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="days_without_activity">
                Días sin actividad (cliente estancado)
              </Label>
              <Input
                id="days_without_activity"
                name="days_without_activity"
                type="number"
                min="1"
                max="90"
                defaultValue={settings.days_without_activity}
              />
              <p className="text-xs text-muted-foreground">
                Alerta si un cliente no tiene movimiento en X días
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="days_before_deadline">
                Días antes de vencimiento
              </Label>
              <Input
                id="days_before_deadline"
                name="days_before_deadline"
                type="number"
                min="1"
                max="14"
                defaultValue={settings.days_before_deadline}
              />
              <p className="text-xs text-muted-foreground">
                Aviso de tareas próximas a vencer
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="days_without_contact">
                Días sin contacto
              </Label>
              <Input
                id="days_without_contact"
                name="days_without_contact"
                type="number"
                min="1"
                max="60"
                defaultValue={settings.days_without_contact}
              />
              <p className="text-xs text-muted-foreground">
                Alerta si no has contactado con el cliente
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="max_tasks_per_week">
                Máximo tareas/semana
              </Label>
              <Input
                id="max_tasks_per_week"
                name="max_tasks_per_week"
                type="number"
                min="1"
                max="50"
                defaultValue={settings.max_tasks_per_week}
              />
              <p className="text-xs text-muted-foreground">
                Alerta de carga de trabajo alta
              </p>
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              Guardar
            </Button>
          </div>
        </form>
      ) : null}
    </Dialog>
  )
}

export function AlertSettingsButton() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)} title="Configurar alertas">
        <Settings className="h-4 w-4" />
      </Button>
      <AlertSettingsDialog open={open} onOpenChange={setOpen} />
    </>
  )
}
