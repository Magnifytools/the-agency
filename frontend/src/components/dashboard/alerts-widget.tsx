import { useQuery } from "@tanstack/react-query"
import { dashboardApi } from "@/lib/api"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { AlertTriangle, Clock, Users, FileText, Briefcase, ChevronRight } from "lucide-react"
import { Link } from "react-router-dom"

interface Alert {
  type: string
  severity: "critical" | "warning" | "info"
  count: number
  title: string
  detail?: string[]
  link: string
}

interface AlertsSummary {
  total: number
  critical: number
  alerts: Alert[]
}

const iconMap: Record<string, React.ReactNode> = {
  overdue_tasks: <Clock className="h-4 w-4" />,
  missing_dailys: <FileText className="h-4 w-4" />,
  incomplete_timesheets: <Clock className="h-4 w-4" />,
  clients_no_hours: <Briefcase className="h-4 w-4" />,
  capacity_overload: <Users className="h-4 w-4" />,
}

const severityColors: Record<string, string> = {
  critical: "bg-red-500/10 border-red-500/30 text-red-400",
  warning: "bg-amber-500/10 border-amber-500/30 text-amber-400",
  info: "bg-blue-500/10 border-blue-500/30 text-blue-400",
}

export function AlertsWidget() {
  const { data, isLoading } = useQuery<AlertsSummary>({
    queryKey: ["dashboard", "alerts-summary"],
    queryFn: () => dashboardApi.alertsSummary(),
    refetchInterval: 5 * 60 * 1000, // Refresh every 5 min
  })

  if (isLoading) return null

  const alerts = data?.alerts ?? []
  const total = data?.total ?? 0
  const critical = data?.critical ?? 0

  if (total === 0) {
    return (
      <Card>
        <CardContent className="p-4 text-center text-muted-foreground">
          <p className="text-sm">Sin alertas activas</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-bold uppercase tracking-wider flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-500" />
          Alertas
          <Badge variant={critical > 0 ? "destructive" : "warning"} className="ml-auto">
            {total} {critical > 0 ? `(${critical} críticas)` : ""}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {alerts.map((alert) => (
          <Link
            key={alert.type}
            to={alert.link}
            className={`block p-3 rounded-lg border transition-colors hover:opacity-80 ${severityColors[alert.severity]}`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {iconMap[alert.type]}
                <span className="text-sm font-medium">{alert.title}</span>
              </div>
              <ChevronRight className="h-4 w-4 opacity-50" />
            </div>
            {alert.detail && alert.detail.length > 0 && (
              <p className="text-xs opacity-70 mt-1 ml-6">
                {alert.detail.slice(0, 3).join(", ")}
                {alert.detail.length > 3 ? ` +${alert.detail.length - 3} más` : ""}
              </p>
            )}
          </Link>
        ))}
      </CardContent>
    </Card>
  )
}
