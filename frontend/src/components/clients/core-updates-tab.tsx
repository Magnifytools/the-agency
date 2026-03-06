import { useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { engineApi } from "@/lib/api"
import type { Client } from "@/lib/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  ZAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts"
import {
  TrendingDown,
  TrendingUp,
  Search,
  Loader2,
  Crosshair,
  Minus,
  Plus,
} from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

interface Props {
  client: Client
}

interface CoreUpdateSummary {
  pre_total_clicks: number
  post_total_clicks: number
  net_click_change: number
  net_click_change_pct: number
  centroid_distance: number
  keywords_lost: number
  keywords_gained: number
  keywords_retained: number
}

interface KeywordPoint {
  keyword: string
  category: "lost" | "gained" | "retained"
  clicks_pre: number
  clicks_post: number
  x: number
  y: number
}

interface ThemeCluster {
  theme_label: string
  keywords: string[]
  total_clicks: number
  keyword_count: number
}

interface CoreUpdateResult {
  summary: CoreUpdateSummary
  keywords: KeywordPoint[]
  themes_lost: ThemeCluster[]
  themes_gained: ThemeCluster[]
}

const CATEGORY_COLORS: Record<string, string> = {
  lost: "#60a5fa",
  gained: "#fb923c",
  retained: "#4ade80",
}

const CATEGORY_LABELS: Record<string, string> = {
  lost: "Perdidas",
  gained: "Ganadas",
  retained: "Retenidas",
}

function formatNumber(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString("es-ES")
}

function getDefaultDates() {
  const today = new Date()
  const postEnd = today.toISOString().split("T")[0]
  const postStart = new Date(today.getTime() - 30 * 86400000)
    .toISOString()
    .split("T")[0]
  const preEnd = new Date(today.getTime() - 31 * 86400000)
    .toISOString()
    .split("T")[0]
  const preStart = new Date(today.getTime() - 60 * 86400000)
    .toISOString()
    .split("T")[0]
  return { preStart, preEnd, postStart, postEnd }
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: KeywordPoint }> }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload as KeywordPoint
  return (
    <div
      className="rounded-lg border px-3 py-2 text-xs"
      style={{
        backgroundColor: "hsl(var(--card))",
        border: "1px solid hsl(var(--border))",
        color: "hsl(var(--foreground))",
      }}
    >
      <p className="font-medium mb-1">{d.keyword}</p>
      <p>
        <span
          className="inline-block w-2 h-2 rounded-full mr-1.5"
          style={{ backgroundColor: CATEGORY_COLORS[d.category] }}
        />
        {CATEGORY_LABELS[d.category]}
      </p>
      <p className="text-muted-foreground">
        Clicks: {d.clicks_pre} → {d.clicks_post}
      </p>
    </div>
  )
}

export function CoreUpdatesTab({ client }: Props) {
  const defaults = getDefaultDates()
  const [preStart, setPreStart] = useState(defaults.preStart)
  const [preEnd, setPreEnd] = useState(defaults.preEnd)
  const [postStart, setPostStart] = useState(defaults.postStart)
  const [postEnd, setPostEnd] = useState(defaults.postEnd)
  const [topN, setTopN] = useState(1000)
  const [metric, setMetric] = useState<"clicks" | "impressions">("clicks")
  const [result, setResult] = useState<CoreUpdateResult | null>(null)

  const analyzeMutation = useMutation({
    mutationFn: () =>
      engineApi.analyzeCoreUpdate(client.engine_project_id!, {
        period_pre_start: preStart,
        period_pre_end: preEnd,
        period_post_start: postStart,
        period_post_end: postEnd,
        top_n: topN,
        metric,
      }),
    onSuccess: (data) => {
      setResult(data)
      toast.success("Analisis completado")
    },
    onError: (err) =>
      toast.error(getErrorMessage(err, "Error al analizar core update")),
  })

  if (!client.engine_project_id) {
    return (
      <Card>
        <CardContent className="p-6">
          <div className="text-center space-y-4 py-8">
            <Search className="h-12 w-12 mx-auto text-muted-foreground" />
            <p className="text-muted-foreground">
              Este cliente no esta vinculado a un proyecto en Engine
            </p>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {/* Controls */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Pre — Inicio
              </label>
              <input
                type="date"
                value={preStart}
                onChange={(e) => setPreStart(e.target.value)}
                className="block w-[150px] rounded-md border border-border bg-background px-3 py-1.5 text-sm"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Pre — Fin
              </label>
              <input
                type="date"
                value={preEnd}
                onChange={(e) => setPreEnd(e.target.value)}
                className="block w-[150px] rounded-md border border-border bg-background px-3 py-1.5 text-sm"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Post — Inicio
              </label>
              <input
                type="date"
                value={postStart}
                onChange={(e) => setPostStart(e.target.value)}
                className="block w-[150px] rounded-md border border-border bg-background px-3 py-1.5 text-sm"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Post — Fin
              </label>
              <input
                type="date"
                value={postEnd}
                onChange={(e) => setPostEnd(e.target.value)}
                className="block w-[150px] rounded-md border border-border bg-background px-3 py-1.5 text-sm"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Top N
              </label>
              <select
                value={topN}
                onChange={(e) => setTopN(Number(e.target.value))}
                className="block rounded-md border border-border bg-background px-3 py-1.5 text-sm"
              >
                <option value={500}>500</option>
                <option value={1000}>1000</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Metrica
              </label>
              <select
                value={metric}
                onChange={(e) =>
                  setMetric(e.target.value as "clicks" | "impressions")
                }
                className="block rounded-md border border-border bg-background px-3 py-1.5 text-sm"
              >
                <option value="clicks">Clicks</option>
                <option value="impressions">Impressions</option>
              </select>
            </div>
            <Button
              onClick={() => analyzeMutation.mutate()}
              disabled={analyzeMutation.isPending}
            >
              {analyzeMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Analizando...
                </>
              ) : (
                <>
                  <Search className="h-4 w-4 mr-2" />
                  Analizar
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Results */}
      {result && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <Card>
              <CardContent className="p-4">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                  {result.summary.net_click_change < 0 ? (
                    <TrendingDown className="h-3 w-3" />
                  ) : (
                    <TrendingUp className="h-3 w-3" />
                  )}
                  Cambio neto clicks
                </p>
                <p
                  className={`kpi-value mt-1 ${result.summary.net_click_change < 0 ? "text-red-500" : "text-green-600"}`}
                >
                  {result.summary.net_click_change > 0 ? "+" : ""}
                  {formatNumber(result.summary.net_click_change)}
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {result.summary.net_click_change_pct > 0 ? "+" : ""}
                  {result.summary.net_click_change_pct}%
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                  <Crosshair className="h-3 w-3" />
                  Distancia centroide
                </p>
                <p className="kpi-value mt-1">
                  {result.summary.centroid_distance.toFixed(4)}
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Mayor = mas cambio tematico
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                  <Minus className="h-3 w-3" />
                  Keywords perdidas
                </p>
                <p className="kpi-value mt-1 text-blue-400">
                  {formatNumber(result.summary.keywords_lost)}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                  <Plus className="h-3 w-3" />
                  Keywords ganadas
                </p>
                <p className="kpi-value mt-1 text-orange-400">
                  {formatNumber(result.summary.keywords_gained)}
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Scatter Chart */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                Mapa semantico PCA 2D
                <div className="flex items-center gap-3 ml-auto text-xs font-normal">
                  {Object.entries(CATEGORY_COLORS).map(([cat, color]) => (
                    <span key={cat} className="flex items-center gap-1">
                      <span
                        className="w-2.5 h-2.5 rounded-full"
                        style={{ backgroundColor: color }}
                      />
                      {CATEGORY_LABELS[cat]}
                    </span>
                  ))}
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent className="h-[400px]">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart
                  margin={{ top: 10, right: 10, bottom: 10, left: 10 }}
                >
                  <XAxis
                    dataKey="x"
                    type="number"
                    tick={{ fill: "#8a8a80" }}
                    fontSize={11}
                    name="PC1"
                  />
                  <YAxis
                    dataKey="y"
                    type="number"
                    tick={{ fill: "#8a8a80" }}
                    fontSize={11}
                    name="PC2"
                  />
                  <ZAxis
                    dataKey="clicks_pre"
                    range={[20, 400]}
                    name="Clicks"
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <Scatter data={result.keywords}>
                    {result.keywords.map((kw, i) => (
                      <Cell
                        key={i}
                        fill={CATEGORY_COLORS[kw.category]}
                        fillOpacity={0.7}
                      />
                    ))}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* Theme clusters */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Lost themes */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <TrendingDown className="h-4 w-4 text-blue-400" />
                  Temas perdidos
                  <Badge variant="secondary" className="ml-auto">
                    {result.themes_lost.length} clusters
                  </Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                {result.themes_lost.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Sin temas perdidos significativos
                  </p>
                ) : (
                  <div className="space-y-3">
                    {result.themes_lost.map((theme, i) => (
                      <div
                        key={i}
                        className="p-3 rounded-lg border border-border"
                      >
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-sm font-medium">
                            {theme.theme_label}
                          </span>
                          <span className="text-xs font-mono text-red-500">
                            -{formatNumber(theme.total_clicks)} clicks
                          </span>
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {theme.keyword_count} keywords
                        </p>
                        <div className="flex flex-wrap gap-1 mt-2">
                          {theme.keywords.slice(0, 8).map((kw) => (
                            <Badge
                              key={kw}
                              variant="outline"
                              className="text-[10px]"
                            >
                              {kw}
                            </Badge>
                          ))}
                          {theme.keywords.length > 8 && (
                            <Badge variant="outline" className="text-[10px]">
                              +{theme.keywords.length - 8}
                            </Badge>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Gained themes */}
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <TrendingUp className="h-4 w-4 text-orange-400" />
                  Temas ganados
                  <Badge variant="secondary" className="ml-auto">
                    {result.themes_gained.length} clusters
                  </Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                {result.themes_gained.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Sin temas ganados significativos
                  </p>
                ) : (
                  <div className="space-y-3">
                    {result.themes_gained.map((theme, i) => (
                      <div
                        key={i}
                        className="p-3 rounded-lg border border-border"
                      >
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-sm font-medium">
                            {theme.theme_label}
                          </span>
                          <span className="text-xs font-mono text-green-600">
                            +{formatNumber(theme.total_clicks)} clicks
                          </span>
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {theme.keyword_count} keywords
                        </p>
                        <div className="flex flex-wrap gap-1 mt-2">
                          {theme.keywords.slice(0, 8).map((kw) => (
                            <Badge
                              key={kw}
                              variant="outline"
                              className="text-[10px]"
                            >
                              {kw}
                            </Badge>
                          ))}
                          {theme.keywords.length > 8 && (
                            <Badge variant="outline" className="text-[10px]">
                              +{theme.keywords.length - 8}
                            </Badge>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
