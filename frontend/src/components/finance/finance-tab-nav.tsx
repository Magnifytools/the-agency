import { Link, useLocation } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { holdedApi } from "@/lib/api"
import { holdedKeys } from "@/lib/query-keys"
import { useAuth } from "@/context/auth-context"
import { cn } from "@/lib/utils"

const TABS = [
  { to: "/finance", label: "Dashboard", exact: true },
  { to: "/executive", label: "Ejecutivo" },
  { to: "/finance/income", label: "Ingresos" },
  { to: "/finance/expenses", label: "Gastos" },
  { to: "/finance/taxes", label: "Impuestos" },
  { to: "/finance/forecasts", label: "Previsiones" },
  { to: "/finance-holded", label: "Holded", holdedOnly: true },
  { to: "/billing", label: "Facturación" },
  { to: "/finance/advisor", label: "Asesor" },
]

export function FinanceTabNav() {
  const { pathname } = useLocation()
  const { isAdmin } = useAuth()

  const { data: holdedConfig } = useQuery({
    queryKey: holdedKeys.config(),
    queryFn: holdedApi.config,
    staleTime: 5 * 60_000,
    retry: false,
    enabled: isAdmin,
  })
  const holdedEnabled = isAdmin && (holdedConfig?.api_key_configured ?? false)

  const visibleTabs = TABS.filter((t) => {
    if ("holdedOnly" in t && t.holdedOnly && !holdedEnabled) return false
    return true
  })

  const isActive = (tab: typeof TABS[number]) => {
    if (tab.exact) return pathname === tab.to
    return pathname.startsWith(tab.to)
  }

  return (
    <nav className="flex items-center gap-1 overflow-x-auto pb-4 mb-2 -mt-1 scrollbar-none">
      {visibleTabs.map((tab) => (
        <Link
          key={tab.to}
          to={tab.to}
          className={cn(
            "px-3 py-1.5 rounded-md text-sm font-medium whitespace-nowrap transition-colors",
            isActive(tab)
              ? "bg-brand/10 text-brand"
              : "text-muted-foreground hover:bg-muted hover:text-foreground"
          )}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  )
}
