import { useState } from "react"
import { useQuery, useMutation } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { Target, AlertTriangle, Phone, Lightbulb, Calendar, Send } from "lucide-react"
import { pmApi } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

export function DailyBriefingDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { data: briefing, isLoading } = useQuery({
    queryKey: ["daily-briefing"],
    queryFn: () => pmApi.dailyBriefing(),
  })

  const shareMutation = useMutation({
    mutationFn: () => pmApi.shareBriefingToDiscord(),
    onSuccess: () => {
      toast.success("Briefing compartido en Discord")
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, "Error al compartir en Discord"))
    }
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>{briefing?.greeting || "Briefing del día"}</DialogTitle>
      </DialogHeader>

      {isLoading ? (
        <div className="py-8 text-center text-muted-foreground">Cargando briefing...</div>
      ) : briefing ? (
        <div className="space-y-6 mt-4">
          {/* Priorities */}
          {briefing.priorities.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-3">
                <Target className="h-4 w-4 text-brand" />
                <h3 className="font-semibold text-sm">Prioridades de hoy</h3>
              </div>
              <div className="space-y-2">
                {briefing.priorities.map((task, i) => (
                  <Link
                    key={task.id}
                    to={`/tasks?id=${task.id}`}
                    onClick={() => onOpenChange(false)}
                    className="flex items-center gap-3 p-2 rounded-lg hover:bg-card group"
                  >
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand/10 text-brand text-xs font-medium">
                      {i + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate group-hover:text-brand">
                        {task.title}
                      </p>
                      {task.client && (
                        <p className="text-xs text-muted-foreground">{task.client}</p>
                      )}
                    </div>
                  </Link>
                ))}
              </div>
            </section>
          )}

          {/* Alerts */}
          {briefing.alerts.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle className="h-4 w-4 text-destructive" />
                <h3 className="font-semibold text-sm">Requiere atención</h3>
              </div>
              <div className="space-y-2">
                {briefing.alerts.map((alert) => (
                  <Link
                    key={alert.id}
                    to={`/tasks?id=${alert.id}`}
                    onClick={() => onOpenChange(false)}
                    className="flex items-center justify-between p-2 rounded-lg hover:bg-card group"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate group-hover:text-brand">
                        {alert.title}
                      </p>
                      {alert.client && (
                        <p className="text-xs text-muted-foreground">{alert.client}</p>
                      )}
                    </div>
                    <Badge variant="destructive" className="text-[10px]">
                      {alert.days_overdue}d vencida
                    </Badge>
                  </Link>
                ))}
              </div>
            </section>
          )}

          {/* Followups */}
          {briefing.followups.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-3">
                <Phone className="h-4 w-4 text-warning" />
                <h3 className="font-semibold text-sm">Seguimientos pendientes</h3>
              </div>
              <div className="space-y-2">
                {briefing.followups.map((f, i) => (
                  <div key={i} className="p-2 rounded-lg bg-card">
                    <p className="text-sm font-medium">{f.client}</p>
                    <p className="text-xs text-muted-foreground truncate">{f.subject}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Suggestion */}
          {briefing.suggestion && (
            <section className="p-3 rounded-lg bg-brand/5 border border-brand/20">
              <div className="flex items-start gap-2">
                <Lightbulb className="h-4 w-4 text-brand mt-0.5" />
                <p className="text-sm">{briefing.suggestion}</p>
              </div>
            </section>
          )}

          {/* Empty state */}
          {briefing.priorities.length === 0 &&
            briefing.alerts.length === 0 &&
            briefing.followups.length === 0 && (
              <div className="text-center py-6">
                <Calendar className="h-10 w-10 mx-auto text-muted-foreground mb-3" />
                <p className="text-muted-foreground">
                  No hay tareas urgentes para hoy. ¡Buen trabajo!
                </p>
              </div>
            )}
        </div>
      ) : null}

      <div className="flex justify-between items-center mt-6">
        <Button
          variant="outline"
          onClick={() => shareMutation.mutate()}
          disabled={shareMutation.isPending || isLoading || !briefing}
        >
          <Send className="w-4 h-4 mr-2" />
          {shareMutation.isPending ? "Enviando..." : "Compartir en Discord"}
        </Button>
        <Button onClick={() => onOpenChange(false)}>Cerrar</Button>
      </div>
    </Dialog>
  )
}

export function DailyBriefingButton() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Calendar className="h-4 w-4 mr-2" />
        Briefing
      </Button>
      <DailyBriefingDialog open={open} onOpenChange={setOpen} />
    </>
  )
}
