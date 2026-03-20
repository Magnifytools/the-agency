import { useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { useAuth } from "@/context/auth-context"
import { usersApi } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

const REGIONES = [
  "MAD", "CAT", "AND", "VAL", "GAL", "PV", "CYL", "CLM",
  "ARA", "EXT", "MUR", "NAV", "AST", "CAN", "BAL", "RIO", "CANT", "CEU", "MEL",
] as const

export function OnboardingModal() {
  const { user, refreshUser } = useAuth()

  const [form, setForm] = useState({
    short_name: "",
    full_name: user?.full_name ?? "",
    job_title: "",
    birthday: "",
    locality: user?.locality ?? "",
    region: "",
    morning_reminder_time: "09:00",
    evening_reminder_time: "18:00",
  })

  const mutation = useMutation({
    mutationFn: (data: typeof form & { onboarding_completed: boolean }) =>
      usersApi.update(user!.id, data),
    onSuccess: async () => {
      toast.success("Perfil completado")
      await refreshUser()
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al guardar perfil")),
  })

  if (!user || user.onboarding_completed !== false) return null

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    mutation.mutate({ ...form, onboarding_completed: true })
  }

  const update = (field: keyof typeof form, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
        className="relative z-50 w-full max-w-lg max-h-[90vh] md:max-h-[85vh] overflow-y-auto rounded-[16px] border border-border bg-card p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex flex-col space-y-1.5 text-center sm:text-left mb-6">
          <h2 id="onboarding-title" className="text-lg font-semibold leading-none tracking-tight text-foreground">
            Completa tu perfil
          </h2>
          <p className="text-sm text-muted-foreground">
            Necesitamos algunos datos para personalizar tu experiencia
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="ob_short_name">Nombre corto</Label>
              <Input
                id="ob_short_name"
                required
                placeholder="David"
                value={form.short_name}
                onChange={(e) => update("short_name", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ob_full_name">Nombre completo</Label>
              <Input
                id="ob_full_name"
                required
                value={form.full_name}
                onChange={(e) => update("full_name", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ob_job_title">Puesto</Label>
              <Input
                id="ob_job_title"
                placeholder="SEO Strategist"
                value={form.job_title}
                onChange={(e) => update("job_title", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ob_birthday">Cumpleanos</Label>
              <Input
                id="ob_birthday"
                type="date"
                value={form.birthday}
                onChange={(e) => update("birthday", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ob_locality">Ciudad</Label>
              <Input
                id="ob_locality"
                placeholder="Madrid"
                value={form.locality}
                onChange={(e) => update("locality", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ob_region">Comunidad Autonoma</Label>
              <Select
                id="ob_region"
                value={form.region}
                onChange={(e: React.ChangeEvent<HTMLSelectElement>) => update("region", e.target.value)}
              >
                <option value="">Seleccionar...</option>
                {REGIONES.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="ob_morning">Reminder manana</Label>
              <Input
                id="ob_morning"
                type="time"
                value={form.morning_reminder_time}
                onChange={(e) => update("morning_reminder_time", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ob_evening">Recap noche</Label>
              <Input
                id="ob_evening"
                type="time"
                value={form.evening_reminder_time}
                onChange={(e) => update("evening_reminder_time", e.target.value)}
              />
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? "Guardando..." : "Guardar y continuar"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
