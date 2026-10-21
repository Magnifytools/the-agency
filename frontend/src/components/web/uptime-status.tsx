import { Badge } from "@/components/ui/badge"
import { getAgencyTimezone, parseApiInstant } from "@/lib/dates"
import type { UptimeStatus } from "@/lib/types"

type Variant = "success" | "destructive" | "warning" | "secondary" | "outline"

/** Un bloqueo NO es una caída: la web responde, pero no a nosotros. */
const STATUS: Record<UptimeStatus, { label: string; variant: Variant; hint: string }> = {
  up: { label: "Responde", variant: "success", hint: "La última comprobación fue buena." },
  suspect: { label: "Fallando", variant: "warning", hint: "Ha fallado una vez; se vuelve a mirar en un minuto antes de avisar." },
  down: { label: "Caída", variant: "destructive", hint: "No responde en dos comprobaciones seguidas." },
  blocked: { label: "Bloqueada", variant: "warning", hint: "Responde con 401/403/429 o un desafío anti-bots: no sabemos si está arriba." },
  unknown: { label: "Sin comprobar", variant: "secondary", hint: "Todavía no se ha mirado." },
  paused: { label: "Pausada", variant: "outline", hint: "No se comprueba." },
}

export function UptimeStatusPill({ status }: { status: UptimeStatus | null }) {
  if (!status) return <Badge variant="secondary" dot={false}>Sin URLs</Badge>
  const { label, variant, hint } = STATUS[status]
  return <Badge variant={variant} title={hint}>{label}</Badge>
}

export function formatInstant(value: string | null) {
  if (!value) return "—"
  return parseApiInstant(value).toLocaleString("es-ES", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: getAgencyTimezone(),
  })
}

export function formatPct(value: number | null) {
  if (value === null || value === undefined) return "—"
  return `${value.toLocaleString("es-ES", { maximumFractionDigits: 2 })} %`
}

export function formatMinutes(minutes: number) {
  if (minutes < 60) return `${Math.max(1, minutes)} min`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return minutes % 60 ? `${hours} h ${minutes % 60} min` : `${hours} h`
  const days = Math.floor(hours / 24)
  return hours % 24 ? `${days} d ${hours % 24} h` : `${days} d`
}
