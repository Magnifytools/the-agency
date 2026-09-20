import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { Calendar } from "lucide-react"
import { useAuth } from "@/context/auth-context"
import { calendarApi } from "@/lib/api"
import { calendarKeys } from "@/lib/calendar-queries"
import { formatCivilDate, parseApiInstant } from "@/lib/dates"
import { Button } from "@/components/ui/button"

export function NextMeeting({ today }: { today: string }) {
  const { user } = useAuth()
  const { data, isPending, isError, isFetching, refetch } = useQuery({
    queryKey: calendarKeys.nextMeeting(user?.id),
    queryFn: calendarApi.nextMeeting,
    enabled: Boolean(user),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })
  if (!user) return null
  const meeting = data?.meeting
  const zone = data?.timezone === "Europe/Madrid" ? "Hora de Madrid" : `Hora de ${data?.timezone}`
  const synced = data?.last_synced_at
    ? parseApiInstant(data.last_synced_at).toLocaleString("es-ES", {
      timeZone: data.timezone, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
    }) : null

  return (
    <section aria-label="Tu próxima reunión" className="rounded-xl border border-border px-4 py-3 space-y-2">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Calendar className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <h2>Tu próxima reunión</h2>
      </div>
      {isPending && <p role="status" className="text-sm text-muted-foreground">Consultando reuniones…</p>}
      {isError && <div role="alert" className="flex flex-wrap items-center gap-2 text-sm">
        <p>{data ? "No se ha podido actualizar la reunión guardada." : "No se pudieron consultar las reuniones."}</p>
        <Button variant="outline" size="sm" disabled={isFetching} onClick={() => void refetch()}>Reintentar reuniones</Button>
      </div>}
      {meeting && <div className="space-y-1 min-w-0">
        <p className="text-sm font-medium break-words">{meeting.title}</p>
        <p className="text-sm text-muted-foreground">
          <time dateTime={`${meeting.date}T${meeting.time}`}>
            {meeting.date === today ? "Hoy" : formatCivilDate(meeting.date, { weekday: "short", day: "numeric", month: "short" })} a las {meeting.time}
          </time>{" · "}{zone}{" · "}{meeting.source === "google" ? "Google Calendar" : "Calendario manual"}
        </p>
      </div>}
      {data && !meeting && !isError && <p className="text-sm text-muted-foreground">No hay próximas reuniones guardadas.</p>}
      {data && <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        {data.connection_status === "reconnect_required" ? <>
          <span>Google Calendar necesita reconexión; sus reuniones guardadas pueden haber cambiado.</span>
          <Link to="/settings#calendar" className="text-brand underline underline-offset-2">Reconectar calendario</Link>
        </> : data.connection_status === "disconnected" ? <>
          <span>Google Calendar no está conectado.</span>
          <Link to="/settings#calendar" className="text-brand underline underline-offset-2">Conectar calendario</Link>
        </> : <>
          <span>{synced ? `Última sincronización con Google: ${synced}.` : "Google Calendar aún no tiene una sincronización completa."}</span>
          <Link to="/settings#calendar" className="underline underline-offset-2">Revisar calendario</Link>
        </>}
      </div>}
    </section>
  )
}
