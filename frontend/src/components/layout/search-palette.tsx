import { useState, useEffect, useRef, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { searchApi } from "@/lib/api"
import { Building2, FolderKanban, CheckSquare, Target, Search } from "lucide-react"
import { useAuth } from "@/context/auth-context"
import { searchKeys } from "@/lib/query-keys"
import { isEnabled } from "@/lib/hidden-modules"
import { Dialog, DialogTitle } from "@/components/ui/dialog"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SearchPalette({ open, onOpenChange }: Props) {
  if (!open) return null
  return <SearchPaletteDialog onOpenChange={onOpenChange} />
}

function SearchPaletteDialog({ onOpenChange }: Omit<Props, "open">) {
  const [query, setQuery] = useState("")
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()
  const { user, hasPermission } = useAuth()
  const normalizedQuery = query.trim()
  const searchableTypes = ["clients", "projects", "tasks", "leads"].filter(
    (module) => isEnabled(module) && hasPermission(module),
  )
  const permissionSignature = searchableTypes.join(",")
  const searchTargetLabels: Record<string, string> = {
    clients: "clientes",
    projects: "proyectos",
    tasks: "tareas",
    leads: "leads",
  }
  const searchPlaceholder = searchableTypes.length > 0
    ? `Buscar ${searchableTypes.map((module) => searchTargetLabels[module]).join(", ")}...`
    : "Buscar..."

  useEffect(() => {
    const frame = requestAnimationFrame(() => inputRef.current?.focus())
    return () => cancelAnimationFrame(frame)
  }, [])

  const { data: results, isLoading, isError, refetch } = useQuery({
    queryKey: searchKeys.results(user?.id ?? 0, permissionSignature, normalizedQuery),
    queryFn: () => searchApi.search(normalizedQuery),
    enabled: !!user && normalizedQuery.length >= 2,
    staleTime: 10_000,
  })

  // Build flat list of all results for keyboard nav
  const allItems: { type: string; id: number; label: string; sub: string | null; href: string }[] = []
  if (results && !isError) {
    if (searchableTypes.includes("clients")) {
      for (const c of results.clients) allItems.push({ type: "client", id: c.id, label: c.name, sub: c.company, href: `/clients/${c.id}` })
    }
    if (searchableTypes.includes("projects")) {
      for (const p of results.projects) allItems.push({ type: "project", id: p.id, label: p.name, sub: p.client_name, href: `/projects/${p.id}` })
    }
    if (searchableTypes.includes("tasks")) {
      for (const t of results.tasks) allItems.push({ type: "task", id: t.id, label: t.title, sub: t.client_name, href: `/tasks?id=${t.id}` })
    }
    if (searchableTypes.includes("leads")) {
      for (const l of results.leads) allItems.push({ type: "lead", id: l.id, label: l.company_name, sub: l.contact_name, href: `/leads/${l.id}` })
    }
  }
  const activeIndex = Math.min(selectedIndex, Math.max(allItems.length - 1, 0))

  const handleNavigate = useCallback((href: string) => {
    onOpenChange(false)
    navigate(href)
  }, [navigate, onOpenChange])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault()
      setSelectedIndex((i) => Math.min(i + 1, Math.max(allItems.length - 1, 0)))
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setSelectedIndex((i) => Math.max(i - 1, 0))
    } else if (e.key === "Enter" && allItems[activeIndex]) {
      e.preventDefault()
      handleNavigate(allItems[activeIndex].href)
    }
  }

  const sectionIcon = (type: string) => {
    switch (type) {
      case "client": return Building2
      case "project": return FolderKanban
      case "task": return CheckSquare
      case "lead": return Target
      default: return Search
    }
  }

  const sectionLabel = (type: string) => {
    switch (type) {
      case "client": return "Clientes"
      case "project": return "Proyectos"
      case "task": return "Tareas"
      case "lead": return "Pipeline"
      default: return type
    }
  }

  // Group items by type for section headers
  const sections: { type: string; items: typeof allItems }[] = []
  for (const type of ["client", "project", "task", "lead"]) {
    const items = allItems.filter((i) => i.type === type)
    if (items.length > 0) sections.push({ type, items })
  }

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogTitle className="sr-only">Búsqueda global</DialogTitle>
      <div className="-m-6 overflow-hidden rounded-[16px]">
        <div className="flex items-center gap-3 px-4 py-3 pr-14 border-b border-border">
          <Search className="h-5 w-5 text-muted-foreground shrink-0" />
          <input
            ref={inputRef}
            value={query}
            aria-label="Buscar"
            onChange={(e) => { setQuery(e.target.value); setSelectedIndex(0) }}
            onKeyDown={handleKeyDown}
            placeholder={searchPlaceholder}
            className="min-w-0 flex-1 bg-transparent text-foreground placeholder:text-muted-foreground text-sm outline-none"
          />
          <kbd className="hidden sm:inline-flex items-center px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground bg-muted rounded border border-border">
            ESC
          </kbd>
        </div>

        {normalizedQuery.length >= 2 && (
          <div className="max-h-[50vh] overflow-y-auto p-2">
            {isLoading ? <p role="status" className="text-sm text-muted-foreground text-center py-8">Buscando…</p> : isError ? (
              <div role="alert" className="text-center py-8 text-sm text-muted-foreground">No se pudo buscar. <button type="button" className="underline" onClick={() => void refetch()}>Reintentar</button></div>
            ) : allItems.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">Sin resultados para &quot;{query}&quot;</p>
            ) : (
              sections.map((section) => {
                const Icon = sectionIcon(section.type)
                return (
                  <div key={section.type} className="mb-2">
                    <div className="flex items-center gap-2 px-3 py-1.5">
                      <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                        {sectionLabel(section.type)}
                      </span>
                    </div>
                    {section.items.map((item) => {
                      const idx = allItems.indexOf(item)
                      const isSelected = idx === activeIndex
                      return (
                        <button
                          key={`${item.type}-${item.id}`}
                          className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-left transition-colors ${
                            isSelected ? "bg-brand/10 text-brand" : "text-foreground hover:bg-muted"
                          }`}
                          onClick={() => handleNavigate(item.href)}
                          onMouseEnter={() => setSelectedIndex(idx)}
                        >
                          <span className="font-medium truncate">{item.label}</span>
                          {item.sub && <span className="text-xs text-muted-foreground truncate ml-auto">{item.sub}</span>}
                        </button>
                      )
                    })}
                  </div>
                )
              })
            )}
          </div>
        )}

        {normalizedQuery.length < 2 && (
          <div className="p-6 text-center">
            <p className="text-sm text-muted-foreground">Escribe al menos 2 caracteres para buscar</p>
          </div>
        )}
      </div>
    </Dialog>
  )
}
