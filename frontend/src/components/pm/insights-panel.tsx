import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import {
  AlertTriangle,
  Calendar,
  Clock,
  MessageCircle,
  TrendingUp,
  Lightbulb,
  Star,
  X,
  Check,
  RefreshCw,
  ChevronRight,
} from "lucide-react"
import { toast } from "sonner"
import { pmApi } from "@/lib/api"
import type { Insight, InsightType, InsightPriority } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { AlertSettingsButton } from "./alert-settings-dialog"
import { getErrorMessage } from "@/lib/utils"

const TYPE_ICONS: Record<InsightType, typeof AlertTriangle> = {
  deadline: Calendar,
  stalled: Clock,
  overdue: AlertTriangle,
  followup: MessageCircle,
  workload: TrendingUp,
  suggestion: Lightbulb,
  quality: Star,
}

const PRIORITY_COLORS: Record<InsightPriority, string> = {
  high: "border-l-red-500",
  medium: "border-l-yellow-500",
  low: "border-l-blue-500",
}

const PRIORITY_BADGES: Record<InsightPriority, "destructive" | "warning" | "default"> = {
  high: "destructive",
  medium: "warning",
  low: "default",
}

export function InsightsPanel() {
  const queryClient = useQueryClient()

  const { data: insights = [], isLoading } = useQuery({
    queryKey: ["insights"],
    queryFn: () => pmApi.insights(),
  })

  const generateMutation = useMutation({
    mutationFn: () => pmApi.generateInsights(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["insights"] })
      queryClient.invalidateQueries({ queryKey: ["insight-count"] })
      toast.success(`${data.length} insights generados`)
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al generar insights")),
  })

  const dismissMutation = useMutation({
    mutationFn: (id: number) => pmApi.dismissInsight(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insights"] })
      queryClient.invalidateQueries({ queryKey: ["insight-count"] })
    },
  })

  const actMutation = useMutation({
    mutationFn: (id: number) => pmApi.actOnInsight(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insights"] })
      queryClient.invalidateQueries({ queryKey: ["insight-count"] })
      toast.success("Marcado como actuado")
    },
  })

  const highPriority = insights.filter((i) => i.priority === "high")
  const otherPriority = insights.filter((i) => i.priority !== "high")

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-semibold">Asistente PM</CardTitle>
          <div className="flex items-center gap-1">
            <AlertSettingsButton />
            <Button
              variant="ghost"
              size="sm"
              onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${generateMutation.isPending ? "animate-spin" : ""}`} />
              Actualizar
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Cargando...</p>
        ) : insights.length === 0 ? (
          <div className="text-center py-6">
            <Lightbulb className="h-10 w-10 mx-auto text-muted-foreground mb-3" />
            <p className="text-sm text-muted-foreground">No hay insights activos</p>
            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending}
            >
              Generar insights
            </Button>
          </div>
        ) : (
          <>
            {/* High priority insights */}
            {highPriority.length > 0 && (
              <div className="space-y-2">
                {highPriority.map((insight) => (
                  <InsightCard
                    key={insight.id}
                    insight={insight}
                    onDismiss={() => dismissMutation.mutate(insight.id)}
                    onAct={() => actMutation.mutate(insight.id)}
                  />
                ))}
              </div>
            )}

            {/* Other insights */}
            {otherPriority.length > 0 && (
              <div className="space-y-2">
                {otherPriority.slice(0, 5).map((insight) => (
                  <InsightCard
                    key={insight.id}
                    insight={insight}
                    onDismiss={() => dismissMutation.mutate(insight.id)}
                    onAct={() => actMutation.mutate(insight.id)}
                    compact
                  />
                ))}
                {otherPriority.length > 5 && (
                  <p className="text-xs text-muted-foreground text-center pt-2">
                    +{otherPriority.length - 5} más
                  </p>
                )}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

function InsightCard({
  insight,
  onDismiss,
  onAct,
  compact = false,
}: {
  insight: Insight
  onDismiss: () => void
  onAct: () => void
  compact?: boolean
}) {
  const Icon = TYPE_ICONS[insight.insight_type] ?? AlertTriangle

  const getLink = () => {
    if (insight.task_id) return `/tasks?id=${insight.task_id}`
    if (insight.project_id) return `/projects/${insight.project_id}`
    if (insight.client_id) return `/clients/${insight.client_id}`
    return null
  }

  const link = getLink()

  return (
    <div
      className={`p-3 rounded-lg border border-border bg-card border-l-4 ${PRIORITY_COLORS[insight.priority]} group`}
    >
      <div className="flex items-start gap-3">
        <div className={`p-1.5 rounded-lg ${insight.priority === "high" ? "bg-red-500/10" : "bg-secondary"}`}>
          <Icon className={`h-4 w-4 ${insight.priority === "high" ? "text-red-400" : "text-muted-foreground"}`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className={`font-medium ${compact ? "text-sm" : ""}`}>{insight.title}</p>
            {!compact && (
              <Badge variant={PRIORITY_BADGES[insight.priority]} className="text-[10px]">
                {insight.priority}
              </Badge>
            )}
          </div>
          {!compact && (
            <p className="text-sm text-muted-foreground mt-1 line-clamp-2">{insight.description}</p>
          )}
          {!compact && insight.suggested_action && (
            <p className="text-xs text-brand mt-2">{insight.suggested_action}</p>
          )}
          {insight.client_name && (
            <p className="text-xs text-muted-foreground mt-1">{insight.client_name}</p>
          )}
        </div>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {link && (
            <Link
              to={link}
              onClick={onAct}
              className="p-1.5 rounded-md hover:bg-brand/10 text-muted-foreground hover:text-brand"
              title="Ver y actuar"
            >
              <ChevronRight className="h-4 w-4" />
            </Link>
          )}
          <button
            onClick={onAct}
            className="p-1.5 rounded-md hover:bg-green-500/10 text-muted-foreground hover:text-green-400"
            title="Marcar como actuado"
          >
            <Check className="h-4 w-4" />
          </button>
          <button
            onClick={onDismiss}
            className="p-1.5 rounded-md hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
            title="Descartar"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

export function InsightsBadge() {
  const { data: count } = useQuery({
    queryKey: ["insight-count"],
    queryFn: () => pmApi.insightCount(),
    refetchInterval: 60000, // Refresh every minute
  })

  if (!count || count.total === 0) return null

  return (
    <div className="flex items-center gap-1">
      {count.high > 0 && (
        <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 text-[10px] font-medium text-white px-1.5">
          {count.high}
        </span>
      )}
      {count.medium > 0 && (
        <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-yellow-500 text-[10px] font-medium text-black px-1.5">
          {count.medium}
        </span>
      )}
    </div>
  )
}
