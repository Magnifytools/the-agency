import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { leadsApi } from "@/lib/api"
import { Card, CardContent } from "@/components/ui/card"
import { Select } from "@/components/ui/select"

const PERIODS = [
  { days: 90, label: "Últimos 3 meses" },
  { days: 180, label: "Últimos 6 meses" },
  { days: 365, label: "Último año" },
] as const

const pct = (value: number | null) => (value === null ? "—" : `${value.toLocaleString("es-ES")} %`)
const days = (value: number | null) => (value === null ? "—" : `${value.toLocaleString("es-ES")} d`)

/**
 * Embudo del Pipeline: de los leads creados en el periodo, cuántos llegan a
 * cada etapa, qué parte pasa a la siguiente y cuántos días se quedan en ella.
 * Sale del historial de etapas (`lead_status_history`).
 */
export function LeadFunnelCard() {
  const [period, setPeriod] = useState<number>(180)
  const { data } = useQuery({ queryKey: ["lead-funnel", period], queryFn: () => leadsApi.funnel(period) })
  if (!data) return null
  const top = Math.max(1, data.stages[0]?.reached ?? 1)

  return (
    <Card>
      <CardContent className="p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold">Embudo</h2>
            <p className="text-xs text-muted-foreground">
              {data.total} {data.total === 1 ? "lead creado" : "leads creados"} · {data.won} ganados · {data.lost} perdidos · tasa de cierre {pct(data.win_rate_pct)}
            </p>
          </div>
          <Select aria-label="Periodo del embudo" value={period} onChange={(e) => setPeriod(Number(e.target.value))} className="w-[170px]">
            {PERIODS.map((p) => <option key={p.days} value={p.days}>{p.label}</option>)}
          </Select>
        </div>
        {data.total === 0 ? (
          <p className="text-sm text-muted-foreground">Aún no hay leads en este periodo.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th className="py-1 text-left font-medium">Etapa</th>
                  <th className="py-1 text-left font-medium">Llegan</th>
                  <th className="py-1 text-right font-medium">Pasan a la siguiente</th>
                  <th className="py-1 text-right font-medium">Días en la etapa</th>
                </tr>
              </thead>
              <tbody>
                {data.stages.map((stage) => (
                  <tr key={stage.status} className="border-t border-border">
                    <td className="py-1.5 pr-3">{stage.label}</td>
                    <td className="py-1.5 pr-3 w-1/2">
                      <div className="flex items-center gap-2">
                        <div className="h-2 rounded-full bg-brand" style={{ width: `${(stage.reached / top) * 100}%`, minWidth: stage.reached ? 4 : 0 }} />
                        <span className="mono text-xs">{stage.reached}</span>
                      </div>
                    </td>
                    <td className="py-1.5 text-right mono text-xs">{stage.status === "won" ? "" : pct(stage.conversion_pct)}</td>
                    <td className="py-1.5 text-right mono text-xs">{stage.status === "won" ? "" : days(stage.avg_days)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
