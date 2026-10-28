import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { TIMER_CAP_SECONDS } from "@/lib/timer"

function hoursAndMinutes(seconds: number) {
  const minutes = Math.floor(seconds / 60)
  return { hours: Math.floor(minutes / 60), minutes: minutes % 60 }
}

/**
 * Parar un cronómetro que lleva muchas horas: ¿fue de verdad o se quedó
 * encendido? Sin corregir se guarda lo contado, recortado a 8 h.
 */
export function LongTimerDialog({ seconds, pending, onStop, onCancel }: {
  seconds: number
  pending: boolean
  onStop: (minutes?: number) => void
  onCancel: () => void
}) {
  const counted = hoursAndMinutes(seconds)
  const initial = hoursAndMinutes(Math.min(seconds, TIMER_CAP_SECONDS))
  const [hours, setHours] = useState(String(initial.hours))
  const [minutes, setMinutes] = useState(String(initial.minutes))
  const total = (Number(hours) || 0) * 60 + (Number(minutes) || 0)
  const valid = Number.isInteger(total) && total >= 1 && total <= 720
  const capped = seconds > TIMER_CAP_SECONDS

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onCancel() }}>
      <DialogHeader>
        <DialogTitle>¿Se quedó encendido?</DialogTitle>
      </DialogHeader>
      <DialogContent>
        <div className="space-y-3 text-sm">
          <p>
            El cronómetro lleva <strong>{counted.hours} h {counted.minutes} min</strong>.
            {capped ? " Si lo paras sin más se guardan 8 h." : ""} Si no trabajaste todo ese tiempo, escribe lo que fue de verdad.
          </p>
          <div className="flex items-end gap-2">
            <div className="w-24 space-y-1">
              <Label htmlFor="long-timer-hours">Horas</Label>
              <Input id="long-timer-hours" type="number" min="0" max="12" value={hours} onChange={(e) => setHours(e.target.value)} />
            </div>
            <div className="w-24 space-y-1">
              <Label htmlFor="long-timer-minutes">Minutos</Label>
              <Input id="long-timer-minutes" type="number" min="0" max="59" value={minutes} onChange={(e) => setMinutes(e.target.value)} />
            </div>
          </div>
          {!valid && <p role="alert" className="text-destructive">Entre 1 minuto y 12 horas.</p>}
        </div>
      </DialogContent>
      <DialogFooter>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={pending}>Seguir con él</Button>
        <Button type="button" variant="outline" onClick={() => onStop()} disabled={pending}>
          Guardar lo contado{capped ? " (8 h)" : ""}
        </Button>
        <Button type="button" onClick={() => onStop(total)} disabled={pending || !valid}>
          Guardar {Math.floor(total / 60)} h {total % 60} min
        </Button>
      </DialogFooter>
    </Dialog>
  )
}
