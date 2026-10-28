import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { calendarApi } from "@/lib/api"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"

/** Publicar los bloques de trabajo de Mi agenda en el calendario "The Agency" de Google. */
export function CalendarBlocksPanel({ active }: { active: boolean }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const [deleteCalendar, setDeleteCalendar] = useState(true)

  const activateMut = useMutation({
    mutationFn: async () => {
      const { url } = await calendarApi.getBlocksAuthUrl()
      window.location.href = url
    },
    onError: () => toast.error("Error al obtener URL de autorización"),
  })

  const disableMut = useMutation({
    mutationFn: calendarApi.disableBlocks,
    onSuccess: (result, deleted) => {
      setConfirming(false)
      void queryClient.invalidateQueries({ queryKey: ["calendar-status"] })
      if (!deleted) toast.success("Bloques sin publicar. El calendario «The Agency» se queda en tu Google tal como estaba")
      else if (result.calendar_deleted) toast.success("Bloques sin publicar y calendario «The Agency» borrado de Google")
      else toast.warning("Bloques sin publicar, pero Google no borró el calendario «The Agency»: bórralo tú desde Google Calendar")
    },
    onError: () => toast.error("No se pudo dejar de publicar"),
  })

  return (
    <div className="rounded-xl border border-border p-4">
      <p className="text-sm font-medium text-foreground">Bloques de trabajo en Google Calendar</p>
      {active ? (
        <>
          <p className="mt-1 text-sm text-muted-foreground">
            Tus bloques de esta semana y las cuatro siguientes están en el calendario «The Agency». Lo que muevas o
            borres allí cambia aquí (borrar un bloque nunca borra la tarea), y al revés. Tarda hasta un minuto.
          </p>
          <button
            onClick={() => setConfirming(true)}
            className="mt-3 px-3 py-1.5 text-xs border border-border rounded-lg hover:bg-muted/50 transition-colors"
          >
            Dejar de publicar
          </button>
        </>
      ) : (
        <>
          <p className="mt-1 text-sm text-muted-foreground">
            Publica los bloques de Mi agenda en un calendario aparte, «The Agency», y muévelos desde Google o desde aquí.
            Google te pedirá un permiso más: sólo deja tocar ese calendario, nunca los tuyos.
          </p>
          <button
            onClick={() => activateMut.mutate()}
            disabled={activateMut.isPending}
            className="mt-3 px-3 py-1.5 text-xs font-semibold bg-brand text-black rounded-lg hover:bg-brand/90 transition-colors disabled:opacity-50"
          >
            {activateMut.isPending ? "Redirigiendo…" : "Publicar mis bloques"}
          </button>
        </>
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="¿Dejar de publicar tus bloques?"
        description="Los bloques se quedan en Mi agenda; sólo dejan de copiarse a Google."
        confirmLabel="Dejar de publicar"
        onConfirm={() => disableMut.mutate(deleteCalendar)}
      >
        <BlocksCalendarCheckbox checked={deleteCalendar} onChange={setDeleteCalendar} />
      </ConfirmDialog>
    </div>
  )
}

export function BlocksCalendarCheckbox({ checked, onChange }: { checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="mb-4 flex items-start gap-2 text-sm">
      <input type="checkbox" className="mt-0.5" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>
        Borrar también el calendario «The Agency» de Google
        <span className="block text-xs text-muted-foreground">
          Si no, se queda en tu Google con los bloques que tenía, pero ya no se actualiza.
        </span>
      </span>
    </label>
  )
}
