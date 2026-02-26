import { useState, useRef, useEffect } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { notificationsApi } from "@/lib/api"
import { Bell, CheckCheck } from "lucide-react"
import { useNavigate } from "react-router-dom"

export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const { data: unread } = useQuery({
    queryKey: ["notifications-unread-count"],
    queryFn: () => notificationsApi.unreadCount(),
    refetchInterval: 60_000,
  })

  const { data: notifications } = useQuery({
    queryKey: ["notifications-list"],
    queryFn: () => notificationsApi.list({ limit: 20 }),
    enabled: open,
  })

  const markReadMutation = useMutation({
    mutationFn: (id: number) => notificationsApi.markRead(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications-unread-count"] })
      queryClient.invalidateQueries({ queryKey: ["notifications-list"] })
    },
  })

  const markAllReadMutation = useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications-unread-count"] })
      queryClient.invalidateQueries({ queryKey: ["notifications-list"] })
    },
  })

  // Close on click outside
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [open])

  const count = unread?.count || 0

  const handleNotifClick = (notif: { id: number; link_url: string | null; is_read: boolean }) => {
    if (!notif.is_read) markReadMutation.mutate(notif.id)
    if (notif.link_url) navigate(notif.link_url)
    setOpen(false)
  }

  const formatTime = (ts: string) => {
    const d = new Date(ts)
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    const diffMin = Math.floor(diffMs / 60000)
    if (diffMin < 1) return "ahora"
    if (diffMin < 60) return `${diffMin}m`
    const diffH = Math.floor(diffMin / 60)
    if (diffH < 24) return `${diffH}h`
    const diffD = Math.floor(diffH / 24)
    return `${diffD}d`
  }

  return (
    <div className="relative" ref={panelRef}>
      <button
        onClick={() => setOpen(!open)}
        className="relative p-2 text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg transition-colors"
        title="Notificaciones"
      >
        <Bell className="h-4 w-4" />
        {count > 0 && (
          <span className="absolute -top-0.5 -right-0.5 h-4 min-w-[16px] flex items-center justify-center rounded-full bg-red-500 text-[9px] font-bold text-white px-1">
            {count > 99 ? "99+" : count}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 max-h-[400px] overflow-auto rounded-xl border border-border bg-card shadow-xl z-50">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border">
            <span className="text-sm font-semibold">Notificaciones</span>
            {count > 0 && (
              <button
                onClick={() => markAllReadMutation.mutate()}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-brand transition-colors"
              >
                <CheckCheck className="h-3 w-3" />
                Marcar todas
              </button>
            )}
          </div>

          {!notifications || notifications.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">
              Sin notificaciones
            </div>
          ) : (
            <div>
              {notifications.map((n) => (
                <button
                  key={n.id}
                  onClick={() => handleNotifClick(n)}
                  className={`w-full text-left px-3 py-2.5 border-b border-border/50 hover:bg-muted/50 transition-colors flex items-start gap-2 ${
                    !n.is_read ? "bg-brand/5" : ""
                  }`}
                >
                  {!n.is_read && (
                    <div className="w-1.5 h-1.5 rounded-full bg-brand mt-1.5 flex-shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm truncate ${!n.is_read ? "font-medium" : "text-muted-foreground"}`}>
                      {n.title}
                    </p>
                    {n.message && (
                      <p className="text-xs text-muted-foreground truncate mt-0.5">{n.message}</p>
                    )}
                  </div>
                  <span className="text-[10px] text-muted-foreground/70 flex-shrink-0 mt-0.5">
                    {formatTime(n.created_at)}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
