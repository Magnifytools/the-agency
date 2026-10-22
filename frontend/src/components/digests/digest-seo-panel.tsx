import { Search } from "lucide-react"
import { digestSeoUnavailableReason } from "@/lib/gsc"
import type { DigestSeo, DigestSeoPeriod } from "@/lib/types"
import { Card, CardContent } from "@/components/ui/card"

// Mismo formato que el bloque del email (1.234 / 12,3). es-ES no agrupa los
// números de cuatro cifras y el editor no cuadraría con lo que se envía.
const group = (digits: string) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ".")
const num = (value: number) => group(String(Math.trunc(value)))
const dec = (value: number, digits = 1) => {
  const [whole, fraction] = value.toFixed(digits).split(".")
  return fraction ? `${group(whole)},${fraction}` : group(whole)
}
const monthName = (period: DigestSeoPeriod) =>
  new Date(`${period.start}T12:00:00`).toLocaleDateString("es-ES", { month: "long", year: "numeric" })
const capitalized = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)

function Change({ value, unit }: { value: number | null | undefined; unit: "%" | "pp" | "pos" }) {
  if (value == null) return <span className="text-muted-foreground">—</span>
  const better = value > 0
  const color = value === 0 ? "text-muted-foreground" : better ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"
  const text = unit === "pos"
    ? `${value > 0 ? "▲" : value < 0 ? "▼" : ""} ${dec(Math.abs(value))}`
    : `${value > 0 ? "+" : ""}${dec(value, unit === "pp" ? 2 : 1)}${unit === "%" ? " %" : " p. p."}`
  return <span className={`font-medium ${color}`}>{text}</span>
}

interface Props {
  seo: DigestSeo
  include: boolean
  canWrite: boolean
  onIncludeChange: (value: boolean) => void
}

/** Bloque de Search Console del resumen mensual: cifras y si se incluye (también en el PDF). */
export function DigestSeoPanel({ seo, include, canWrite, onIncludeChange }: Props) {
  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Search className="h-4 w-4 text-muted-foreground" />
            Visibilidad en Google
          </h2>
          {seo.status === "ok" && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={include} disabled={!canWrite} onChange={(e) => onIncludeChange(e.target.checked)} />
              Incluir en el resumen
            </label>
          )}
        </div>

        {seo.status === "ok" ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground">
                    <th className="py-1 text-left font-medium"></th>
                    <th className="py-1 text-right font-medium">{capitalized(monthName(seo.month))}</th>
                    {seo.previous && <th className="py-1 text-right font-medium">{capitalized(monthName(seo.previous))}</th>}
                    {seo.previous && <th className="py-1 text-right font-medium">Cambio</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border mono">
                  {([
                    ["Clics", (p: DigestSeoPeriod) => num(p.clicks), seo.vs_previous?.clicks_pct, "%"],
                    ["Impresiones", (p: DigestSeoPeriod) => num(p.impressions), seo.vs_previous?.impressions_pct, "%"],
                    ["CTR", (p: DigestSeoPeriod) => (p.ctr == null ? "—" : `${dec(p.ctr, 2)} %`), seo.vs_previous?.ctr_delta, "pp"],
                    ["Posición media", (p: DigestSeoPeriod) => (p.position == null ? "—" : dec(p.position)), seo.vs_previous?.position_delta, "pos"],
                  ] as const).map(([label, fmt, change, unit]) => (
                    <tr key={label}>
                      <td className="py-1.5 font-sans">{label}</td>
                      <td className="py-1.5 text-right font-semibold">{fmt(seo.month)}</td>
                      {seo.previous && <td className="py-1.5 text-right text-muted-foreground">{fmt(seo.previous)}</td>}
                      {seo.previous && <td className="py-1.5 text-right"><Change value={change} unit={unit} /></td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {seo.year_ago && seo.vs_year_ago?.clicks_pct != null && (
              <p className="text-xs text-muted-foreground">
                Respecto a {monthName(seo.year_ago)}: clics <Change value={seo.vs_year_ago.clicks_pct} unit="%" />.
              </p>
            )}
            <p className="text-xs text-muted-foreground">
              Datos finales de Search Console ({seo.site_url}). Se añaden tal cual al email, al PDF, a Slack y a Discord; la IA no los redacta.
            </p>
          </>
        ) : (
          <p role="status" className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm">
            Este resumen mensual no lleva el bloque de Search Console. {digestSeoUnavailableReason(seo)}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
