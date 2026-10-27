import { useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { LineChart, RefreshCw } from "lucide-react"
import { clientSeoApi } from "@/lib/api"
import { clientSeoKeys } from "@/lib/query-keys"
import type { Client, ClientSeoSummary, SeoControlStatus, SeoWindowDays } from "@/lib/types"
import { useAuth } from "@/context/auth-context"
import { formatDay } from "@/lib/gsc"
import { formatInt, formatPosition, seoStatusMessage } from "@/lib/seo-control"
import { formatTimeAgo } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { DeltaBadge } from "@/components/clients/delta-badge"
import { SeoBrandSplit } from "./seo-brand-split"
import { SeoSectionsTable } from "./seo-sections-table"
import { SeoGroupsCard } from "./seo-groups-card"
import { SeoMoversTable } from "./seo-movers-table"
import { SeoAnnotationsCard } from "./seo-annotations-card"
import { SeoImpactCard, type ImpactQuery } from "./seo-impact-card"
import { SeoDecayCard } from "./seo-decay-card"

interface Props {
  client: Client
  /** Abre la Configuración del cliente (propiedad y términos de marca). */
  onOpenSettings?: () => void
}

export const SEO_STALE_TIME = 10 * 60_000

/**
 * Pestaña "Control SEO" (Resultados): tráfico de Google del cliente por marca,
 * sección, consulta y página, con la misma ventana que su estado.
 */
export function SeoControlTab({ client, onOpenSettings }: Props) {
  const { isAdmin, hasPermission } = useAuth()
  const canWriteClient = hasPermission("clients", true)
  const [days, setDays] = useState<SeoWindowDays>(28)
  const [section, setSection] = useState<string | null>(null)
  const [view, setView] = useState<"sections" | "groups">("sections")
  const [group, setGroup] = useState<string | null>(null)

  const changeView = (next: "sections" | "groups") => {
    setView(next)
    setSection(null)
    setGroup(null)
  }
  const viewToggle = (
    <div className="flex items-center gap-1" role="group" aria-label="Agrupar páginas por">
      {(["sections", "groups"] as const).map((value) => (
        <Button key={value} size="sm" variant={view === value ? "secondary" : "ghost"} className="h-7 text-xs"
          aria-pressed={view === value} onClick={() => changeView(value)}>
          {value === "sections" ? "Secciones" : "Grupos"}
        </Button>
      ))}
    </div>
  )

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: clientSeoKeys.summary(client.id, days),
    queryFn: () => clientSeoApi.get(client.id, days),
    staleTime: SEO_STALE_TIME,
  })
  // "Qué ha pasado" cubre las 16 semanas de la gráfica.
  const trend = data?.brand?.trend ?? []
  const annotationsTo = data?.window?.end ?? null
  const annotationsFrom = trend[0]?.week_start ?? (annotationsTo ? shiftDay(annotationsTo, -111) : null)
  const annotationsQuery = useQuery({
    queryKey: clientSeoKeys.annotations(client.id, annotationsFrom ?? "", annotationsTo ?? ""),
    queryFn: () => clientSeoApi.annotations(client.id, annotationsFrom!, annotationsTo!),
    enabled: !!annotationsFrom && !!annotationsTo,
    staleTime: SEO_STALE_TIME,
  })
  const [impact, setImpact] = useState<ImpactQuery | null>(null)
  const impactQuery: ImpactQuery = impact ?? {
    date: annotationsTo ? shiftDay(annotationsTo, -28) : "", days: 28, scope: "site", page: "", group: "",
  }
  const compare = (next: Partial<ImpactQuery>) => {
    setImpact({ ...impactQuery, ...next })
    requestAnimationFrame(() => document.getElementById("seo-impact")?.scrollIntoView?.({ behavior: "smooth", block: "start" }))
  }

  const header = (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h2 className="text-lg font-semibold flex items-center gap-2"><LineChart className="h-5 w-5" /> Control SEO</h2>
        {data?.window && (
          <p className="text-xs text-muted-foreground">
            {data.window.days} días hasta el {formatDay(data.window.end)} · frente a los {data.window.days} anteriores
            {data.site_url ? ` · ${data.site_url}` : ""}
          </p>
        )}
      </div>
      <div className="flex items-center gap-1 bg-muted/30 p-1 rounded-lg border border-border" role="group" aria-label="Ventana">
        {([7, 28] as const).map((value) => (
          <Button key={value} size="sm" variant={days === value ? "default" : "ghost"} className="h-7 text-xs"
            aria-pressed={days === value} onClick={() => { setDays(value); setSection(null); setGroup(null) }}>
            {value} d
          </Button>
        ))}
      </div>
    </div>
  )

  if (isLoading) {
    return <div className="space-y-4">{header}<Skeleton className="h-32 w-full" /><Skeleton className="h-64 w-full" /></div>
  }
  if (isError || !data) {
    return (
      <div className="space-y-4">
        {header}
        <Card><CardContent className="py-8 text-center space-y-3">
          <p className="text-sm text-muted-foreground">No se pudo cargar el Control SEO.</p>
          <Button size="sm" variant="ghost" onClick={() => void refetch()}><RefreshCw className="h-4 w-4 mr-1" /> Reintentar</Button>
        </CardContent></Card>
      </div>
    )
  }
  if (data.status !== "ok" || !data.totals || !data.brand) {
    return (
      <div className="space-y-4">
        {header}
        <SeoControlEmpty data={data} isAdmin={isAdmin} canWriteClient={canWriteClient} onOpenSettings={onOpenSettings} />
      </div>
    )
  }

  const { totals } = data
  const noTraffic = totals.current.clicks === 0 && totals.current.impressions === 0
  const sectionLabel = data.sections.find((s) => s.key === section)?.label ?? null
  const ctr = (value: number | null) => value == null ? "—" : `${(value * 100).toLocaleString("es-ES", { maximumFractionDigits: 2 })} %`

  return (
    <div className="space-y-4">
      {header}
      <Card>
        <CardContent className="pt-6">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <Kpi label="Clics" value={formatInt(totals.current.clicks)}
              delta={<DeltaBadge value={totals.change.clicks_pct} digits={1} />} />
            <Kpi label="Impresiones" value={formatInt(totals.current.impressions)}
              delta={<DeltaBadge value={totals.change.impressions_pct} digits={1} />} />
            <Kpi label="CTR" value={ctr(totals.current.ctr)}
              delta={<DeltaBadge value={totals.change.ctr_delta == null ? null : totals.change.ctr_delta * 100} suffix=" pp" digits={2} />} />
            <Kpi label="Posición media" value={formatPosition(totals.current.position)}
              delta={<DeltaBadge value={totals.change.position_delta} suffix="" digits={1} />} />
          </div>
          {data.coverage?.query_clicks_share != null && (
            <p className="mt-3 text-[11px] text-muted-foreground">
              Google atribuye a consultas concretas el {Math.round(data.coverage.query_clicks_share * 100)} % de los clics; el resto son búsquedas poco frecuentes que oculta.
            </p>
          )}
        </CardContent>
      </Card>

      {noTraffic ? (
        <Card><CardContent className="py-8 text-center">
          <p className="text-sm text-muted-foreground">Google no registra clics ni impresiones de esta propiedad en la ventana.</p>
        </CardContent></Card>
      ) : (
        <>
          <SeoBrandSplit brand={data.brand} canEditTerms={canWriteClient} onEditTerms={onOpenSettings}
            markedDates={annotationsQuery.data?.items.map((item) => item.date)} />
          {annotationsFrom && annotationsTo && (
            <SeoAnnotationsCard clientId={client.id} from={annotationsFrom} to={annotationsTo} data={annotationsQuery.data}
              isError={annotationsQuery.isError} onRetry={() => void annotationsQuery.refetch()} canWrite={canWriteClient}
              onCompare={(date) => compare({ date, scope: "site" })} />
          )}
          {view === "sections" ? (
            <SeoSectionsTable sections={data.sections} selected={section} onSelect={setSection} actions={viewToggle} />
          ) : (
            <SeoGroupsCard clientId={client.id} days={days} selected={group} onSelect={setGroup} actions={viewToggle}
              canEdit={canWriteClient} onOpenSettings={onOpenSettings} />
          )}
          <SeoMoversTable key={`queries-${days}`} clientId={client.id} kind="queries" days={days} summaryRows={data.queries} />
          <SeoMoversTable key={`pages-${days}`} clientId={client.id} kind="pages" days={days} summaryRows={data.pages}
            section={section} sectionLabel={sectionLabel} onClearSection={() => setSection(null)}
            group={group} onClearGroup={() => setGroup(null)} />
          <SeoDecayCard clientId={client.id} canCreateTask={hasPermission("tasks", true)}
            onCompare={(page) => compare({ scope: "page", page, days: 28, date: annotationsTo ? shiftDay(annotationsTo, -28) : impactQuery.date })} />
          {annotationsTo && (
            <div id="seo-impact" className="scroll-mt-8">
              <SeoImpactCard clientId={client.id} end={annotationsTo}
                groups={(client.seo_page_groups ?? []).map((g) => g.name)} value={impactQuery} onChange={setImpact} />
            </div>
          )}
        </>
      )}
    </div>
  )
}

function shiftDay(day: string, days: number) {
  const date = new Date(`${day}T12:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

function Kpi({ label, value, delta }: { label: string; value: string; delta: ReactNode }) {
  return (
    <div>
      <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="kpi-value mono mt-1">{value}</p>
      <div className="min-h-4">{delta}</div>
    </div>
  )
}

function SeoControlEmpty({ data, isAdmin, canWriteClient, onOpenSettings }: {
  data: ClientSeoSummary
  isAdmin: boolean
  canWriteClient: boolean
  onOpenSettings?: () => void
}) {
  const status = data.status as Exclude<SeoControlStatus, "ok">
  const needsAccount = status === "not_connected" || status === "reconnect_required"
  const importing = status === "not_synced" || status === "backfilling"
  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Control SEO</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm">{seoStatusMessage(status, data.error_code)}</p>
        {importing && (
          <p className="text-xs text-muted-foreground">
            {data.last_synced_at ? `Última pasada: ${formatTimeAgo(data.last_synced_at)}.` : "Aún no ha corrido ninguna pasada para esta propiedad."}
          </p>
        )}
        {status === "no_property" && (canWriteClient && onOpenSettings ? (
          <Button size="sm" onClick={onOpenSettings}>Añadir la propiedad en Configuración</Button>
        ) : (
          <p className="text-xs text-muted-foreground">Quien puede editar el cliente la añade en su Configuración.</p>
        ))}
        {needsAccount && (isAdmin ? (
          <Link to="/settings#search-console" className="text-sm text-brand underline underline-offset-2">
            {status === "not_connected" ? "Conectar en Ajustes → Search Console" : "Reconectar en Ajustes → Search Console"}
          </Link>
        ) : (
          <p className="text-xs text-muted-foreground">Pide a un admin que lo revise en Ajustes → Search Console.</p>
        ))}
      </CardContent>
    </Card>
  )
}
