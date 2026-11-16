import { Fragment, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery } from "@tanstack/react-query"
import { ChevronDown, ChevronRight, Search } from "lucide-react"
import { clientBingApi } from "@/lib/api"
import { clientBingKeys } from "@/lib/query-keys"
import type { BingCheckResult, BingUrlRow, BingUrlState } from "@/lib/types"
import { formatDay } from "@/lib/gsc"
import { formatInt, formatPosition } from "@/lib/seo-control"
import { formatTimeAgo, getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

const STATES: Record<BingUrlState, { label: string; tone: string }> = {
  crawled: { label: "Rastreada", tone: "text-green-500" },
  redirect: { label: "Redirige", tone: "text-amber-600" },
  crawl_error: { label: "Error al rastrear", tone: "text-red-400" },
  discovered: { label: "Descubierta, sin rastrear", tone: "text-amber-600" },
  unknown: { label: "Bing no la conoce", tone: "text-red-400" },
  error: { label: "No se pudo leer", tone: "text-muted-foreground" },
}
// Más de tres meses sin rastrear: Bing apenas la está mirando.
const STALE_DAYS = 90

function pathOf(url: string) {
  try {
    return decodeURIComponent(new URL(url).pathname) || "/"
  } catch {
    return url
  }
}

function crawlAge(days: number | null) {
  if (days == null) return "—"
  if (days <= 0) return "hoy"
  return days === 1 ? "hace 1 día" : `hace ${formatInt(days)} días`
}

/**
 * Tarjeta "Bing" de Control SEO: si Bing rastrea las URLs clave del cliente y
 * cómo posicionan allí. Se comprueba a mano (gasta cuota de Bing) y no se
 * guarda nada: el resultado vive en esta pantalla.
 */
export function SeoBingCard({ clientId, isAdmin }: { clientId: number; isAdmin: boolean }) {
  const connection = useQuery({
    queryKey: clientBingKeys.connection(clientId),
    queryFn: () => clientBingApi.connection(clientId),
  })
  const [result, setResult] = useState<BingCheckResult | null>(null)
  const check = useMutation({
    mutationFn: () => clientBingApi.check(clientId),
    onSuccess: setResult,
    onSettled: () => void connection.refetch(),
  })
  const settings = `/clients/${clientId}?tab=ajustes&foco=bing`
  const data = connection.data

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base"><Search className="h-4 w-4" /> Bing</CardTitle>
        <p className="text-xs text-muted-foreground">
          ChatGPT y Copilot parten de los resultados de Bing antes de elegir qué citar. Una URL que Bing no rastrea
          difícilmente aparece ahí. No mide si la IA te cita: dice si cumples el primer paso.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {connection.isPending ? (
          <p role="status" className="text-sm text-muted-foreground">Cargando…</p>
        ) : !data?.connected ? (
          <p className="text-sm text-muted-foreground">
            Esta web no tiene Bing conectado.{" "}
            {isAdmin ? <Link to={settings} className="text-brand underline underline-offset-2">Conectar en los ajustes del cliente</Link>
              : "Pide a un admin que lo conecte con la cuenta de Bing de la web."}
          </p>
        ) : (
          <>
            {data.status === "invalid" && (
              <p role="alert" className="text-sm text-red-400">
                Bing ya no acepta la clave de esta web.{" "}
                {isAdmin ? <Link to={settings} className="underline underline-offset-2">Cambiarla</Link> : "Avisa a un admin."}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" onClick={() => check.mutate()} disabled={check.isPending}>
                {check.isPending ? "Comprobando en Bing…" : result ? "Volver a comprobar" : "Comprobar en Bing"}
              </Button>
              <span className="text-xs text-muted-foreground break-all">{data.site_url}</span>
            </div>
            {check.isError && <p role="alert" className="text-sm text-red-400">{getErrorMessage(check.error)}</p>}
            {result && <BingResult clientId={clientId} result={result} />}
          </>
        )}
      </CardContent>
    </Card>
  )
}

function BingResult({ clientId, result }: { clientId: number; result: BingCheckResult }) {
  const [open, setOpen] = useState<string | null>(null)
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        Comprobado {formatTimeAgo(result.checked_at)}.
        {result.window ? ` Rendimiento del ${formatDay(result.window.start)} al ${formatDay(result.window.end)} (lo último que trae Bing).` : " Bing no trae rendimiento de esta web."}
      </p>
      {result.watched_total === 0 && (
        <p className="text-xs text-muted-foreground">
          Sin URLs vigiladas: sólo se mira la web. Añade las URLs clave en la{" "}
          <Link to={`/clients/${clientId}?tab=web`} className="underline underline-offset-2">pestaña Web</Link>.
        </p>
      )}
      {result.watched_total > result.max_urls && (
        <p className="text-xs text-muted-foreground">
          Se miran las {result.max_urls} primeras de {formatInt(result.watched_total)} URLs vigiladas.
        </p>
      )}
      {result.urls.length === 0 ? (
        <p className="text-sm text-muted-foreground">El cliente no tiene web ni URLs vigiladas que comprobar.</p>
      ) : (
        <div className="overflow-x-auto">
          {/* Ancho mínimo: en móvil se desplaza en vez de partir la URL letra a letra. */}
          <table className="w-full min-w-[36rem] text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="py-1 pr-3 font-medium">URL</th>
                <th className="py-1 pr-3 font-medium">En Bing</th>
                <th className="py-1 pr-3 font-medium">Último rastreo</th>
                <th className="py-1 pr-3 font-medium text-right">Impresiones</th>
                <th className="py-1 pr-3 font-medium text-right">Clics</th>
                <th className="py-1 pr-3 font-medium text-right">Posición</th>
              </tr>
            </thead>
            <tbody>
              {result.urls.map((row) => (
                <Fragment key={row.url}>
                  <BingRow row={row} open={open === row.url} onToggle={() => setOpen(open === row.url ? null : row.url)} />
                  {open === row.url && (
                    <tr><td colSpan={6} className="pb-3 pl-6"><BingQueries clientId={clientId} url={row.url} /></td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function BingRow({ row, open, onToggle }: { row: BingUrlRow; open: boolean; onToggle: () => void }) {
  const state = STATES[row.state]
  const stale = row.days_since_crawl != null && row.days_since_crawl > STALE_DAYS
  const detail = row.state === "error" ? row.error
    : row.http_status && row.state !== "crawled" ? `HTTP ${row.http_status}` : null
  return (
    <tr className="border-t border-border align-top">
      <td className="py-1.5 pr-3 min-w-[9rem] max-w-[18rem]">
        <button type="button" onClick={onToggle} aria-expanded={open}
          aria-label={`${open ? "Ocultar" : "Ver"} consultas de ${pathOf(row.url)}`}
          className="flex items-start gap-1 text-left hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand rounded">
          {open ? <ChevronDown className="h-3.5 w-3.5 mt-0.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 mt-0.5 shrink-0" />}
          <span className="break-all">{row.label || pathOf(row.url)}</span>
        </button>
      </td>
      <td className={`py-1.5 pr-3 ${state.tone}`}>
        {state.label}
        {detail && <span className="block text-[11px] text-muted-foreground">{detail}</span>}
      </td>
      <td className={`py-1.5 pr-3 whitespace-nowrap ${stale ? "text-amber-600" : ""}`}
        title={stale ? "Más de tres meses sin rastrear" : undefined}>
        {crawlAge(row.days_since_crawl)}
      </td>
      <td className="py-1.5 pr-3 mono text-right">{row.impressions == null ? "—" : formatInt(row.impressions)}</td>
      <td className="py-1.5 pr-3 mono text-right">{row.clicks == null ? "—" : formatInt(row.clicks)}</td>
      <td className="py-1.5 pr-3 mono text-right">{formatPosition(row.position)}</td>
    </tr>
  )
}

function BingQueries({ clientId, url }: { clientId: number; url: string }) {
  // POST que gasta cuota: una vez por URL y pantalla, sin repetir al volver a la pestaña.
  const query = useQuery({
    queryKey: clientBingKeys.queries(clientId, url),
    queryFn: () => clientBingApi.pageQueries(clientId, url),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  })
  if (query.isPending) return <p role="status" className="text-xs text-muted-foreground">Pidiendo las consultas a Bing…</p>
  if (query.isError) return <p role="alert" className="text-xs text-red-400">{getErrorMessage(query.error)}</p>
  const { queries } = query.data
  if (queries.length === 0) return <p className="text-xs text-muted-foreground">Bing no trae búsquedas de esta URL.</p>
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-muted-foreground">
          <th className="py-1 pr-3 font-medium">Búsqueda en Bing</th>
          <th className="py-1 pr-3 font-medium text-right">Impresiones</th>
          <th className="py-1 pr-3 font-medium text-right">Clics</th>
          <th className="py-1 font-medium text-right">Posición</th>
        </tr>
      </thead>
      <tbody>
        {queries.map((q) => (
          <tr key={q.query} className="border-t border-border">
            <td className="py-1 pr-3 break-all">{q.query}</td>
            <td className="py-1 pr-3 mono text-right">{formatInt(q.impressions)}</td>
            <td className="py-1 pr-3 mono text-right">{formatInt(q.clicks)}</td>
            <td className="py-1 mono text-right">{formatPosition(q.position)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
