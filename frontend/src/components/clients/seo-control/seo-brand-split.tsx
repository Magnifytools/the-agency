import { Bar, BarChart, Legend, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from "recharts"
import { Tag } from "lucide-react"
import type { ClientSeoSummary } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { InfoTooltip } from "@/components/ui/tooltip"
import { DeltaBadge } from "@/components/clients/delta-badge"
import { formatInt, formatShare, formatShortDay } from "@/lib/seo-control"

const COLORS = { brand: "#FEE630", non_brand: "#3b82f6", unclassified: "#a3a39a" }

const UNCLASSIFIED_HELP =
  "Google oculta las búsquedas poco frecuentes (por privacidad): sus clics cuentan en el total, pero no sabemos qué se buscó. Es la diferencia entre el total y la suma de las consultas."

interface Props {
  brand: NonNullable<ClientSeoSummary["brand"]>
  canEditTerms: boolean
  onEditTerms?: () => void
}

function pct(current: number, previous: number): number | null {
  if (previous <= 0) return null
  return Math.round(((current - previous) * 1000) / previous) / 10
}

/** Marca / Sin marca / Sin clasificar: clics de la ventana y su evolución semanal. */
export function SeoBrandSplit({ brand, canEditTerms, onEditTerms }: Props) {
  const { current, previous, terms, trend } = brand
  const total = current.brand.clicks + current.non_brand.clicks + current.unclassified.clicks

  if (terms.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><Tag className="h-4 w-4" /> Marca y sin marca</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Sin términos de marca no se puede separar quién busca al cliente por su nombre de quién llega buscando lo que vende.
          </p>
          {canEditTerms && onEditTerms ? (
            <Button size="sm" onClick={onEditTerms}>Añadir términos de marca</Button>
          ) : (
            <p className="text-xs text-muted-foreground">Quien puede editar el cliente los añade en su Configuración.</p>
          )}
        </CardContent>
      </Card>
    )
  }

  const blocks = [
    { key: "brand" as const, label: "Marca" },
    { key: "non_brand" as const, label: "Sin marca" },
    { key: "unclassified" as const, label: "Sin clasificar" },
  ]
  const chartData = trend.map((w) => ({
    week: formatShortDay(w.week_end),
    Marca: w.brand_clicks,
    "Sin marca": w.non_brand_clicks,
    "Sin clasificar": w.unclassified_clicks,
  }))

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2 text-base"><Tag className="h-4 w-4" /> Marca y sin marca</CardTitle>
        {canEditTerms && onEditTerms && (
          <Button size="sm" variant="ghost" onClick={onEditTerms}>Términos ({terms.length})</Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {blocks.map(({ key, label }) => (
            <div key={key} className="rounded-lg border border-border p-3">
              <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: COLORS[key] }} />
                {label}
                {key === "unclassified" && <InfoTooltip content={UNCLASSIFIED_HELP} align="start" />}
              </p>
              <p className="mono text-xl font-semibold mt-1">{formatInt(current[key].clicks)}</p>
              <p className="text-xs text-muted-foreground flex items-center gap-2">
                <span>{total > 0 ? formatShare(current[key].clicks / total) : "—"} de los clics</span>
                <DeltaBadge value={pct(current[key].clicks, previous[key].clicks)} digits={1} />
              </p>
            </div>
          ))}
        </div>
        <div className="h-56" aria-label="Clics por semana: marca, sin marca y sin clasificar">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <XAxis dataKey="week" fontSize={11} tick={{ fill: "#8a8a80" }} interval="preserveStartEnd" />
              <YAxis fontSize={11} tick={{ fill: "#8a8a80" }} width={40} />
              <ChartTooltip
                formatter={(value) => formatInt(Number(value))}
                contentStyle={{ backgroundColor: "#2a2a28", border: "1px solid rgba(254, 230, 48, 0.3)", color: "#f5f5f0", fontSize: 12 }}
                labelFormatter={(label) => `Semana hasta el ${label}`}
              />
              <Legend wrapperStyle={{ fontSize: 11, color: "#8a8a80" }} />
              <Bar dataKey="Marca" stackId="clics" fill={COLORS.brand} />
              <Bar dataKey="Sin marca" stackId="clics" fill={COLORS.non_brand} />
              <Bar dataKey="Sin clasificar" stackId="clics" fill={COLORS.unclassified} radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Términos: {terms.join(", ")}. Coincide sin acentos ni mayúsculas, con o sin espacios.
        </p>
      </CardContent>
    </Card>
  )
}
