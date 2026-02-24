import { Link, useLocation, Outlet } from "react-router-dom"
import { useAuth } from "@/context/auth-context"
import { LayoutDashboard, Users, CheckSquare, UserCog, LogOut, Clock, CreditCard, FolderKanban, FileText, ScrollText, Rocket, Wallet, TrendingUp, Receipt, LineChart, Brain, Upload } from "lucide-react"
import { cn } from "@/lib/utils"
import { ActiveTimerBar } from "@/components/timer/active-timer-bar"
import { useMemo } from "react"

export function AppLayout() {
  const { user, logout, hasPermission, isAdmin } = useAuth()
  const location = useLocation()

  const mainNav = useMemo(() => {
    const items = [
      { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, module: "dashboard" },
      { to: "/clients", label: "Clientes", icon: Users, module: "clients" },
      { to: "/projects", label: "Proyectos", icon: FolderKanban, module: "projects" },
      { to: "/tasks", label: "Tareas", icon: CheckSquare, module: "tasks" },
      { to: "/growth", label: "Growth", icon: Rocket, module: "growth" },
      { to: "/timesheet", label: "Timesheet", icon: Clock, module: "timesheet" },
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
    return [{ to: "/users", label: "Equipo", icon: UserCog }]
  }, [isAdmin])

  const isActive = (path: string) => {
    if (path === "/finance") {
      return location.pathname === "/finance"
    }
    if (path === "/clients") {
      return location.pathname === "/clients" || location.pathname.startsWith("/clients/")
    }
    if (path === "/projects") {
      return location.pathname === "/projects" || location.pathname.startsWith("/projects/")
    }
    if (path === "/proposals") {
      return location.pathname === "/proposals" || location.pathname.startsWith("/proposals/")
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
          <div className="flex items-center gap-3">
            <svg width="28" height="28" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M46.17 33.4C44.05 28.29 41.14 24.01 37.23 20.1C33.32 16.19 28.68 13.09 23.57 10.97C18.46 8.86 12.99 7.77 7.45 7.77L7.45 49.88L7.45 92C12.99 92 18.46 90.91 23.57 88.79C28.68 86.67 33.32 83.57 37.23 79.66C41.14 75.75 44.03 71.56 46.15 66.45" stroke="#FFD600" strokeWidth="3"/>
              <circle cx="33.61" cy="49.88" r="26.09" stroke="#F0F0F0" strokeWidth="3"/>
              <circle cx="65.52" cy="49.88" r="26.09" stroke="#F0F0F0" strokeWidth="3"/>
              <path d="M53.01 66.45C55.13 71.56 57.99 75.75 61.9 79.66C65.81 83.57 70.46 86.67 75.57 88.79C80.68 90.91 86.15 92 91.68 92L91.68 49.88L91.68 7.77C86.15 7.77 80.68 8.86 75.57 10.97C70.46 13.09 65.81 16.19 61.9 20.1C58.16 23.84 55.16 28.25 53.06 33.1" stroke="#F0F0F0" strokeWidth="3"/>
              <circle cx="49.57" cy="49.88" r="4.78" stroke="#FFD600" strokeWidth="3" strokeLinecap="round" strokeLinejoin="bevel"/>
            </svg>
            <div className="flex flex-col">
              <span className="font-bold text-[16px] tracking-tight text-foreground">Magnify</span>
              <span className="text-[11px] text-muted-foreground font-medium uppercase tracking-wider">Agency Manager</span>
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
                <item.icon className={cn("h-[18px] w-[18px]", isActive(item.to) ? "text-brand" : "text-muted-foreground group-hover:text-foreground transition-colors")} />
                {item.label}
              </Link>
            ))}

            {/* Finance Nav */}
            {financeNav.length > 0 && (
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
            )}

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
          ...(financeNav.length > 0 ? [{ to: "/finance", label: "Finanzas", icon: Wallet }] : []),
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
