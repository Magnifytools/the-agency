import { Link, useLocation, Outlet } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { useAuth } from "@/context/auth-context"
import { inboxApi } from "@/lib/api"
import { inboxKeys } from "@/lib/query-keys"
import { LayoutDashboard, Users, CheckSquare, UserCog, LogOut, Clock, FolderKanban, FileText, ScrollText, Wallet, Newspaper, Target, MessageCircle, ClipboardList, Gauge, Search, Archive, Megaphone, Inbox, Settings, LayoutGrid, CalendarDays, Zap, Lightbulb, Bookmark } from "lucide-react"
import { cn } from "@/lib/utils"
import { BottomDrawer } from "@/components/ui/bottom-drawer"
import { ActiveTimerBar } from "@/components/timer/active-timer-bar"
import { DataAssistant } from "@/components/data-assistant"
import { NotificationBell } from "@/components/layout/notification-bell"
import { SearchPalette } from "@/components/layout/search-palette"
import { QuickCaptureDialog } from "@/components/inbox/quick-capture-dialog"
import { ShortcutsHelpModal } from "@/components/shortcuts/shortcuts-help-modal"
import { OnboardingModal } from "@/components/layout/onboarding-modal"
import { useKeyboardShortcuts } from "@/hooks/use-keyboard-shortcuts"
import { useMemo, useState, useCallback } from "react"

export function AppLayout() {
  const { user, logout, hasPermission, isAdmin } = useAuth()
  const location = useLocation()
  const [searchOpen, setSearchOpen] = useState(false)
  const [captureOpen, setCaptureOpen] = useState(false)
  const [moreDrawerOpen, setMoreDrawerOpen] = useState(false)

  const handleSearch = useCallback(() => setSearchOpen((o) => !o), [])
  const handleCapture = useCallback(() => setCaptureOpen((o) => !o), [])
  const userShortcuts = useMemo(() => user?.preferences?.shortcuts ?? {}, [user?.preferences?.shortcuts])
  const { shortcuts, isHelpOpen, setIsHelpOpen } = useKeyboardShortcuts({
    userOverrides: userShortcuts,
    onSearch: handleSearch,
    onCapture: handleCapture,
  })

  const { data: inboxCount } = useQuery({
    queryKey: inboxKeys.count(),
    queryFn: inboxApi.count,
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
    retry: false,
    staleTime: 10_000,
    // Si falla, simplemente no hay badge — no bloquear la shell
  })

  const workspaceNav = useMemo(() => {
    const items = [
      { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, module: "dashboard" },
      { to: "/my-week", label: "Mi Semana", icon: CalendarDays },
      { to: "/clients", label: "Clientes", icon: Users, module: "clients" },
      { to: "/projects", label: "Proyectos", icon: FolderKanban, module: "projects" },
      { to: "/leads", label: "Pipeline", icon: Target, module: "growth" },
      { to: "/growth", label: "Buffer", icon: Lightbulb, module: "growth" },
      { to: "/tasks", label: "Tareas", icon: CheckSquare, module: "tasks" },
      { to: "/inbox", label: "Inbox", icon: Inbox, module: "tasks" },
    ]
    return items.filter((item) => !item.module || hasPermission(item.module))
  }, [hasPermission, isAdmin])

  const opsNav = useMemo(() => {
    const items = [
      { to: "/timesheet", label: "Timesheet", icon: Clock, module: "timesheet" },
      { to: "/dailys", label: "Dailys", icon: ClipboardList },
      { to: "/digests", label: "Digests", icon: Newspaper, module: "digests" },
      { to: "/reports", label: "Informes", icon: FileText, module: "reports" },
      { to: "/proposals", label: "Presupuestos", icon: ScrollText, module: "proposals" },
    ]
    return items.filter((item) => !item.module || hasPermission(item.module))
  }, [hasPermission])

  // Keep mainNav as combined for backward compat (mobile nav, etc.)
  const mainNav = useMemo(() => [...workspaceNav, ...opsNav], [workspaceNav, opsNav])

  const agencyNav = useMemo(() => {
    const items: { to: string; label: string; icon: typeof Archive; adminOnly?: boolean }[] = [
      { to: "/resources", label: "Recursos", icon: Bookmark },
      { to: "/news", label: "Noticias", icon: Megaphone },
      { to: "/vault", label: "Vault", icon: Archive, adminOnly: true },
    ]
    return items.filter((item) => !item.adminOnly || isAdmin)
  }, [isAdmin])

  const adminNav = useMemo(() => {
    if (!isAdmin) return []
    return [
      { to: "/capacity", label: "Capacidad", icon: Gauge },
      { to: "/users", label: "Equipo", icon: UserCog },
      { to: "/discord", label: "Integraciones", icon: MessageCircle },
      { to: "/automations", label: "Automatizaciones", icon: Zap },
    ]
  }, [isAdmin])

  const mobileNav = useMemo(() => {
    const findMain = (path: string) => mainNav.find((item) => item.to === path)

    return [
      findMain("/dashboard"),
      findMain("/tasks"),
      findMain("/inbox"),
      { to: "/dailys", label: "Dailys", icon: ClipboardList },
    ].filter((item): item is { to: string; label: string; icon: typeof Wallet } => Boolean(item))
  }, [mainNav])

  const isActive = (path: string) => {
    if (path === "/finance-holded") {
      return location.pathname === "/finance-holded"
    }
    if (path === "/finance") {
      return location.pathname === "/finance"
    }
    if (path === "/clients") {
      return location.pathname === "/clients" || location.pathname.startsWith("/clients/")
    }
    if (path === "/leads") {
      return location.pathname === "/leads" || location.pathname.startsWith("/leads/")
    }
    if (path === "/growth") {
      return location.pathname === "/growth"
    }
    if (path === "/projects") {
      return location.pathname === "/projects" || location.pathname.startsWith("/projects/")
    }
    if (path === "/proposals") {
      return location.pathname === "/proposals" || location.pathname.startsWith("/proposals/")
    }
    if (path === "/dailys") {
      return location.pathname === "/dailys" || location.pathname.startsWith("/dailys/")
    }
    if (path === "/digests") {
      return location.pathname === "/digests" || location.pathname.startsWith("/digests/")
    }
    return location.pathname === path
  }

  return (
    <div className="flex h-screen flex-col bg-background overflow-hidden relative">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-[100] focus:top-4 focus:left-4 focus:px-4 focus:py-2 focus:bg-brand focus:text-black focus:rounded-lg focus:text-sm focus:font-semibold"
      >
        Ir al contenido
      </a>
      <ActiveTimerBar />

      <div className="flex flex-1 overflow-hidden pb-[60px] md:pb-0">
        {/* Sidebar (Desktop) */}
        <aside className="hidden md:flex w-[260px] flex-col flex-shrink-0 border-r border-border py-6 px-4 gap-6 bg-card/50" role="complementary" aria-label="Barra lateral">
          {/* Brand */}
          <div className="flex items-center gap-3 pl-1">
            <svg width="120" height="16" viewBox="300 610 2200 200" xmlns="http://www.w3.org/2000/svg">
              <path fill="currentColor" d="M772.2,645.1l-44,147h-26.6l62.8-166.8h7.8h7.8l62.8,166.8h-26.6L772.2,645.1z M1741.7,625.2h32.4v167.1h-32.4V625.2z M353.7,625.2v167.1h29.7V659.1l47.9,133.2h23.9l47.9-133.2v133.2h29.7V625.2c-15.1,0-30.3,0-45.4,0l-44.1,113.6l-44.1-113.6C384,625.2,368.8,625.2,353.7,625.2z M1376.2,625.2v167.1h30.1V666.5l72.6,125.8h34.2V625.2h-30.1v127.1l-72.6-127.1H1376.2z M1999.6,625.2v167.1h31.1v-73h66v-25.9h-66v-41.3h76v-27H1999.6z M2337.3,625.2l54.1,97.3v69.8h33.2v-69.8l54.1-97.3h-34l-36.7,70l-36.7-70H2337.3z M1077.2,703.4v24.2h43.6v27.8l-1.2,0.9c-9.3,6.8-20.2,11.1-31.6,12.6c-10.9,1.4-22.1,0.3-32.3-3.8c-10.3-4-19.1-10.8-25.3-20c-7.2-10.5-10.2-22.9-10.2-35.5c0-16,5.6-31.6,16.5-43.4c10.8-11.6,25.4-18.1,41.3-18.1c17.6,0,33.6,8.4,44.4,22.1h31c-11.4-30.9-43.9-47.7-75.8-47.7c-23.8,0-46.5,8.7-63.5,25.5c-16.5,16.3-25.5,38.4-25.5,61.6c0,31.2,14.5,59.3,42.4,74.2c9.5,5.1,20.2,8.3,30.9,9.9c11.4,1.7,23.1,1.7,34.4,0.1c21.4-3.1,43.2-12.2,57.4-29v-61.4H1077.2z"/>
            </svg>
          </div>

          {/* Search Button */}
          <button
            onClick={() => setSearchOpen(true)}
            className="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-[14px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-all group w-full"
          >
            <Search className="h-[18px] w-[18px] text-muted-foreground group-hover:text-foreground transition-colors" />
            <span className="flex-1 text-left">Buscar</span>
            <kbd className="hidden lg:inline-flex items-center px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground/60 bg-muted rounded border border-border">
              ⌘K
            </kbd>
          </button>

          {/* Main Nav */}
          <nav className="flex flex-col gap-1.5 flex-1 overflow-y-auto min-h-0" role="navigation" aria-label="Menu principal">
            <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70 px-3.5 mb-2">Workspace</p>
            {workspaceNav.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                aria-current={isActive(item.to) ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-[14px] font-medium transition-all group",
                  isActive(item.to)
                    ? "bg-brand/10 text-brand"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <item.icon className={cn("h-[18px] w-[18px] transition-colors", isActive(item.to) ? "text-brand" : "text-muted-foreground group-hover:text-foreground")} />
                {item.label}
                {item.to === "/inbox" && (inboxCount?.count ?? 0) > 0 && (
                  <span className="ml-auto text-[10px] font-semibold bg-brand/15 text-brand px-1.5 py-0.5 rounded-full min-w-[20px] text-center">
                    {inboxCount!.count}
                  </span>
                )}
              </Link>
            ))}

            {/* Operations Nav */}
            {opsNav.length > 0 && (
              <div className="mt-6 flex flex-col gap-1.5">
                <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70 px-3.5 mb-2">Operaciones</p>
                {opsNav.map((item) => (
                  <Link
                    key={item.to}
                    to={item.to}
                    aria-current={isActive(item.to) ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-[14px] font-medium transition-all group",
                      isActive(item.to)
                        ? "bg-brand/10 text-brand"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    )}
                  >
                    <item.icon className={cn("h-[18px] w-[18px] transition-colors", isActive(item.to) ? "text-brand" : "text-muted-foreground group-hover:text-foreground")} />
                    {item.label}
                  </Link>
                ))}
              </div>
            )}

            {/* Finance Nav — single entry */}
            {isAdmin && (
              <div className="mt-6 flex flex-col gap-1.5">
                <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70 px-3.5 mb-2">Finanzas</p>
                <Link
                  to="/finance"
                  aria-current={isActive("/finance") || isActive("/executive") || isActive("/billing") || isActive("/finance-holded") ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-[14px] font-medium transition-all group",
                    isActive("/finance") || isActive("/executive") || isActive("/billing") || isActive("/finance-holded")
                      ? "bg-brand/10 text-brand"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  <Wallet className={cn("h-[18px] w-[18px]", isActive("/finance") || isActive("/executive") || isActive("/billing") || isActive("/finance-holded") ? "text-brand" : "text-muted-foreground group-hover:text-foreground transition-colors")} />
                  Finanzas
                </Link>
              </div>
            )}

            {/* Agency Nav */}
            {agencyNav.length > 0 && (
              <div className="mt-8 flex flex-col gap-1.5">
                <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70 px-3.5 mb-2">La Agencia</p>
                {agencyNav.map((item) => (
                  <Link
                    key={item.to}
                    to={item.to}
                    aria-current={isActive(item.to) ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-[14px] font-medium transition-all group",
                      isActive(item.to)
                        ? "bg-brand/10 text-brand"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    )}
                  >
                    <item.icon className={cn("h-[18px] w-[18px] transition-colors", isActive(item.to) ? "text-brand" : "text-muted-foreground group-hover:text-foreground")} />
                    {item.label}
                  </Link>
                ))}
              </div>
            )}

            {/* Admin Nav */}
            {adminNav.length > 0 && (
              <div className="mt-8 flex flex-col gap-1.5">
                <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70 px-3.5 mb-2">Admin</p>
                {adminNav.map((item) => (
                  <Link
                    key={item.to}
                    to={item.to}
                    aria-current={isActive(item.to) ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-[14px] font-medium transition-all group",
                      isActive(item.to)
                        ? "bg-brand/10 text-brand"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    )}
                  >
                    <item.icon className={cn("h-[18px] w-[18px] transition-colors", isActive(item.to) ? "text-brand" : "text-muted-foreground group-hover:text-foreground")} />
                    {item.label}
                  </Link>
                ))}
              </div>
            )}

            {/* Settings */}
            <div className="mt-4">
              <Link
                to="/settings"
                aria-current={isActive("/settings") ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-[14px] font-medium transition-all group",
                  isActive("/settings")
                    ? "bg-brand/10 text-brand"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <Settings className={cn("h-[18px] w-[18px] transition-colors", isActive("/settings") ? "text-brand" : "text-muted-foreground group-hover:text-foreground")} />
                Configuración
              </Link>
            </div>
          </nav>

          {/* User info at bottom */}
          <div className="mt-auto border-t border-border pt-5 px-1">
            <div className="flex items-center justify-between">
              <div className="text-sm truncate pr-2">
                <p className="font-semibold text-foreground truncate">{user?.full_name}</p>
                <p className="text-muted-foreground text-[11px] mt-0.5 truncate">{user?.email}</p>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0">
                <NotificationBell />
                <button
                  onClick={() => void logout()}
                  className="p-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
                  title="Cerrar sesión"
                >
                  <LogOut className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        </aside>

        {/* Main content */}
        <main id="main-content" role="main" className="flex-1 overflow-auto p-4 md:p-5 lg:p-6 2xl:p-8 bg-background/50 relative">
          <Outlet />
        </main>
      </div>

      {/* Mobile Bottom Navigation */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 h-[60px] bg-card/95 backdrop-blur-md border-t border-border flex items-center justify-around px-2 z-50 shadow-[0_-4px_20px_-10px_rgba(0,0,0,0.3)]" aria-label="Navegacion movil">
        {mobileNav.map((item) => (
          <Link
            key={item.to}
            to={item.to}
            aria-current={isActive(item.to) ? "page" : undefined}
            className={cn(
              "flex flex-col items-center justify-center w-full h-full gap-1 transition-colors",
              isActive(item.to) ? "text-brand" : "text-muted-foreground"
            )}
          >
            <item.icon className={cn("h-5 w-5", isActive(item.to) && "fill-brand/10")} />
            <span className="text-[10px] font-medium tracking-tight">
              {item.label === "Dashboard" ? "Home" : item.label}
            </span>
          </Link>
        ))}
        <button
          onClick={() => setMoreDrawerOpen(true)}
          className={cn(
            "flex flex-col items-center justify-center w-full h-full gap-1 transition-colors",
            moreDrawerOpen ? "text-brand" : "text-muted-foreground"
          )}
        >
          <LayoutGrid className="h-5 w-5" />
          <span className="text-[10px] font-medium tracking-tight">Más</span>
        </button>
      </nav>

      {/* More drawer */}
      <BottomDrawer open={moreDrawerOpen} onOpenChange={setMoreDrawerOpen}>
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-4">
          {[...mainNav, ...agencyNav, ...(isAdmin ? [{ to: "/finance", label: "Finanzas", icon: Wallet }] : []), ...adminNav, { to: "/settings", label: "Ajustes", icon: Settings }]
            .filter((item) => !mobileNav.some((m) => m.to === item.to))
            .map((item) => (
              <Link
                key={item.to}
                to={item.to}
                onClick={() => setMoreDrawerOpen(false)}
                className="flex flex-col items-center gap-2 p-3 rounded-xl hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
              >
                <item.icon className="h-6 w-6" />
                <span className="text-[11px] font-medium text-center leading-tight">{item.label}</span>
              </Link>
            ))}
        </div>
      </BottomDrawer>

      <SearchPalette open={searchOpen} onOpenChange={setSearchOpen} />
      <QuickCaptureDialog open={captureOpen} onOpenChange={setCaptureOpen} />
      <ShortcutsHelpModal open={isHelpOpen} onOpenChange={setIsHelpOpen} shortcuts={shortcuts} />
      <DataAssistant />
      {user?.onboarding_completed === false && <OnboardingModal />}
    </div>
  )
}
