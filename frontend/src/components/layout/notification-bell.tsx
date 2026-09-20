import { useState, useRef, useEffect, useId } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { notificationsApi } from "@/lib/api"
import { incidentKeys, incidentsApi } from "@/lib/incidents-api"
import { IncidentInbox } from "@/components/incidents/incident-inbox"
import { useAuth } from "@/context/auth-context"
import { Bell, CheckCheck, X } from "lucide-react"
import { formatTimeAgo } from "@/lib/utils"
import { useNavigate } from "react-router-dom"

export function NotificationBell({ onNavigate }: { onNavigate?: () => void } = {}) {
  const { user } = useAuth()
  return user ? <RecipientBell key={user.id} userId={user.id} onNavigate={onNavigate} /> : null
}

function RecipientBell({ userId, onNavigate }: { userId: number; onNavigate?: () => void }) {
  const [open, setOpen] = useState(false)
  const [view, setView] = useState<"incidents" | "activity">("incidents")
  const [position, setPosition] = useState<{ left: number; top?: number; bottom?: number; maxHeight?: number }>({ left: 16, top: 56 })
  const panelRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const panelId = useId()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const closeForNavigation = () => { setOpen(false); onNavigate?.() }
  const toggle = () => {
    if (!open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      const width = Math.min(384, window.innerWidth - 32)
      const above = rect.top > window.innerHeight / 2
      setPosition({
        left: Math.max(16, Math.min(rect.left, window.innerWidth - width - 16)),
        maxHeight: Math.min(512, above ? rect.top - 24 : window.innerHeight - rect.bottom - 24),
        ...(above ? { bottom: window.innerHeight - rect.top + 8 } : { top: rect.bottom + 8 }),
      })
    }
    setOpen(!open)
  }

  const pendingQuery = useQuery({
    queryKey: incidentKeys.count(userId), queryFn: incidentsApi.count,
    refetchInterval: 30_000, refetchIntervalInBackground: false,
  })
  const unreadQuery = useQuery({
    queryKey: ["notifications-unread-count", userId],
    queryFn: () => notificationsApi.unreadCount(),
    refetchInterval: 60_000, refetchIntervalInBackground: false,
  })
  const activityQuery = useQuery({
    queryKey: ["notifications-list", userId],
    queryFn: () => notificationsApi.list({ limit: 20 }),
    enabled: open && view === "activity",
  })
  const refreshActivity = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ["notifications-unread-count", userId] }),
    queryClient.invalidateQueries({ queryKey: ["notifications-list", userId] }),
  ])
  const readMutation = useMutation({
    mutationFn: (id: number | "all") => id === "all" ? notificationsApi.markAllRead() : notificationsApi.markRead(id),
    onSuccess: refreshActivity,
  })

  useEffect(() => {
    if (!open) return
    closeRef.current?.focus()
    function outside(event: MouseEvent) {
      if (!panelRef.current?.contains(event.target as Node)) setOpen(false)
    }
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    function resize() { setOpen(false) }
    window.addEventListener("resize", resize)
    document.addEventListener("mousedown", outside)
    document.addEventListener("keydown", escape)
    return () => {
      window.removeEventListener("resize", resize)
      document.removeEventListener("mousedown", outside)
      document.removeEventListener("keydown", escape)
    }
  }, [open])

  const count = pendingQuery.data?.count ?? 0
  const unread = unreadQuery.data?.count ?? 0
  return (
    <div className="relative" ref={panelRef}>
      <button ref={triggerRef} type="button" aria-label="Alertas y actividad" aria-expanded={open} aria-controls={open ? panelId : undefined}
        onClick={toggle} className="relative rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground">
        <Bell className="h-4 w-4" aria-hidden="true" />
        {!pendingQuery.isError && count > 0 && <span aria-label={`${count} alertas pendientes`} className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-destructive px-1 text-[10px] font-bold text-destructive-foreground">{count > 99 ? "99+" : count}</span>}
      </button>
      {open && <div id={panelId} role="dialog" aria-label="Alertas y actividad" style={position} className="fixed z-50 max-h-[min(32rem,calc(100dvh-8rem))] w-96 max-w-[calc(100vw-2rem)] overflow-auto rounded-xl border border-border bg-card shadow-xl">
        <div className="flex items-center gap-2 border-b border-border p-3">
          <button type="button" aria-pressed={view === "incidents"} onClick={() => setView("incidents")} className={`rounded px-2 py-1 text-sm ${view === "incidents" ? "bg-muted font-semibold" : "text-muted-foreground"}`}>Alertas</button>
          <button type="button" aria-pressed={view === "activity"} onClick={() => setView("activity")} className={`rounded px-2 py-1 text-sm ${view === "activity" ? "bg-muted font-semibold" : "text-muted-foreground"}`}>Actividad{unread > 0 ? ` (${unread})` : ""}</button>
          <button ref={closeRef} type="button" aria-label="Cerrar notificaciones" onClick={() => { setOpen(false); triggerRef.current?.focus() }} className="ml-auto rounded p-2 hover:bg-muted"><X className="h-4 w-4" /></button>
        </div>
        {view === "incidents" ? <div className="p-3"><IncidentInbox userId={userId} compact onNavigate={closeForNavigation} /></div> : <>
          {unread > 0 && <button type="button" disabled={readMutation.isPending} onClick={() => readMutation.mutate("all")} className="flex items-center gap-2 p-3 text-xs text-muted-foreground hover:text-foreground"><CheckCheck className="h-4 w-4" />Marcar actividad como leída</button>}
          {readMutation.isError && <p role="alert" className="px-3 py-2 text-sm text-destructive">No se pudo marcar como leída. Puedes volver a intentarlo.</p>}
          {activityQuery.isPending ? <p className="p-5 text-sm text-muted-foreground">Cargando actividad…</p>
            : activityQuery.isError ? <div role="alert" className="p-5 text-sm">No se pudo cargar la actividad. <button type="button" className="underline" onClick={() => void activityQuery.refetch()}>Reintentar</button></div>
            : !activityQuery.data?.length ? <p className="p-5 text-sm text-muted-foreground">Sin actividad reciente.</p>
            : activityQuery.data.map(item => <button type="button" key={item.id} onClick={() => {
              if (!item.is_read) readMutation.mutate(item.id)
              if (item.link_url?.startsWith("/") && !item.link_url.startsWith("//")) navigate(item.link_url)
              closeForNavigation()
            }} className={`w-full border-t border-border/50 p-3 text-left hover:bg-muted/50 ${!item.is_read ? "bg-brand/5" : ""}`}>
              <p className="break-words text-sm font-medium">{item.title}</p>
              {item.message && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{item.message}</p>}
              <span className="mt-1 block text-xs text-muted-foreground">{formatTimeAgo(item.created_at)}</span>
            </button>)}
        </>}
      </div>}
    </div>
  )
}
