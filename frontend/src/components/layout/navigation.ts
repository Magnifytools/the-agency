import { CalendarDays, CheckSquare, Users, ClipboardList, Settings, type LucideIcon } from "lucide-react"
import { isHidden } from "@/lib/hidden-modules"

export type AreaId = "today" | "work" | "clients" | "summaries" | "settings"
export interface AreaLink { to: string; label: string; mobileLabel?: string; module?: string; hidden?: string; admin?: boolean }
export interface NavigationArea { id: AreaId; label: string; icon: LucideIcon; links: AreaLink[] }

const areas: NavigationArea[] = [
  { id: "today", label: "Hoy", icon: CalendarDays, links: [
    { to: "/tasks?view=my_day", label: "Mi agenda", module: "tasks" },
    { to: "/incidents", label: "Alertas" },
    { to: "/dashboard", label: "Visión general", module: "dashboard" },
  ] },
  { id: "work", label: "Trabajo", icon: CheckSquare, links: [
    { to: "/tasks?view=all", label: "Tareas", module: "tasks" },
    { to: "/projects", label: "Proyectos", module: "projects" },
    { to: "/timesheet", label: "Horas", module: "timesheet" },
    { to: "/inbox", label: "Por aclarar", module: "tasks" },
    { to: "/my-week", label: "Mi semana", hidden: "my_week" },
    { to: "/leads", label: "Pipeline", module: "growth", hidden: "leads" },
    { to: "/growth", label: "Ideas", module: "growth", hidden: "growth" },
    { to: "/proposals", label: "Presupuestos", module: "proposals", hidden: "proposals" },
  ] },
  { id: "clients", label: "Clientes", icon: Users, links: [
    { to: "/clients", label: "Clientes", module: "clients" },
  ] },
  { id: "summaries", label: "Resúmenes", icon: ClipboardList, links: [
    { to: "/dailys", label: "Mi resumen diario", mobileLabel: "Diario" },
    { to: "/digests", label: "Resúmenes de clientes", mobileLabel: "Clientes", module: "digests" },
    { to: "/reports", label: "Informes", mobileLabel: "Informes", module: "reports", hidden: "reports" },
  ] },
  { id: "settings", label: "Ajustes", icon: Settings, links: [
    { to: "/settings", label: "Preferencias" },
    { to: "/users", label: "Equipo y permisos", admin: true },
    { to: "/capacity", label: "Capacidad", admin: true, hidden: "capacity" },
    { to: "/discord", label: "Integraciones", admin: true, hidden: "discord" },
    { to: "/automations", label: "Automatizaciones", admin: true, hidden: "automations" },
    { to: "/vault", label: "Vault", admin: true, hidden: "vault" },
    { to: "/finance", label: "Finanzas", admin: true, hidden: "finance" },
  ] },
]

export function navigationFor(canRead: (module: string) => boolean, isAdmin: boolean): NavigationArea[] {
  return areas.map((area) => ({ ...area, links: area.links.filter((link) =>
    (!link.hidden || !isHidden(link.hidden)) && (!link.admin || isAdmin) && (!link.module || canRead(link.module)),
  ) })).filter((area) => area.links.length > 0)
}

export function activeArea(pathname: string, search: string): AreaId {
  if (pathname === "/tasks") {
    const params = new URLSearchParams(search)
    return params.has("qaFilter") || (params.has("view") && params.get("view") !== "my_day") ? "work" : "today"
  }
  if (pathname === "/dashboard" || pathname === "/incidents" || pathname.startsWith("/deliveries/")) return "today"
  if (pathname.startsWith("/clients")) return "clients"
  if (["/dailys", "/digests", "/reports"].some((path) => pathname === path || pathname.startsWith(path + "/"))) return "summaries"
  if (["/projects", "/timesheet", "/inbox", "/my-week", "/leads", "/growth", "/proposals"].some((path) => pathname === path || pathname.startsWith(path + "/"))) return "work"
  return "settings"
}

export function activeAreaLink(to: string, pathname: string, search: string): boolean {
  const [path, query] = to.split("?")
  if (path === "/tasks") return pathname === path && activeArea(pathname, search) === (query === "view=my_day" ? "today" : "work")
  return pathname === path || pathname.startsWith(path + "/")
}
