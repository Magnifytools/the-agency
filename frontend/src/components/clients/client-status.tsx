import { Badge } from "@/components/ui/badge"
import type { ClientStatusLevel, ClientStatusRow } from "@/lib/types"

const LEVEL: Record<ClientStatusLevel, { label: string; variant: "success" | "warning" | "destructive" | "secondary" }> = {
  act: { label: "Actuar", variant: "destructive" },
  watch: { label: "Vigilar", variant: "warning" },
  ok: { label: "Bien", variant: "success" },
  no_data: { label: "Sin datos", variant: "secondary" },
}

export function ClientStatusBadge({ status }: { status: ClientStatusLevel }) {
  const level = LEVEL[status]
  return <Badge variant={level.variant}>{level.label}</Badge>
}

/** Motivos del estado. Sin motivos: frase de por qué está bien o sin datos. */
export function ClientStatusReasons({ row, limit }: { row: ClientStatusRow; limit?: number }) {
  if (row.status === "no_data") return <p className="text-xs text-muted-foreground">Sin señales que medir: falta propiedad de Search Console, política de resumen o tareas.</p>
  if (row.reasons.length === 0) return <p className="text-xs text-muted-foreground">Ninguna señal preocupa.</p>
  const shown = limit ? row.reasons.slice(0, limit) : row.reasons
  return (
    <ul className="space-y-0.5 text-xs">
      {shown.map((reason) => <li key={reason}>{reason}</li>)}
      {limit && row.reasons.length > limit && <li className="text-muted-foreground">y {row.reasons.length - limit} más</li>}
    </ul>
  )
}

const pct = (value: number) => `${value > 0 ? "+" : ""}${value.toLocaleString("es-ES", { maximumFractionDigits: 1 })} %`

export function SeoCell({ seo }: { seo: ClientStatusRow["seo"] }) {
  if (!seo) return <span className="text-xs text-muted-foreground">Sin datos</span>
  const color = seo.trend === "drop_alert" ? "text-red-600 dark:text-red-400"
    : seo.trend === "down" ? "text-amber-600 dark:text-amber-400"
    : seo.trend === "up" ? "text-green-700 dark:text-green-400" : "text-muted-foreground"
  return (
    <div className="text-xs">
      <span className="mono">{seo.clicks.toLocaleString("es-ES")}</span> clics
      {seo.change_pct != null && <span className={`ml-1 font-medium ${color}`}>{pct(seo.change_pct)}</span>}
      <p className="text-muted-foreground">{seo.source === "search_console" ? "Search Console · 28 días" : "The Engine · 30 días"}</p>
    </div>
  )
}

const DIGEST_STATE = { ok: "Al día", due: "Toca enviarlo", late: "Atrasado" } as const

const CADENCE = { monthly: "Informe mensual", weekly: "Seguimiento semanal" } as const

/** Una línea por cadencia encendida (informe mensual y/o seguimiento semanal). */
export function DigestCell({ digests }: { digests: ClientStatusRow["digests"] | null | undefined }) {
  if (!digests?.length) return <p className="text-xs text-muted-foreground">Sin política</p>
  return (
    <div className="space-y-1 text-xs">
      {digests.map(digest => {
        const last = digest.last_sent_period_end
          ? new Date(`${digest.last_sent_period_end}T12:00:00`).toLocaleDateString("es-ES", { day: "numeric", month: "short" })
          : null
        return (
          <div key={digest.cadence}>
            <span className={digest.state === "late" ? "font-medium text-red-600 dark:text-red-400" : digest.state === "due" ? "font-medium text-amber-600 dark:text-amber-400" : ""}>
              {CADENCE[digest.cadence]} · {DIGEST_STATE[digest.state]}
            </span>
            <p className="text-muted-foreground">{last ? `Último entregado hasta ${last}` : "Nunca entregado"}</p>
          </div>
        )
      })}
    </div>
  )
}

export function WorkCell({ tasks, month }: Pick<ClientStatusRow, "tasks" | "month">) {
  if (!tasks && !month) return <span className="text-xs text-muted-foreground">—</span>
  return (
    <div className="space-y-0.5 text-xs">
      {tasks && <p>{tasks.overdue ? <span className="font-medium text-red-600 dark:text-red-400">{tasks.overdue} vencidas</span> : "0 vencidas"}{tasks.waiting ? ` · ${tasks.waiting} en espera` : ""}</p>}
      {month && <p className="text-muted-foreground"><span className="mono">{month.hours.toLocaleString("es-ES")}</span> h este mes{month.consumption_pct != null ? ` · ${month.consumption_pct.toLocaleString("es-ES")} % de la cuota` : ""}</p>}
    </div>
  )
}
