import { useQuery } from "@tanstack/react-query"
import { RefreshCw } from "lucide-react"
import { clientSeoApi } from "@/lib/api"
import { clientSeoKeys } from "@/lib/query-keys"
import type { SeoImpact } from "@/lib/types"
import { formatDay } from "@/lib/gsc"
import { formatInt, formatPosition } from "@/lib/seo-control"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { DeltaBadge } from "@/components/clients/delta-badge"

export interface ImpactQuery {
  date: string
  days: number
  scope: "site" | "page" | "group"
  page: string
  group: string
}

const REASONS: Record<NonNullable<SeoImpact["reason"]>, (impact: SeoImpact) => string> = {
  too_early: (impact) => `Aún es pronto: hace falta al menos una semana de datos después del cambio${impact.available_from ? ` (a partir del ${formatDay(impact.available_from)})` : ""}.`,
  outside_detail: (impact) => `El detalle por página sólo guarda 120 días${impact.detail_start ? ` (desde el ${formatDay(impact.detail_start)})` : ""}: elige una fecha más reciente o compara la web entera.`,
  no_data: () => "Google no tiene datos de esa página o grupo en esas fechas. Revisa que la URL sea la misma que en Search Console.",
}

/** El resultado de un antes/después, reutilizado en Control SEO y en el panel de tarea. */
export function ImpactResult({ impact }: { impact: SeoImpact }) {
  if (!impact.result) {
    return <p className="text-sm text-muted-foreground">{impact.reason ? REASONS[impact.reason](impact) : "Sin datos de Search Console para comparar."}</p>
  }
  const { result } = impact
  const rows = [
    { label: "Clics", before: formatInt(result.before.clicks), after: formatInt(result.after.clicks), delta: <DeltaBadge value={result.clicks_change_pct} digits={1} /> },
    { label: "Impresiones", before: formatInt(result.before.impressions), after: formatInt(result.after.impressions), delta: <DeltaBadge value={result.impressions_change_pct} digits={1} /> },
    { label: "Posición media", before: formatPosition(result.before.position), after: formatPosition(result.after.position), delta: <DeltaBadge value={result.position_delta} suffix="" digits={1} /> },
  ]
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1 pr-3 font-medium" />
              <th className="py-1 pr-3 font-medium">Antes · {formatDay(result.before.start)}–{formatDay(result.before.end)}</th>
              <th className="py-1 pr-3 font-medium">Después · {formatDay(result.after.start)}–{formatDay(result.after.end)}</th>
              <th className="py-1 font-medium">Cambio</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-t border-border">
                <td className="py-1.5 pr-3">{row.label}</td>
                <td className="py-1.5 pr-3 mono">{row.before}</td>
                <td className="py-1.5 pr-3 mono">{row.after}</td>
                <td className="py-1.5">{row.delta}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-muted-foreground">
        {result.days} días antes y {result.days} después; el día del cambio no cuenta.
        {result.pages != null ? ` ${result.pages} ${result.pages === 1 ? "página" : "páginas"}.` : ""}
        {" "}Compara también con la web entera: si todo sube o baja a la vez, no es sólo por el cambio.
      </p>
    </div>
  )
}

/** "Antes y después": mide qué pasó con el tráfico tras un cambio concreto. */
export function SeoImpactCard({ clientId, groups, end, value, onChange }: {
  clientId: number
  groups: string[]
  end: string
  value: ImpactQuery
  onChange: (next: ImpactQuery) => void
}) {
  const params = {
    date: value.date, days: value.days,
    ...(value.scope === "page" && value.page.trim() ? { page: value.page.trim() } : {}),
    ...(value.scope === "group" && value.group ? { group: value.group } : {}),
  }
  const ready = !!value.date && (value.scope === "site" || (value.scope === "page" ? !!value.page.trim() : !!value.group))
  const query = useQuery({
    queryKey: clientSeoKeys.impact(clientId, params),
    queryFn: () => clientSeoApi.impact(clientId, params),
    enabled: ready,
    staleTime: 10 * 60_000,
    retry: false,
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Antes y después</CardTitle>
        <p className="text-xs text-muted-foreground">Elige la fecha de un cambio (una migración, unos títulos nuevos…) y compara el tráfico de antes y de después.</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="space-y-1 text-xs text-muted-foreground">Fecha del cambio
            <Input type="date" value={value.date} max={end} onChange={(event) => onChange({ ...value, date: event.target.value })} className="w-40" />
          </label>
          <label className="space-y-1 text-xs text-muted-foreground">Comparar
            <Select value={String(value.days)} onChange={(event) => onChange({ ...value, days: Number(event.target.value) })} className="w-32">
              <option value="14">14 días</option>
              <option value="28">28 días</option>
              <option value="56">56 días</option>
            </Select>
          </label>
          <label className="space-y-1 text-xs text-muted-foreground">Qué
            <Select value={value.scope} onChange={(event) => onChange({ ...value, scope: event.target.value as ImpactQuery["scope"] })} className="w-40">
              <option value="site">La web entera</option>
              <option value="page">Una página</option>
              {groups.length > 0 && <option value="group">Un grupo de URL</option>}
            </Select>
          </label>
          {value.scope === "page" && (
            <Input aria-label="URL de la página" placeholder="https://…" value={value.page} onChange={(event) => onChange({ ...value, page: event.target.value })} className="min-w-[16rem] flex-1" />
          )}
          {value.scope === "group" && (
            <Select aria-label="Grupo de URL" value={value.group} onChange={(event) => onChange({ ...value, group: event.target.value })} className="w-48">
              <option value="">Elige un grupo…</option>
              {groups.map((name) => <option key={name} value={name}>{name}</option>)}
            </Select>
          )}
        </div>
        {!ready ? <p className="text-sm text-muted-foreground">Indica la fecha y qué quieres comparar.</p>
          : query.isPending ? <p role="status" className="text-sm text-muted-foreground">Comparando…</p>
            : query.isError ? <div role="alert" className="text-sm">No se pudo comparar. <Button size="sm" variant="outline" onClick={() => void query.refetch()}><RefreshCw className="h-3.5 w-3.5 mr-1" />Reintentar</Button></div>
              : <ImpactResult impact={query.data} />}
      </CardContent>
    </Card>
  )
}
