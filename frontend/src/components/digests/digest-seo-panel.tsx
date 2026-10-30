import { Search } from "lucide-react"
import { digestSeoUnavailableReason } from "@/lib/gsc"
import type { DigestSeo, DigestSeoDetail, DigestSeoDetailRow, DigestSeoPeriod } from "@/lib/types"
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

function YearAgo({ period, changes }: { period: DigestSeoPeriod; changes: NonNullable<Extract<DigestSeo, { status: "ok" }>["vs_year_ago"]> }) {
  const parts = ([
    ["clics", changes.clicks_pct, "%"],
    ["impresiones", changes.impressions_pct, "%"],
    ["CTR", changes.ctr_delta, "pp"],
    ["posición media", changes.position_delta, "pos"],
  ] as const).filter(([, value]) => value != null)
  if (parts.length === 0) return null
  return (
    <p className="text-xs text-muted-foreground">
      Respecto a {monthName(period)}:{" "}
      {parts.map(([label, value, unit], i) => (
        <span key={label}>
          {label} <Change value={value} unit={unit} />
          {i < parts.length - 1 ? ", " : "."}
        </span>
      ))}
    </p>
  )
}

const shortMonth = (period: { start: string }) =>
  new Date(`${period.start}T12:00:00`).toLocaleDateString("es-ES", { month: "long" })

function RowsTable({ title, rows, compareLabel, pages }: { title: string; rows: DigestSeoDetailRow[]; compareLabel: string | null; pages?: boolean }) {
  if (rows.length === 0) return null
  return (
    <div className="space-y-1">
      <h3 className="text-xs font-semibold">{title}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-muted-foreground">
              <th className="py-1 text-left font-medium"><span className="sr-only">{pages ? "Página" : "Búsqueda"}</span></th>
              <th className="py-1 text-right font-medium">Clics</th>
              <th className="py-1 text-right font-medium">Posición</th>
              {compareLabel && <th className="py-1 text-right font-medium">Frente a {compareLabel}</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((row) => (
              <tr key={row.key}>
                <td className="max-w-[16rem] truncate py-1.5 pr-2" title={row.key}>{pages ? row.label ?? row.key : row.key}</td>
                <td className="mono py-1.5 text-right font-semibold">{num(row.clicks)}</td>
                <td className="mono py-1.5 text-right text-muted-foreground">{row.position == null ? "—" : dec(row.position)}</td>
                {compareLabel && (
                  <td className="mono py-1.5 text-right">
                    {row.is_new ? <span className="font-medium text-green-700 dark:text-green-400">nueva</span> : <Change value={row.clicks_pct} unit="%" />}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** La foto del mes: lo mismo que se pinta en el email y el PDF. */
function Detail({ detail }: { detail: DigestSeoDetail }) {
  const compareLabel = detail.previous ? shortMonth(detail.previous) : null
  const brand = detail.brand
  return (
    <div className="space-y-4 border-t border-border pt-4">
      <RowsTable title="Búsquedas que más visitas trajeron" rows={detail.queries} compareLabel={compareLabel} />
      <RowsTable title="Páginas con más visitas desde Google" rows={detail.pages} compareLabel={compareLabel} pages />
      {detail.opportunities.length > 0 && (
        <div className="space-y-1">
          <h3 className="text-xs font-semibold">Oportunidades: búsquedas cerca de la primera página</h3>
          <p className="text-xs text-muted-foreground">Entre la posición 8 y la 20, sin la marca y con al menos 30 impresiones en el mes.</p>
          <ul className="divide-y divide-border text-sm">
            {detail.opportunities.map((row) => (
              <li key={row.key} className="flex justify-between gap-2 py-1.5">
                <span className="truncate" title={row.key}>{row.key}</span>
                <span className="mono shrink-0 text-muted-foreground">posición {dec(row.position)} · {num(row.impressions)} impresiones</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {brand && (
        <div className="space-y-1">
          <h3 className="text-xs font-semibold">Con la marca y sin ella (clics)</h3>
          <ul className="divide-y divide-border text-sm">
            <li className="flex justify-between gap-2 py-1.5"><span>Sin la marca</span><span className="mono">{num(brand.non_brand)} {compareLabel && <Change value={brand.non_brand_pct} unit="%" />}</span></li>
            <li className="flex justify-between gap-2 py-1.5"><span>Con la marca</span><span className="mono">{num(brand.brand)} {compareLabel && <Change value={brand.brand_pct} unit="%" />}</span></li>
            {brand.unclassified > 0 && <li className="flex justify-between gap-2 py-1.5"><span>Sin detallar por Google</span><span className="mono">{num(brand.unclassified)}</span></li>}
          </ul>
        </div>
      )}
      {!brand && <p className="text-xs text-muted-foreground">Sin términos de marca: añádelos en Ajustes del cliente para separar el tráfico de marca.</p>}
    </div>
  )
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
            {seo.year_ago && seo.vs_year_ago && <YearAgo period={seo.year_ago} changes={seo.vs_year_ago} />}
            {seo.detail && <Detail detail={seo.detail} />}
            <p className="text-xs text-muted-foreground">
              Datos finales de Search Console ({seo.site_url}). Se añaden tal cual al email, al PDF, a Slack, a Discord y al enlace del cliente; la IA no los ve ni los redacta.
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
