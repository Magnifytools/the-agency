import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { FileSearch, ShieldCheck } from "lucide-react"
import { webApi } from "@/lib/api"
import type { ClientWebHealth, WebExpiryLevel, WebHostExpiry, WebRobotsInfo } from "@/lib/types"
import { getAgencyTimezone, parseApiInstant } from "@/lib/dates"
import { getErrorMessage } from "@/lib/utils"
import { formatInt } from "@/components/web/change-format"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { formatInstant } from "@/components/web/uptime-status"

export const webHealthKey = (clientId: number) => ["web-health", clientId] as const

type Variant = "success" | "destructive" | "warning" | "secondary"

const LEVEL_VARIANT: Record<WebExpiryLevel, Variant> = { ok: "success", warning: "warning", critical: "destructive" }

function formatDay(value: string) {
  return parseApiInstant(value).toLocaleDateString("es-ES", {
    day: "numeric", month: "short", year: "numeric", timeZone: getAgencyTimezone(),
  })
}

function daysText(days: number) {
  if (days < 0) return `caducó hace ${-days} ${days === -1 ? "día" : "días"}`
  if (days === 0) return "caduca hoy"
  return `en ${days} ${days === 1 ? "día" : "días"}`
}

function useWebHealth(clientId: number) {
  return useQuery({ queryKey: webHealthKey(clientId), queryFn: () => webApi.health(clientId) })
}

function ExpiryBadge({ level, expiresAt, days }: { level: WebExpiryLevel | null; expiresAt: string | null; days: number | null }) {
  if (!level || !expiresAt || days === null) return null
  return (
    <Badge variant={LEVEL_VARIANT[level]} title={`Caduca el ${formatDay(expiresAt)}`}>
      {formatDay(expiresAt)} · {daysText(days)}
    </Badge>
  )
}

function CertCell({ cert }: { cert: WebHostExpiry["cert"] }) {
  if (cert.status === "no_https") {
    return <span className="text-sm text-amber-600">Sin HTTPS: ninguna URL vigilada usa https.</span>
  }
  return (
    <div className="space-y-1">
      <ExpiryBadge level={cert.level} expiresAt={cert.expires_at} days={cert.days_left} />
      {cert.status === "invalid" && (
        <p className="text-xs text-red-600">El navegador no lo acepta: {cert.error}</p>
      )}
      {cert.status === "error" && (
        <p className="text-xs text-muted-foreground">
          Hoy no se pudo leer ({cert.error}){cert.expires_at ? "; se muestra la última fecha conocida." : "."}
        </p>
      )}
      {cert.issuer && cert.status !== "error" && <p className="text-xs text-muted-foreground">Emisor: {cert.issuer}</p>}
    </div>
  )
}

function DomainCell({ domain }: { domain: WebHostExpiry["domain"] }) {
  const name = domain.name ? <span className="mono text-xs">{domain.name}</span> : null
  switch (domain.status) {
    case "unsupported":
      return <span className="text-xs text-muted-foreground">El registro de este dominio no publica su fecha de caducidad (sin RDAP, como .es). Revísala en el registrador.</span>
    case "no_date":
      return <span className="text-xs text-muted-foreground">{name} El registro no da fecha de caducidad.</span>
    case "not_found":
      return <span className="text-xs text-muted-foreground">El registro no encuentra el dominio.</span>
    case "error":
      return (
        <div className="space-y-1">
          <ExpiryBadge level={domain.level} expiresAt={domain.expires_at} days={domain.days_left} />
          <p className="text-xs text-muted-foreground">
            Hoy no se pudo consultar ({domain.error}){domain.expires_at ? "; se muestra la última fecha conocida." : "."}
          </p>
        </div>
      )
    default:
      return (
        <div className="space-y-1">
          <ExpiryBadge level={domain.level} expiresAt={domain.expires_at} days={domain.days_left} />
          {name && <p>{name}</p>}
        </div>
      )
  }
}

function LoadState({ isLoading, label, onRetry }: { isLoading: boolean; label: string; onRetry: () => void }) {
  // Mientras carga no se pinta nada: la disponibilidad, encima, ya enseña su propio "Cargando…".
  if (isLoading) return null
  return (
    <div role="alert" className="flex items-center justify-between gap-3 text-sm">
      <span>No se pudo cargar {label}.</span>
      <Button size="sm" variant="outline" onClick={onRetry}>Reintentar</Button>
    </div>
  )
}

/**
 * Cuándo caducan el certificado y el dominio de cada host vigilado. Lo mira el
 * job diario `web_health` a partir de las URLs de disponibilidad.
 */
export function WebExpiryCard({ clientId }: { clientId: number }) {
  const { data, isLoading, isError, refetch } = useWebHealth(clientId)
  if (isLoading || isError || !data) {
    return <LoadState isLoading={isLoading} label="la caducidad del dominio y del certificado" onRetry={() => refetch()} />
  }
  const lastCheck = data.hosts.map((h) => h.checked_at).sort().at(-1) ?? null
  return (
    <Card>
      <CardHeader className="space-y-0">
        <CardTitle className="flex items-center gap-2 text-base"><ShieldCheck className="h-4 w-4" /> Dominio y certificado</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {!data.expiry_enabled && (
          <p className="text-sm text-amber-600">La comprobación diaria va con el monitor de caídas, que está apagado.</p>
        )}
        {data.hosts.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Se comprueba cada día para las webs de la lista de disponibilidad. Aún no hay datos.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="py-1 pr-3 font-medium">Web</th>
                  <th className="py-1 pr-3 font-medium">Certificado</th>
                  <th className="py-1 font-medium">Dominio</th>
                </tr>
              </thead>
              <tbody>
                {data.hosts.map((host) => (
                  <tr key={host.host} className="border-t border-border align-top">
                    <td className="py-2 pr-3 mono text-xs">{host.host}</td>
                    <td className="py-2 pr-3"><CertCell cert={host.cert} /></td>
                    <td className="py-2"><DomainCell domain={host.domain} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Thresholds data={data} lastCheck={lastCheck} />
      </CardContent>
    </Card>
  )
}

function Thresholds({ data, lastCheck }: { data: ClientWebHealth; lastCheck: string | null }) {
  const t = data.thresholds
  return (
    <p className="text-xs text-muted-foreground">
      Avisa con {t.cert_warning_days} días de margen para el certificado ({t.cert_critical_days} o menos es crítico)
      y {t.domain_warning_days} para el dominio ({t.domain_critical_days} o menos es crítico).
      {lastCheck && ` Última comprobación: ${formatInstant(lastCheck)}.`}
    </p>
  )
}

const SITEMAP_TEXT: Record<NonNullable<WebRobotsInfo["sitemap"]["status"]>, string> = {
  ok: "Responde",
  empty: "Responde, pero sin URLs",
  invalid: "No es un XML de sitemap válido",
  error: "No responde",
}

function SitemapLine({ sitemap }: { sitemap: WebRobotsInfo["sitemap"] }) {
  if (!sitemap.status) return null
  const count = sitemap.url_count ?? 0
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="font-medium">Sitemap</span>
      <Badge variant={sitemap.status === "ok" ? "success" : "warning"}>{SITEMAP_TEXT[sitemap.status]}</Badge>
      {sitemap.url && (
        <a href={sitemap.url} target="_blank" rel="noreferrer" className="mono text-xs text-brand hover:underline break-all">
          {sitemap.url}
        </a>
      )}
      <span className="text-xs text-muted-foreground">
        {sitemap.source === "declared" ? "(declarado en robots.txt)" : "(no hay ninguno declarado; se mira /sitemap.xml)"}
      </span>
      {sitemap.status === "ok" && (
        <span className="text-xs text-muted-foreground">{sitemap.has_more ? `${formatInt(count)} URLs o más` : `${formatInt(count)} URLs`}</span>
      )}
      {sitemap.status === "error" && sitemap.error && <span className="text-xs text-muted-foreground">({sitemap.error})</span>}
    </div>
  )
}

function RobotsBlock({ clientId, item, canWrite }: { clientId: number; item: WebRobotsInfo; canWrite: boolean }) {
  const qc = useQueryClient()
  const review = useMutation({
    mutationFn: () => webApi.reviewRobots(clientId, item.origin),
    onSuccess: () => {
      toast.success("Cambio del robots.txt revisado")
      return qc.invalidateQueries({ queryKey: webHealthKey(clientId) })
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  return (
    <div className="space-y-2 rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <a href={`${item.origin}/robots.txt`} target="_blank" rel="noreferrer" className="mono text-xs text-brand hover:underline">
          {item.origin}/robots.txt
        </a>
        {item.blocks_all && <Badge variant="destructive">Bloquea la web entera a Google</Badge>}
        {item.status === "missing" && <Badge variant="secondary">No existe (Google lo rastrea todo)</Badge>}
        {item.status === "error" && <Badge variant="warning">Hoy no se pudo leer{item.error ? `: ${item.error}` : ""}</Badge>}
        {item.status === "ok" && !item.blocks_all && <Badge variant="success">Correcto</Badge>}
      </div>
      {item.pending_review && item.changed_at && (
        <div role="status" className="space-y-2 rounded-md border border-amber-800/40 bg-amber-950/20 p-2 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>Cambió el {formatInstant(item.changed_at)}. Revisa que el cambio sea intencionado.</span>
            {canWrite && (
              <Button size="sm" variant="outline" disabled={review.isPending} onClick={() => review.mutate()}>
                {review.isPending ? "Marcando…" : "Marcar como revisado"}
              </Button>
            )}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <RobotsText title="Antes" body={item.previous_body} />
            <RobotsText title="Ahora" body={item.body} />
          </div>
        </div>
      )}
      {!item.pending_review && item.reviewed_at && (
        <p className="text-xs text-muted-foreground">
          Último cambio revisado el {formatInstant(item.reviewed_at)}{item.reviewed_by ? ` por ${item.reviewed_by}` : ""}.
        </p>
      )}
      {!item.pending_review && item.body ? (
        <details>
          <summary className="cursor-pointer text-xs text-muted-foreground">Ver el robots.txt guardado</summary>
          <RobotsText body={item.body} />
        </details>
      ) : null}
      <SitemapLine sitemap={item.sitemap} />
    </div>
  )
}

function RobotsText({ title, body }: { title?: string; body: string | null }) {
  return (
    <div className="min-w-0">
      {title && <p className="text-xs font-medium text-muted-foreground">{title}</p>}
      <pre className="mono mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-all rounded bg-muted p-2 text-xs">
        {body ? body : "(vacío o no existía)"}
      </pre>
    </div>
  )
}

/**
 * robots.txt y sitemap de cada web vigilada (sólo con la vigilancia de cambios
 * encendida). El cambio del robots.txt se marca como revisado aquí.
 */
export function WebRobotsCard({ clientId, canWrite }: { clientId: number; canWrite: boolean }) {
  const { data, isLoading, isError, refetch } = useWebHealth(clientId)
  if (isLoading || isError || !data) {
    return <LoadState isLoading={isLoading} label="el robots.txt y el sitemap" onRetry={() => refetch()} />
  }
  const lastCheck = data.robots.map((r) => r.checked_at).sort().at(-1) ?? null
  return (
    <Card>
      <CardHeader className="space-y-0">
        <CardTitle className="flex items-center gap-2 text-base"><FileSearch className="h-4 w-4" /> robots.txt y sitemap</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {!data.robots_enabled && (
          <p className="text-sm text-amber-600">La revisión diaria va con la vigilancia de cambios, que está apagada en el servidor.</p>
        )}
        {data.robots.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Se revisa cada día en las webs de las URLs vigiladas. Aún no hay datos.
          </p>
        ) : (
          data.robots.map((item) => <RobotsBlock key={item.origin} clientId={clientId} item={item} canWrite={canWrite} />)
        )}
        {lastCheck && <p className="text-xs text-muted-foreground">Última comprobación: {formatInstant(lastCheck)}.</p>}
      </CardContent>
    </Card>
  )
}
