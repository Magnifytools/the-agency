import { useQuery } from "@tanstack/react-query"
import { engineApi } from "@/lib/api"
import type { Client } from "@/lib/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Globe, FileText, Key, MousePointerClick, Eye, TrendingUp } from "lucide-react"

interface Props {
  client: Client
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString("es-ES")
}

export function EngineMetricsWidget({ client }: Props) {
  const { data: metrics, isLoading, isError } = useQuery({
    queryKey: ["engine-metrics", client.engine_project_id],
    queryFn: () => engineApi.getMetrics(client.engine_project_id!),
    enabled: !!client.engine_project_id,
    staleTime: 5 * 60_000,
  })

  if (!client.engine_project_id) return null

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Globe className="h-4 w-4" /> Engine SEO
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Cargando metricas de Engine...</p>
        </CardContent>
      </Card>
    )
  }

  if (isError || !metrics) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Globe className="h-4 w-4" /> Engine SEO
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No se pudieron cargar las metricas de Engine</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Globe className="h-4 w-4" /> Engine SEO
          <span className="text-xs font-normal text-muted-foreground ml-auto">
            {metrics.domain}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <FileText className="h-3 w-3" /> Contenido
            </p>
            <p className="kpi-value mt-1">{formatNumber(metrics.content_count)}</p>
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <Key className="h-3 w-3" /> Keywords
            </p>
            <p className="kpi-value mt-1">{formatNumber(metrics.keyword_count)}</p>
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <TrendingUp className="h-3 w-3" /> Posicion media
            </p>
            <p className="kpi-value mt-1">{metrics.avg_position ?? "-"}</p>
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <MousePointerClick className="h-3 w-3" /> Clicks
            </p>
            <p className="kpi-value mt-1">{formatNumber(metrics.clicks_30d)}</p>
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <Eye className="h-3 w-3" /> Impresiones
            </p>
            <p className="kpi-value mt-1">{formatNumber(metrics.impressions_30d)}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
