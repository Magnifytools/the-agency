import { Link, useLocation, Outlet } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { useAuth } from "@/context/auth-context"
import { holdedApi } from "@/lib/api"
import { LayoutDashboard, Users, CheckSquare, UserCog, LogOut, Clock, CreditCard, FolderKanban, FileText, ScrollText, Rocket, Wallet, TrendingUp, Receipt, LineChart, Brain, Upload, Newspaper, Target, MessageCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import { ActiveTimerBar } from "@/components/timer/active-timer-bar"
import { useMemo } from "react"

export function AppLayout() {
  const { user, logout, hasPermission, isAdmin } = useAuth()
  const location = useLocation()

  const { data: holdedConfig } = useQuery({
    queryKey: ["holded-config"],
    queryFn: holdedApi.config,
    staleTime: 5 * 60_000,
    retry: false,
  })
  const holdedEnabled = holdedConfig?.api_key_configured ?? false

  const mainNav = useMemo(() => {
    const items = [
      { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, module: "dashboard" },
      { to: "/clients", label: "Clientes", icon: Users, module: "clients" },
      { to: "/leads", label: "Pipeline", icon: Target, module: "leads" },
      { to: "/projects", label: "Proyectos", icon: FolderKanban, module: "projects" },
      { to: "/tasks", label: "Tareas", icon: CheckSquare, module: "tasks" },
      { to: "/growth", label: "Growth", icon: Rocket, module: "growth" },
      { to: "/timesheet", label: "Timesheet", icon: Clock, module: "timesheet" },
      { to: "/digests", label: "Digests", icon: Newspaper, module: "digests" },
      { to: "/reports", label: "Informes", icon: FileText, module: "reports" },
      { to: "/proposals", label: "Presupuestos", icon: ScrollText, module: "proposals" },
      { to: "/billing", label: "Facturacion", icon: CreditCard, module: "billing" },
    ]
    return items.filter((item) => hasPermission(item.module))
  }, [hasPermission])

  const financeNav = useMemo(() => {
    const items = [
      { to: "/finance", label: "Resumen", icon: Wallet, module: "finance_dashboard" },
      { to: "/finance/income", label: "Ingresos", icon: TrendingUp, module: "finance_income" },
      { to: "/finance/expenses", label: "Gastos", icon: Receipt, module: "finance_expenses" },
      { to: "/finance/taxes", label: "Impuestos", icon: CreditCard, module: "finance_taxes" },
      { to: "/finance/forecasts", label: "Previsiones", icon: LineChart, module: "finance_forecasts" },
      { to: "/finance/advisor", label: "Asesor", icon: Brain, module: "finance_advisor" },
      { to: "/finance/import", label: "Importar", icon: Upload, module: "finance_import" },
    ]
    return items.filter((item) => hasPermission(item.module))
  }, [hasPermission])

  const adminNav = useMemo(() => {
    if (!isAdmin) return []
    return [
      { to: "/users", label: "Equipo", icon: UserCog },
      { to: "/discord", label: "Discord", icon: MessageCircle },
    ]
  }, [isAdmin])

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
    if (path === "/projects") {
      return location.pathname === "/projects" || location.pathname.startsWith("/projects/")
    }
    if (path === "/proposals") {
      return location.pathname === "/proposals" || location.pathname.startsWith("/proposals/")
    }
    if (path === "/digests") {
      return location.pathname === "/digests" || location.pathname.startsWith("/digests/")
    }
    return location.pathname === path
  }

  return (
    <div className="flex h-screen flex-col bg-background overflow-hidden relative">
      <ActiveTimerBar />

      <div className="flex flex-1 overflow-hidden pb-[60px] md:pb-0">
        {/* Sidebar (Desktop) */}
        <aside className="hidden md:flex w-[260px] flex-col flex-shrink-0 border-r border-border py-8 px-5 gap-10 bg-card/50">
          {/* Brand */}
          <div className="flex items-center gap-3 pl-1">
            <svg width="28" height="28" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
              <rect width="100" height="100" rx="20" fill="#0A0A0A"/>
              <path d="M50 18 L74 80 L65 80 L59 63 L41 63 L35 80 L26 80 Z M50 32 L43 56 L57 56 Z" fill="#FFD600" fillRule="evenodd"/>
            </svg>
            <div className="flex flex-col">
              <span className="text-[15px] font-semibold text-foreground tracking-tight leading-tight">The Agency</span>
              <span className="text-[10px] text-muted-foreground font-medium tracking-wider">by Magnify</span>
            </div>
          </div>

          {/* Main Nav */}
          <div className="flex flex-col gap-1.5 flex-1">
            <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70 px-3.5 mb-2">Workspace</p>
            {mainNav.map((item) => (
              <Link
                key={item.to}
                to={item.to}
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

            {/* Finance Nav */}
            {holdedEnabled ? (
              <div className="mt-8 flex flex-col gap-1.5">
                <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70 px-3.5 mb-2">Finanzas</p>
                <Link
                  to="/finance-holded"
                  className={cn(
                    "flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-[14px] font-medium transition-all group",
                    isActive("/finance-holded")
                      ? "bg-brand/10 text-brand"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  <Wallet className={cn("h-[18px] w-[18px]", isActive("/finance-holded") ? "text-brand" : "text-muted-foreground group-hover:text-foreground transition-colors")} />
                  Finanzas (Holded)
                </Link>
              </div>
            ) : financeNav.length > 0 ? (
              <div className="mt-8 flex flex-col gap-1.5">
                <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70 px-3.5 mb-2">Finanzas</p>
                {financeNav.map((item) => (
                  <Link
                    key={item.to}
                    to={item.to}
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
            ) : null}

            {/* Admin Nav */}
            {adminNav.length > 0 && (
              <div className="mt-8 flex flex-col gap-1.5">
                <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70 px-3.5 mb-2">Admin</p>
                {adminNav.map((item) => (
                  <Link
                    key={item.to}
                    to={item.to}
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
          </div>

          {/* User info at bottom */}
          <div className="mt-auto border-t border-border pt-5 px-1">
            <div className="flex items-center justify-between">
              <div className="text-sm truncate pr-2">
                <p className="font-semibold text-foreground truncate">{user?.full_name}</p>
                <p className="text-muted-foreground text-[11px] mt-0.5 truncate">{user?.email}</p>
              </div>
              <button
                onClick={logout}
                className="p-2 text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-lg transition-colors flex-shrink-0"
                title="Cerrar sesion"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          </div>
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-auto p-4 md:p-8 lg:px-10 bg-background/50 relative">
          <Outlet />
        </main>
      </div>

      {/* Mobile Bottom Navigation */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 h-[60px] bg-card/95 backdrop-blur-md border-t border-border flex items-center justify-around px-2 z-50 shadow-[0_-4px_20px_-10px_rgba(0,0,0,0.3)]">
        {[
          ...mainNav.slice(0, 3),
          ...(holdedEnabled
            ? [{ to: "/finance-holded", label: "Finanzas", icon: Wallet }]
            : financeNav.length > 0
              ? [{ to: "/finance", label: "Finanzas", icon: Wallet }]
              : []),
          ...mainNav.slice(3, 4),
        ].slice(0, 5).map((item) => (
          <Link
            key={item.to}
            to={item.to}
            className={cn(
              "flex flex-col items-center justify-center w-full h-full gap-1 transition-colors",
              isActive(item.to) || (item.to === "/finance" && location.pathname.startsWith("/finance")) ? "text-brand" : "text-muted-foreground"
            )}
          >
            <item.icon className={cn("h-5 w-5", (isActive(item.to) || (item.to === "/finance" && location.pathname.startsWith("/finance"))) && "fill-brand/10")} />
            <span className="text-[10px] font-medium tracking-tight">
              {item.label === "Dashboard" ? "Home" : item.label}
            </span>
          </Link>
        ))}
      </nav>
    </div>
  )
}
