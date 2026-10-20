import { BarChart3 } from "lucide-react"
import type { DigestGa4 } from "@/lib/types"
import { Card, CardContent } from "@/components/ui/card"
import { ga4Change, ga4ErrorLabel, ga4Number } from "@/lib/ga4"

interface Props {
  ga4: DigestGa4
  include: boolean
  canWrite: boolean
  onIncludeChange: (value: boolean) => void
}

const UNAVAILABLE: Record<string, string> = {
  no_property: "El cliente no tiene propiedad de GA4 en sus ajustes.",
  not_synced: "La propiedad de GA4 todavía no se ha importado.",
  incomplete: "GA4 aún no tiene el mes cerrado (Google tarda unos días en procesarlo).",
  no_data: "GA4 no tiene datos de este mes.",
}

/** Bloque de GA4 del resumen mensual: cifras calculadas y si se incluye. */
export function DigestGa4Panel({ ga4, include, canWrite, onIncludeChange }: Props) {
  const rows = ga4.status === "ok" && ga4.month ? ([
    ["Visitas", ga4.month.sessions, ga4.previous?.sessions, ga4.vs_previous?.sessions_pct],
    ["Conversiones", ga4.month.key_events, ga4.previous?.key_events, ga4.vs_previous?.key_events_pct],
    ["Visitas desde IA", ga4.month.ai_sessions, ga4.previous?.ai_sessions, ga4.vs_previous?.ai_sessions_pct],
  ] as const) : []

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <BarChart3 className="h-4 w-4 text-muted-foreground" />
            Visitas y conversiones (GA4)
          </h2>
          {ga4.status === "ok" && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={include} disabled={!canWrite} onChange={(e) => onIncludeChange(e.target.checked)} />
              Incluir en el resumen
            </label>
          )}
        </div>
        {ga4.status === "ok" ? (
          <table className="w-full text-sm">
            <tbody className="divide-y divide-border">
              {rows.map(([label, current, previous, change]) => (
                <tr key={label}>
                  <td className="py-1.5">{label}</td>
                  <td className="py-1.5 text-right font-medium">{ga4Number(current)}</td>
                  <td className="py-1.5 text-right text-muted-foreground">{previous != null ? ga4Number(previous) : "—"}</td>
                  <td className="py-1.5 text-right">{ga4Change(change) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-muted-foreground">
            {UNAVAILABLE[ga4.status] ?? "Sin datos de GA4."} {ga4ErrorLabel(ga4.error_code)}
          </p>
        )}
        <p className="text-xs text-muted-foreground">Cifras calculadas con los datos importados de GA4; la IA no las redacta.</p>
      </CardContent>
    </Card>
  )
}
