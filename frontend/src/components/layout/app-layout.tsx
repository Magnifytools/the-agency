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
          <div className="flex flex-col gap-1.5 pl-1">
            <svg height="20" viewBox="0 0 447.5208 54.6848" xmlns="http://www.w3.org/2000/svg">
              <g fill="#F0F0F0"><polygon points="63.0249 .7853 63.0249 11.9133 53.5808 11.9133 36.0752 53.8803 26.9488 53.8803 9.4441 11.9133 0 11.9133 0 .7853 14.3999 .7853 31.4371 41.3314 31.5869 41.3314 48.625 .7853 63.0249 .7853"/><rect x="53.7488" y="11.5207" width="9.2761" height="42.3597"/><rect y="11.5207" width="9.2761" height="42.3597"/><path d="M180.9396,33.9812h13.6708v19.7685c3.497-.7488,6.527-2.0017,9.2761-3.7778v-24.3125h-22.9468v8.3218ZM184.7731,0c-17.7476,0-29.1934,10.6979-29.1934,27.3424,0,16.6263,11.4458,27.3424,29.1934,27.3424.5233,0,1.0287,0,1.5337-.0192v-8.5647c-.3927.0183-.8041.0183-1.2159.0183-11.9873,0-19.8242-7.3502-19.8242-18.7768,0-11.4458,7.8369-18.7951,19.8242-18.7951,7.5931,0,13.5214,2.0757,18.3092,6.6388h.4863V4.7129c-5.0494-3.2911-11.0339-4.7129-19.1133-4.7129Z"/><path d="M266.8339.7853v39.6667h-.1498L242.1283.7853h-10.1737l6.4146,10.4733,26.1452,42.6217h11.5956V.7853h-9.2761ZM228.9251,11.5207v42.3597h9.2761v-27.2301l-9.2761-15.1296Z"/><path d="M302.0459.7853v53.095h9.5939V.7853h-9.5939Z"/><path d="M347.1512,23.7326v-14.3817l-9.5939-3.7212v48.2506h9.5939v-21.5821h23.9198v-8.5656h-23.9198ZM337.5573.7853v8.5656h39.274V.7853h-39.274Z"/><path d="M436.3371.7853l-10.8472,15.598,5.2553,7.5556L447.5208.7853h-11.1837Z"/><polygon points="425.4469 29.7733 425.4469 53.8803 415.8531 53.8803 415.8531 31.4198 393.6345 .7853 405.3049 .7853 420.8089 23.097 425.4469 29.7733"/><line x1="194.6044" y1="44.7723" x2="204.3891" y2="40.8173" stroke="#F0F0F0" strokeWidth="1"/></g>
              <g fill="#FFD600"><path d="M124.2013,17.6171h-9.5564l.9725,2.3377,6.5265,15.5414h-.0557l3.5714,8.3976.599,1.4209,3.6281,8.5656h10.3235l-16.009-36.2633Z"/><polygon points="121.5768 11.6704 111.9829 11.6704 94.2353 53.8803 84.2296 53.8803 93.0189 33.8698 107.4755 1.0292 107.5878 .7853 116.7707 .7853 120.3057 8.7903 121.5768 11.6704"/></g>
            </svg>
            <span className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider">Agency Manager</span>
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
                <item.icon className={cn("h-[18px] w-[18px]", isActive(item.to) ? "text-brand" : "text-muted-foreground group-hover:text-foreground transition-colors")} />
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
                    <item.icon className={cn("h-[18px] w-[18px]", isActive(item.to) ? "text-brand" : "text-muted-foreground group-hover:text-foreground transition-colors")} />
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
                    <item.icon className={cn("h-[18px] w-[18px]", isActive(item.to) ? "text-brand" : "text-muted-foreground group-hover:text-foreground transition-colors")} />
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
