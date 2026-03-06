import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { engineApi, clientsApi } from "@/lib/api"
import type { Client, EngineAlert, EngineSummaryData } from "@/lib/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Globe,
  MousePointerClick,
  Eye,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  AlertCircle,
  CheckCircle,
  RefreshCw,
  ExternalLink,
  Link2,
} from "lucide-react"
import { toast } from "sonner"
import { formatTimeAgo } from "@/lib/utils"
import { useAuth } from "@/context/auth-context"

interface Props {
  client: Client
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString("es-ES")
}


function DeltaBadge({ value, invert }: { value: number | null; invert?: boolean }) {
  if (value == null) return null
  const positive = invert ? value < 0 : value > 0
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-medium ${positive ? "text-green-600" : value === 0 ? "text-muted-foreground" : "text-red-500"}`}>
      {value > 0 ? <TrendingUp className="h-3 w-3" /> : value < 0 ? <TrendingDown className="h-3 w-3" /> : null}
      {value > 0 ? "+" : ""}{value}%
    </span>
  )
}

function SeverityIcon({ severity }: { severity: string }) {
  if (severity === "critical") return <AlertCircle className="h-4 w-4 text-red-500" />
  if (severity === "warning") return <AlertTriangle className="h-4 w-4 text-amber-500" />
  return <CheckCircle className="h-4 w-4 text-blue-500" />
}

function SeverityBadge({ severity }: { severity: string }) {
  const variant = severity === "critical" ? "destructive" : severity === "warning" ? "warning" : "secondary"
  return <Badge variant={variant}>{severity}</Badge>
}

function LinkProjectDialog({ client }: { client: Client }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)

  const { data: projects, isLoading } = useQuery({
    queryKey: ["engine-projects"],
    queryFn: () => engineApi.listProjects(),
    enabled: open,
  })

  const linkMutation = useMutation({
    mutationFn: (projectId: number) => clientsApi.update(client.id, { engine_project_id: projectId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["client-summary", client.id] })
      toast.success("Proyecto vinculado correctamente")
      setOpen(false)
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || "Error al vincular proyecto"),
  })

  if (!open) {
    return (
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Link2 className="h-4 w-4 mr-2" /> Vincular proyecto
      </Button>
    )
  }

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">Seleccionar proyecto de Engine:</p>
      {isLoading && <p className="text-sm text-muted-foreground">Cargando proyectos...</p>}
      <div className="max-h-60 overflow-y-auto space-y-1">
        {(projects || []).map((p) => (
          <button
            key={p.id}
            className="w-full text-left px-3 py-2 rounded-md hover:bg-muted text-sm flex justify-between items-center"
            onClick={() => linkMutation.mutate(p.id)}
            disabled={linkMutation.isPending}
          >
            <span className="font-medium">{p.name}</span>
            <span className="text-xs text-muted-foreground">{p.domain}</span>
          </button>
        ))}
      </div>
      <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Cancelar</Button>
    </div>
  )
}

export function EngineSeoTab({ client }: Props) {
  const { isAdmin } = useAuth()
  const queryClient = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)

  const { data: engineConfig } = useQuery({
    queryKey: ["engine-config"],
    queryFn: () => engineApi.getConfig(),
    staleTime: 10 * 60_000,
  })

  const engineFrontendUrl = engineConfig?.engine_frontend_url

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      await engineApi.triggerSync()
      queryClient.invalidateQueries({ queryKey: ["client-summary", client.id] })
      toast.success("Sincronizado correctamente")
    } catch {
      toast.error("Error al sincronizar")
    } finally {
      setRefreshing(false)
    }
  }

  // Not linked
  if (!client.engine_project_id) {
    return (
      <Card>
        <CardContent className="p-6">
          <div className="text-center space-y-4 py-8">
            <Globe className="h-12 w-12 mx-auto text-muted-foreground" />
            <p className="text-muted-foreground">Este cliente no esta vinculado a un proyecto en Engine</p>
            {isAdmin && <LinkProjectDialog client={client} />}
          </div>
        </CardContent>
      </Card>
    )
  }

  const summary: EngineSummaryData | null = client.engine_summary_data
  const alerts = client.engine_alerts_data?.alerts || []

  // Linked but no data yet
  if (!summary) {
    return (
      <Card>
        <CardContent className="p-6">
          <div className="text-center space-y-4 py-8">
            <Globe className="h-12 w-12 mx-auto text-muted-foreground" />
            <p className="text-muted-foreground">Datos pendientes de sincronización</p>
            <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing}>
              <RefreshCw className={`h-4 w-4 mr-2 ${refreshing ? "animate-spin" : ""}`} />
              Sincronizar ahora
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {/* Card: Visibilidad SEO */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Globe className="h-4 w-4" /> Visibilidad SEO
          </CardTitle>
          {engineFrontendUrl && (
            <a
              href={`${engineFrontendUrl}/p/${client.engine_project_id}/dashboard`}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button variant="outline" size="sm">
                Abrir en Engine <ExternalLink className="h-3.5 w-3.5 ml-1.5" />
              </Button>
            </a>
          )}
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                <MousePointerClick className="h-3 w-3" /> Clicks 30d
              </p>
              <p className="kpi-value mt-1">{formatNumber(summary.clicks_30d || 0)}</p>
              <DeltaBadge value={summary.clicks_change_pct} />
            </div>
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                <Eye className="h-3 w-3" /> Impresiones 30d
              </p>
              <p className="kpi-value mt-1">{formatNumber(summary.impressions_30d || 0)}</p>
            </div>
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Keywords top 10</p>
              <p className="kpi-value mt-1">{summary.keywords_top10 ?? "-"}</p>
            </div>
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                <TrendingUp className="h-3 w-3" /> Posicion media
              </p>
              <p className="kpi-value mt-1">{summary.avg_position ?? "-"}</p>
            </div>
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">SEO Health</p>
              <div className="flex items-center gap-2 mt-1">
                <span className={`text-2xl font-bold ${
                  summary.seo_health?.score == null ? "text-muted-foreground" :
                  summary.seo_health.score >= 70 ? "text-green-600" :
                  summary.seo_health.score >= 40 ? "text-amber-500" : "text-red-500"
                }`}>
                  {summary.seo_health?.score ?? "-"}
                </span>
                <Badge variant={
                  summary.seo_health?.trend === "improving" ? "success" :
                  summary.seo_health?.trend === "declining" ? "destructive" : "secondary"
                }>
                  {summary.seo_health?.trend === "improving" ? "Mejorando" :
                   summary.seo_health?.trend === "declining" ? "Bajando" : "Estable"}
                </Badge>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Card: Alertas SEO */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <AlertTriangle className="h-4 w-4" /> Alertas SEO
          </CardTitle>
        </CardHeader>
        <CardContent>
          {alerts.length === 0 ? (
            <div className="flex items-center gap-2 text-green-600 text-sm">
              <CheckCircle className="h-4 w-4" />
              Sin alertas activas
            </div>
          ) : (
            <div className="space-y-2">
              {alerts.slice(0, 5).map((alert: EngineAlert) => (
                <div key={`${alert.type}-${alert.detected_at}`} className="flex items-start gap-3 p-2 rounded-md border">
                  <SeverityIcon severity={alert.severity} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium">{alert.title}</p>
                      <SeverityBadge severity={alert.severity} />
                    </div>
                    {alert.detail && <p className="text-xs text-muted-foreground mt-0.5">{alert.detail}</p>}
                  </div>
                  {alert.detected_at && (
                    <span className="text-xs text-muted-foreground whitespace-nowrap">
                      {new Date(alert.detected_at).toLocaleDateString("es-ES")}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Card: Cambios recientes */}
      {(summary.recent_changes?.length ?? 0) > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Cambios recientes</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {summary.recent_changes.slice(0, 5).map((change) => (
                <div key={`${change.type}-${change.detected_at}`} className="flex items-start gap-3 text-sm">
                  <SeverityIcon severity={change.severity || "info"} />
                  <div className="flex-1">
                    <p className="font-medium">{change.title}</p>
                    {change.detail && <p className="text-xs text-muted-foreground">{change.detail}</p>}
                  </div>
                  {change.detected_at && (
                    <span className="text-xs text-muted-foreground">
                      {new Date(change.detected_at).toLocaleDateString("es-ES")}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Footer: sync info */}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {client.engine_metrics_synced_at
            ? `Última sincronización: ${formatTimeAgo(client.engine_metrics_synced_at)}`
            : "Sin datos de sincronización"}
        </span>
        <Button variant="ghost" size="sm" onClick={handleRefresh} disabled={refreshing}>
          <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${refreshing ? "animate-spin" : ""}`} />
          Sincronizar ahora
        </Button>
      </div>
    </div>
  )
}
