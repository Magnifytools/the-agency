import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { engineApi } from "@/lib/api"
import { useAuth } from "@/context/auth-context"
import type { Client } from "@/lib/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Globe, FileText, Key, MousePointerClick, Eye, TrendingUp, RefreshCw } from "lucide-react"
import { formatTimeAgo } from "@/lib/utils"
import { toast } from "sonner"

interface Props {
  client: Client
}

function formatEngineSyncTime(value: string): string {
  return formatTimeAgo(value.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`)
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString("es-ES")
}


export function EngineMetricsWidget({ client }: Props) {
  const { isAdmin } = useAuth()
  const queryClient = useQueryClient()
  const [refreshing, setRefreshing] = useState(false)

  if (!client.engine_project_id) return null

  const hasCachedData = client.engine_metrics_synced_at != null

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      const result = await engineApi.triggerSync()
      await queryClient.invalidateQueries({ queryKey: ["client-summary"] })
      if (result.detail === "not configured") toast.error("Engine no está configurado.")
      else if (result.failed) toast.error(`Sincronización incompleta: ${result.failed} cliente(s) conservaron sus datos anteriores.`)
      else toast.success(`${result.synced} cliente(s) sincronizados.`)
    } catch {
      toast.error("No se pudo sincronizar Engine.")
    } finally {
      setRefreshing(false)
    }
  }

  if (!hasCachedData) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Globe className="h-4 w-4" /> Engine SEO
            {isAdmin && <Button
              variant="ghost"
              size="icon"
              className="ml-auto h-6 w-6"
              onClick={() => void handleRefresh()}
              disabled={refreshing}
              aria-label="Sincronizar Engine"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
            </Button>}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Pendiente de sincronización</p>
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
            Datos sincronizados {formatEngineSyncTime(client.engine_metrics_synced_at!)}
          </span>
          {isAdmin && <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={() => void handleRefresh()}
            disabled={refreshing}
            aria-label="Sincronizar Engine"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
          </Button>}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <FileText className="h-3 w-3" /> Contenido
            </p>
            <p className="kpi-value mt-1">{client.engine_content_count != null ? formatNumber(client.engine_content_count) : "-"}</p>
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <Key className="h-3 w-3" /> Keywords
            </p>
            <p className="kpi-value mt-1">{client.engine_keyword_count != null ? formatNumber(client.engine_keyword_count) : "-"}</p>
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <TrendingUp className="h-3 w-3" /> Posicion media
            </p>
            <p className="kpi-value mt-1">{client.engine_avg_position ?? "-"}</p>
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <MousePointerClick className="h-3 w-3" /> Clicks
            </p>
            <p className="kpi-value mt-1">{client.engine_clicks_30d != null ? formatNumber(client.engine_clicks_30d) : "-"}</p>
          </div>
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <Eye className="h-3 w-3" /> Impresiones
            </p>
            <p className="kpi-value mt-1">{client.engine_impressions_30d != null ? formatNumber(client.engine_impressions_30d) : "-"}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
