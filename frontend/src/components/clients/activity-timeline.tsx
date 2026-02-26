import { useQuery } from "@tanstack/react-query"
import { clientActivityApi } from "@/lib/api"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  MessageSquare,
  CheckCircle2,
  PlusCircle,
  Newspaper,
  FileText,
  Phone,
  Mail,
  Video,
  MessageCircle,
  Hash,
  HelpCircle,
} from "lucide-react"
import { cn } from "@/lib/utils"

interface Props {
  clientId: number
}

interface ActivityEvent {
  id: string
  type: string
  subtype: string
  timestamp: string
  title: string
  description: string | null
  detail: string | null
  user_name: string | null
  contact_name?: string | null
  icon: string
}

const typeConfig: Record<string, { color: string; bgColor: string; label: string }> = {
  communication: { color: "text-blue-600", bgColor: "bg-blue-100", label: "Comunicación" },
  task_completed: { color: "text-green-600", bgColor: "bg-green-100", label: "Tarea completada" },
  task_created: { color: "text-slate-600", bgColor: "bg-slate-100", label: "Tarea creada" },
  digest: { color: "text-purple-600", bgColor: "bg-purple-100", label: "Digest" },
  proposal: { color: "text-amber-600", bgColor: "bg-amber-100", label: "Presupuesto" },
}

const channelIcons: Record<string, typeof Mail> = {
  email: Mail,
  call: Phone,
  meeting: Video,
  whatsapp: MessageCircle,
  slack: Hash,
  other: HelpCircle,
}

function getIcon(event: ActivityEvent) {
  if (event.type === "communication") {
    const Icon = channelIcons[event.subtype] || MessageSquare
    return <Icon className="h-4 w-4" />
  }
  if (event.type === "task_completed") return <CheckCircle2 className="h-4 w-4" />
  if (event.type === "task_created") return <PlusCircle className="h-4 w-4" />
  if (event.type === "digest") return <Newspaper className="h-4 w-4" />
  if (event.type === "proposal") return <FileText className="h-4 w-4" />
  return <MessageSquare className="h-4 w-4" />
}

function formatRelativeDate(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return "Ahora"
  if (diffMins < 60) return `Hace ${diffMins}m`
  if (diffHours < 24) return `Hace ${diffHours}h`
  if (diffDays < 7) return `Hace ${diffDays}d`
  return date.toLocaleDateString("es-ES", { day: "numeric", month: "short", year: date.getFullYear() !== now.getFullYear() ? "numeric" : undefined })
}

function groupByDate(events: ActivityEvent[]): Map<string, ActivityEvent[]> {
  const groups = new Map<string, ActivityEvent[]>()
  for (const event of events) {
    const date = new Date(event.timestamp)
    const today = new Date()
    const yesterday = new Date(today)
    yesterday.setDate(yesterday.getDate() - 1)

    let key: string
    if (date.toDateString() === today.toDateString()) {
      key = "Hoy"
    } else if (date.toDateString() === yesterday.toDateString()) {
      key = "Ayer"
    } else {
      key = date.toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" })
    }

    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(event)
  }
  return groups
}

export function ActivityTimeline({ clientId }: Props) {
  const { data: events = [], isLoading } = useQuery({
    queryKey: ["client-activity", clientId],
    queryFn: () => clientActivityApi.list(clientId),
    enabled: !!clientId,
  })

  if (isLoading) return <p className="text-muted-foreground text-sm">Cargando actividad...</p>

  if (events.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <MessageSquare className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <p className="font-medium">Sin actividad registrada</p>
        <p className="text-sm mt-1">Las comunicaciones, tareas y digests aparecerán aquí</p>
      </div>
    )
  }

  const grouped = groupByDate(events)

  return (
    <div className="space-y-6">
      {Array.from(grouped.entries()).map(([dateLabel, dayEvents]) => (
        <div key={dateLabel}>
          {/* Date separator */}
          <div className="flex items-center gap-3 mb-3">
            <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">{dateLabel}</span>
            <div className="flex-1 h-px bg-border" />
            <Badge variant="outline" className="text-[10px]">{dayEvents.length}</Badge>
          </div>

          {/* Events for this day */}
          <div className="relative pl-6 space-y-0">
            {/* Vertical line */}
            <div className="absolute left-[11px] top-2 bottom-2 w-px bg-border" />

            {dayEvents.map((event) => {
              const config = typeConfig[event.type] || typeConfig.communication

              return (
                <div key={event.id} className="relative flex gap-3 pb-4 group">
                  {/* Dot / Icon */}
                  <div className={cn(
                    "absolute -left-6 mt-1 h-[22px] w-[22px] rounded-full flex items-center justify-center z-10 border-2 border-background",
                    config.bgColor, config.color
                  )}>
                    {getIcon(event)}
                  </div>

                  {/* Content */}
                  <Card className="flex-1 hover:shadow-sm transition-shadow">
                    <CardContent className="p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm font-medium">{event.title}</span>
                            <Badge variant="outline" className={cn("text-[9px] px-1.5 py-0", config.color)}>
                              {config.label}
                            </Badge>
                          </div>
                          {event.description && (
                            <p className="text-sm text-muted-foreground mt-0.5 line-clamp-2">{event.description}</p>
                          )}
                          <div className="flex items-center gap-3 mt-1.5 text-[11px] text-muted-foreground">
                            <span>{formatRelativeDate(event.timestamp)}</span>
                            {event.user_name && <span>por {event.user_name}</span>}
                            {event.contact_name && <span>con {event.contact_name}</span>}
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
