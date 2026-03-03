import { useState, useEffect, useRef, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { searchApi } from "@/lib/api"
import { Building2, FolderKanban, CheckSquare, Target, Search } from "lucide-react"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function SearchPalette({ open, onOpenChange }: Props) {
  const [query, setQuery] = useState("")
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  const { data: results } = useQuery({
    queryKey: ["global-search", query],
    queryFn: () => searchApi.search(query),
    enabled: query.length >= 2,
    staleTime: 10_000,
  })

  // Build flat list of all results for keyboard nav
  const allItems: { type: string; id: number; label: string; sub: string | null; href: string }[] = []
  if (results) {
    for (const c of results.clients) {
      allItems.push({ type: "client", id: c.id, label: c.name, sub: c.company, href: `/clients/${c.id}` })
    }
    for (const p of results.projects) {
      allItems.push({ type: "project", id: p.id, label: p.name, sub: p.client_name, href: `/projects/${p.id}` })
    }
    for (const t of results.tasks) {
      allItems.push({ type: "task", id: t.id, label: t.title, sub: t.client_name, href: `/tasks?id=${t.id}` })
    }
    for (const l of results.leads) {
      allItems.push({ type: "lead", id: l.id, label: l.company_name, sub: l.contact_name, href: `/leads/${l.id}` })
    }
  }

  useEffect(() => {
    if (open) {
      setQuery("")
      setSelectedIndex(0)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

  const handleNavigate = useCallback((href: string) => {
    onOpenChange(false)
    navigate(href)
  }, [navigate, onOpenChange])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault()
      setSelectedIndex((i) => Math.min(i + 1, allItems.length - 1))
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setSelectedIndex((i) => Math.max(i - 1, 0))
    } else if (e.key === "Enter" && allItems[selectedIndex]) {
      e.preventDefault()
      handleNavigate(allItems[selectedIndex].href)
    } else if (e.key === "Escape") {
      onOpenChange(false)
    }
  }

  if (!open) return null

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
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-start justify-center pt-[20vh]" onClick={() => onOpenChange(false)}>
      <div
        className="w-full max-w-lg bg-card border border-border rounded-xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
          <Search className="h-5 w-5 text-muted-foreground shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Buscar clientes, proyectos, tareas, leads..."
            className="flex-1 bg-transparent text-foreground placeholder:text-muted-foreground text-sm outline-none"
          />
          <kbd className="hidden sm:inline-flex items-center px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground bg-muted rounded border border-border">
            ESC
          </kbd>
        </div>

        {query.length >= 2 && (
          <div className="max-h-[50vh] overflow-y-auto p-2">
            {allItems.length === 0 ? (
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
                      const isSelected = idx === selectedIndex
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

        {query.length < 2 && (
          <div className="p-6 text-center">
            <p className="text-sm text-muted-foreground">Escribe al menos 2 caracteres para buscar</p>
          </div>
        )}
      </div>
    </div>
  )
}
