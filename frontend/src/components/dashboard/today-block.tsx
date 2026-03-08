import { useQuery } from "@tanstack/react-query"
import { dashboardApi } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { CalendarCheck, Clock } from "lucide-react"
import { Link } from "react-router-dom"

const PRIORITY_COLORS: Record<string, string> = {
  urgent: "bg-red-500",
  high: "bg-orange-400",
  medium: "bg-blue-400",
  low: "bg-slate-300",
}

interface TodayTask {
  id: number
  title: string
  status: string
  priority: string
  client_name: string | null
  estimated_minutes: number | null
}

interface TodayData {
  date: string
  total_tasks: number
  by_user: Record<string, TodayTask[]>
}

export function TodayBlock() {
  const { data, isLoading } = useQuery<TodayData>({
    queryKey: ["dashboard-today"],
    queryFn: () => dashboardApi.today(),
    staleTime: 60_000,
  })

  if (isLoading || !data || data.total_tasks === 0) return null

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <CalendarCheck className="h-4 w-4 text-brand" />
          Hoy
          <Badge variant="secondary" className="ml-1 text-xs">
            {data.total_tasks} {data.total_tasks === 1 ? "tarea" : "tareas"}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {Object.entries(data.by_user).map(([userName, tasks]) => (
            <div key={userName}>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">{userName}</p>
              <div className="space-y-1.5">
                {tasks.map((task) => (
                  <Link
                    key={task.id}
                    to="/tasks"
                    className="flex items-center gap-2 py-1.5 px-2 rounded-lg hover:bg-muted/50 transition-colors group"
                  >
                    <div className={`h-2 w-2 rounded-full shrink-0 ${PRIORITY_COLORS[task.priority] ?? "bg-slate-300"}`} />
                    <span className="text-sm truncate flex-1 group-hover:text-foreground">{task.title}</span>
                    {task.client_name && (
                      <span className="text-[11px] text-muted-foreground shrink-0">{task.client_name}</span>
                    )}
                    {task.estimated_minutes && (
                      <span className="text-[11px] text-muted-foreground shrink-0 flex items-center gap-0.5">
                        <Clock className="h-3 w-3" />
                        {task.estimated_minutes}m
                      </span>
                    )}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
