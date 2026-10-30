import { useQuery } from "@tanstack/react-query"
import {
  Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis,
} from "recharts"
import { clientSeoApi } from "@/lib/api"
import { clientSeoKeys } from "@/lib/query-keys"
import type { SeoHistoryPoint } from "@/lib/types"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { formatInt, formatPosition, formatShortDay } from "@/lib/seo-control"

const COLORS = { clicks: "#FEE630", position: "#3b82f6" }
const AXIS = { fontSize: 11, tick: { fill: "#8a8a80" } }

interface Props {
  clientId: number
  /** Consulta abierta; null = cerrado. */
  query: string | null
  onClose: () => void
}

/** "sept 26" */
function formatMonth(value: string): string {
  return new Date(`${value}T12:00:00`).toLocaleDateString("es-ES", { month: "short", year: "2-digit" })
}

interface ChartRow {
  label: string
  Clics: number
  Posición: number | null
}

function toRows<T extends SeoHistoryPoint>(points: T[], label: (p: T) => string): ChartRow[] {
  return points.map((p) => ({ label: label(p), Clics: p.clicks, Posición: p.position }))
}

/**
 * Clics (barras) y posición media (línea, eje invertido: arriba = mejor).
 * La posición de un periodo sin impresiones queda en blanco, no a cero.
 */
function HistoryChart({ rows, title }: { rows: ChartRow[]; title: string }) {
  return (
    <figure className="space-y-1">
      <figcaption className="text-xs font-bold uppercase tracking-wider text-muted-foreground">{title}</figcaption>
      <div className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#8a8a8022" vertical={false} />
            <XAxis dataKey="label" {...AXIS} interval="preserveStartEnd" minTickGap={16} />
            <YAxis yAxisId="clicks" {...AXIS} width={40} allowDecimals={false} />
            <YAxis yAxisId="position" orientation="right" reversed {...AXIS} width={32} domain={[1, "auto"]}
              allowDecimals={false} />
            <ChartTooltip
              formatter={(value, name) => [name === "Posición" ? formatPosition(value as number | null)
                : formatInt(Number(value)), name]}
              contentStyle={{ fontSize: 12 }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar yAxisId="clicks" dataKey="Clics" fill={COLORS.clicks} radius={[2, 2, 0, 0]} />
            <Line yAxisId="position" dataKey="Posición" stroke={COLORS.position} strokeWidth={2}
              dot={rows.length <= 20} connectNulls={false} type="monotone" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </figure>
  )
}

/** Historial de una consulta: meses guardados (hasta 16) y los últimos 120 días. */
export function SeoQueryHistoryDialog({ clientId, query, onClose }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: clientSeoKeys.history(clientId, query ?? ""),
    queryFn: () => clientSeoApi.queryHistory(clientId, query ?? ""),
    enabled: query != null,
    staleTime: 10 * 60_000,
  })

  const lastMonth = data?.months.at(-1)
  const imported = data?.months.filter((m) => m.imported) ?? []
  return (
    <Dialog open={query != null} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogHeader>
        <DialogTitle className="break-words pr-6">{query}</DialogTitle>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>Historial de posiciones · posición media ponderada por impresiones; arriba = mejor.</span>
          {data?.is_brand && <Badge variant="outline">Marca</Badge>}
        </div>
      </DialogHeader>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Cargando…</p>
      ) : isError || !data ? (
        <p className="text-sm text-muted-foreground">No se pudo cargar el historial.</p>
      ) : data.status !== "ok" ? (
        <p className="text-sm text-muted-foreground">El historial no está disponible para esta propiedad.</p>
      ) : (
        <div className="space-y-4">
          {data.months.length > 0 ? (
            <>
              <HistoryChart title={`Por meses (${data.months.length})`}
                rows={toRows(data.months, (p) => formatMonth(p.month))} />
              {lastMonth && (
                <p className="text-xs text-muted-foreground">
                  {formatMonth(lastMonth.month)}: {formatInt(lastMonth.clicks)} clics, posición {formatPosition(lastMonth.position)}.
                </p>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              {data.monthly_backfilled
                ? "Aún no hay meses completos guardados."
                : "Importando los meses anteriores; listo tras la próxima pasada."}
            </p>
          )}
          {data.days.length > 0 && (
            <HistoryChart title={`Últimos ${data.days.length} días`}
              rows={toRows(data.days, (p) => formatShortDay(p.date))} />
          )}
          <p className="text-[11px] text-muted-foreground">
            Sólo meses cerrados (hasta 16). Un mes o día sin impresiones de esta búsqueda sale sin posición.
            {imported.length > 0 && ` De ${formatMonth(imported[0].month)} a ${formatMonth(imported[imported.length - 1].month)}, `
              + "importado de The Engine (una URL por búsqueda y día, así que los clics pueden quedarse cortos)."}
          </p>
        </div>
      )}
    </Dialog>
  )
}

/** Miniatura de la posición en los últimos meses (arriba = mejor). */
export function SeoSparkline({ values, months }: { values: (number | null)[]; months?: string[] }) {
  const known = values.filter((v): v is number => v != null)
  if (known.length === 0) return <span className="text-xs text-muted-foreground">—</span>
  const width = 64
  const height = 18
  const min = Math.min(...known)
  const max = Math.max(...known)
  const span = max - min || 1
  const step = values.length > 1 ? width / (values.length - 1) : 0
  // Posición menor (mejor) arriba.
  const y = (v: number) => 2 + ((v - min) / span) * (height - 4)
  let path = ""
  values.forEach((v, i) => {
    if (v == null) return
    const prev = i > 0 ? values[i - 1] : null
    path += `${prev == null ? "M" : "L"}${(i * step).toFixed(1)},${y(v).toFixed(1)} `
  })
  const label = values
    .map((v, i) => `${months?.[i] ? formatMonth(months[i]) : `mes ${i + 1}`}: ${formatPosition(v)}`)
    .join(", ")
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img"
      aria-label={`Posición por mes: ${label}`} className="inline-block align-middle">
      <title>{label}</title>
      <path d={path.trim()} fill="none" stroke={COLORS.position} strokeWidth={1.5} />
      {values.map((v, i) => v != null && (values[i - 1] == null && values[i + 1] == null) ? (
        <circle key={i} cx={i * step} cy={y(v)} r={1.5} fill={COLORS.position} />
      ) : null)}
    </svg>
  )
}
