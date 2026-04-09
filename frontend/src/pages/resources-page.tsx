import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { teamResourcesApi } from "@/lib/api"
import type { TeamResource } from "@/lib/api"
import { useAuth } from "@/context/auth-context"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { Search, Plus, ExternalLink, Pin, Trash2, Pencil, Wrench, FileText, Video, Layout, Lightbulb } from "lucide-react"
import { toast } from "sonner"

const UPPERCASE_WORDS = new Set(["ia", "seo", "ui", "ux", "ctr", "crm", "css"])
function displayLabel(s: string) {
  return s.split(" ").map(w => UPPERCASE_WORDS.has(w.toLowerCase()) ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1)).join(" ")
}

// Categoría = temática
const CATEGORY_COLORS: Record<string, string> = {
  "ia": "bg-violet-100 text-violet-700",
  "seo": "bg-green-100 text-green-700",
  "diseño": "bg-pink-100 text-pink-700",
  "desarrollo": "bg-blue-100 text-blue-700",
  "marketing": "bg-orange-100 text-orange-700",
  "producto": "bg-cyan-100 text-cyan-700",
  "ventas": "bg-amber-100 text-amber-700",
  "contenido": "bg-teal-100 text-teal-700",
  "analítica": "bg-indigo-100 text-indigo-700",
}

// Tipo = formato del recurso
const TYPE_ICONS: Record<string, typeof Wrench> = {
  "herramienta": Wrench,
  "guía": FileText,
  "prompt": FileText,
  "template": Layout,
  "extensión": Wrench,
  "dataset": Layout,
  "inspiración": Lightbulb,
  "caso de estudio": Search,
  "artículo": FileText,
  "vídeo": Video,
  "librería": Layout,
  "idea": Lightbulb,
}

export default function ResourcesPage() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [search, setSearch] = useState("")
  const [filterCat, setFilterCat] = useState<string>("")
  const [showAdd, setShowAdd] = useState(false)

  const { data } = useQuery({
    queryKey: ["team-resources", search, filterCat] as const,
    queryFn: () => teamResourcesApi.list({
      search: search || undefined,
      category: filterCat || undefined,
      limit: 100,
    }),
  })


  const [editingResource, setEditingResource] = useState<TeamResource | null>(null)

  const deleteMut = useMutation({
    mutationFn: (id: number) => teamResourcesApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["team-resources"] })
      toast.success("Recurso eliminado")
    },
    onError: () => toast.error("Error al eliminar"),
  })

  const pinMut = useMutation({
    mutationFn: ({ id, pinned }: { id: number; pinned: boolean }) =>
      teamResourcesApi.update(id, { is_pinned: pinned }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["team-resources"] }),
  })

  const resources: TeamResource[] = (data as { items: TeamResource[]; total: number } | undefined)?.items || []
  const total = (data as { items: TeamResource[]; total: number } | undefined)?.total || 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Recursos del equipo</h1>
          <p className="text-muted-foreground">Herramientas, artículos y recursos compartidos</p>
        </div>
        <Button onClick={() => setShowAdd(true)}>
          <Plus className="h-4 w-4 mr-2" /> Añadir recurso
        </Button>
      </div>

      {/* Search + filters */}
      <div className="space-y-3">
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar recursos..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <div className="flex flex-wrap gap-1">
          <button
            onClick={() => setFilterCat("")}
            className={`px-3 py-1.5 text-xs rounded-full transition-colors ${!filterCat ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:bg-muted/80"}`}
          >
            Todos
          </button>
          {Object.keys(CATEGORY_COLORS).map((cat) => (
            <button
              key={cat}
              onClick={() => setFilterCat(filterCat === cat ? "" : cat)}
              className={`px-3 py-1.5 text-xs rounded-full transition-colors ${filterCat === cat ? "bg-foreground text-background" : "bg-muted text-muted-foreground hover:bg-muted/80"}`}
            >
              {displayLabel(cat)}
            </button>
          ))}
        </div>
      </div>

      {/* Resource grid */}
      {resources.length === 0 ? (
        <Card className="p-12 text-center text-muted-foreground">
          {search ? "No se encontraron recursos" : "Aún no hay recursos. ¡Comparte el primero!"}
        </Card>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {resources.map((r) => (
            <ResourceCard
              key={r.id}
              resource={r}
              isOwner={user?.id === r.shared_by || user?.role === "admin"}
              onDelete={() => deleteMut.mutate(r.id)}
              onPin={() => pinMut.mutate({ id: r.id, pinned: !r.is_pinned })}
              onEdit={() => setEditingResource(r)}
            />
          ))}
        </div>
      )}

      {/* Total */}
      {total > 0 && <p className="text-xs text-muted-foreground text-center">{total} recursos</p>}

      {/* Add dialog */}
      <AddResourceDialog open={showAdd} onOpenChange={setShowAdd} />
      {editingResource && (
        <EditResourceDialog
          resource={editingResource}
          open={!!editingResource}
          onOpenChange={(v) => { if (!v) setEditingResource(null) }}
        />
      )}
    </div>
  )
}


function ResourceCard({
  resource: r,
  isOwner,
  onDelete,
  onPin,
  onEdit,
}: {
  resource: TeamResource
  isOwner: boolean
  onDelete: () => void
  onPin: () => void
  onEdit: () => void
}) {
  const catColor = CATEGORY_COLORS[r.category] || "bg-gray-100 text-gray-700"
  const Icon = TYPE_ICONS[r.resource_type] || Wrench

  return (
    <Card className="p-4 flex flex-col gap-3 hover:border-brand/30 transition-colors relative group">
      {r.is_pinned && (
        <Pin className="absolute top-3 right-3 h-3.5 w-3.5 text-brand fill-brand" />
      )}

      <div className="flex items-start gap-3">
        <div className={`p-2 rounded-lg ${catColor}`}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-sm leading-tight truncate">{r.title}</h3>
          <div className="flex gap-1.5 mt-1">
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${catColor}`}>{displayLabel(r.category)}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground">{displayLabel(r.resource_type)}</span>
          </div>
          {r.description && (
            <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{r.description}</p>
          )}
        </div>
      </div>

      {r.tags && (
        <div className="flex flex-wrap gap-1">
          {r.tags.split(",").map((tag) => (
            <Badge key={tag.trim()} variant="secondary" className="text-[10px] px-1.5 py-0">
              {tag.trim()}
            </Badge>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between mt-auto pt-2 border-t border-border">
        <span className="text-[11px] text-muted-foreground">
          {r.shared_by_name} · {new Date(r.created_at).toLocaleDateString("es")}
        </span>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {r.url && (
            <a href={r.url} target="_blank" rel="noopener noreferrer" className="p-1 hover:bg-muted rounded">
              <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
            </a>
          )}
          {isOwner && (
            <>
              <button onClick={onEdit} className="p-1 hover:bg-muted rounded">
                <Pencil className="h-3.5 w-3.5 text-muted-foreground" />
              </button>
              <button onClick={onPin} className="p-1 hover:bg-muted rounded">
                <Pin className={`h-3.5 w-3.5 ${r.is_pinned ? "text-brand fill-brand" : "text-muted-foreground"}`} />
              </button>
              <button onClick={onDelete} className="p-1 hover:bg-red-50 rounded">
                <Trash2 className="h-3.5 w-3.5 text-red-500" />
              </button>
            </>
          )}
        </div>
      </div>
    </Card>
  )
}


function AddResourceDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const onClose = () => onOpenChange(false)
  const qc = useQueryClient()
  const [title, setTitle] = useState("")
  const [url, setUrl] = useState("")
  const [description, setDescription] = useState("")
  const [category, setCategory] = useState("ia")
  const [resourceType, setResourceType] = useState("herramienta")
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set())

  const { data: availableTags = {} } = useQuery({
    queryKey: ["resource-tags"],
    queryFn: teamResourcesApi.tags,
  })

  const { data: catData } = useQuery({
    queryKey: ["resource-categories"],
    queryFn: teamResourcesApi.categories,
  })

  const toggleTag = (tag: string) => {
    setSelectedTags((prev) => {
      const next = new Set(prev)
      if (next.has(tag)) next.delete(tag)
      else next.add(tag)
      return next
    })
  }

  const createMut = useMutation({
    mutationFn: () =>
      teamResourcesApi.create({
        title,
        url: url || undefined,
        description: description || undefined,
        category,
        resource_type: resourceType,
        tags: selectedTags.size > 0 ? [...selectedTags].join(", ") : undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["team-resources"] })
      toast.success("Recurso añadido")
      onClose()
    },
    onError: () => toast.error("Error al crear recurso"),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Añadir recurso</DialogTitle>
      </DialogHeader>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          createMut.mutate()
        }}
        className="space-y-4 mt-4"
      >
        <div className="space-y-2">
          <Label>Título *</Label>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ej: Telex — bloques WordPress con IA" required />
        </div>
        <div className="space-y-2">
          <Label>URL</Label>
          <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." />
        </div>
        <div className="space-y-2">
          <Label>Descripción</Label>
          <Textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Para qué sirve, por qué es útil..." rows={2} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>Categoría *</Label>
            <Select value={category} onChange={(e) => setCategory(e.target.value)}>
              {(catData?.categories || []).map((c: string) => (
                <option key={c} value={c}>{displayLabel(c)}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Tipo *</Label>
            <Select value={resourceType} onChange={(e) => setResourceType(e.target.value)}>
              {(catData?.resource_types || []).map((t: string) => (
                <option key={t} value={t}>{displayLabel(t)}</option>
              ))}
            </Select>
          </div>
        </div>
        <div className="space-y-2">
          <Label>Tags</Label>
          {Object.entries(availableTags as Record<string, string[]>).map(([group, tags]) => (
            <div key={group} className="space-y-1">
              <span className="text-[11px] text-muted-foreground uppercase tracking-wide">{group}</span>
              <div className="flex flex-wrap gap-1.5">
                {tags.map((tag: string) => (
              <button
                key={tag}
                type="button"
                onClick={() => toggleTag(tag)}
                className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                  selectedTags.has(tag)
                    ? "bg-foreground text-background border-foreground"
                    : "bg-background text-muted-foreground border-border hover:border-foreground/30"
                }`}
              >
                {tag}
              </button>
            ))}
              </div>
            </div>
          ))}
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onClose}>Cancelar</Button>
          <Button type="submit" disabled={!title.trim() || createMut.isPending}>
            {createMut.isPending ? "Guardando..." : "Añadir"}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}


function EditResourceDialog({ resource, open, onOpenChange }: { resource: TeamResource; open: boolean; onOpenChange: (v: boolean) => void }) {
  const onClose = () => onOpenChange(false)
  const qc = useQueryClient()
  const [title, setTitle] = useState(resource.title)
  const [url, setUrl] = useState(resource.url || "")
  const [description, setDescription] = useState(resource.description || "")
  const [category, setCategory] = useState(resource.category)
  const [resourceType, setResourceType] = useState(resource.resource_type)
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set(resource.tags?.split(",").map(t => t.trim()).filter(Boolean) || []))

  const { data: availableTags = {} } = useQuery({ queryKey: ["resource-tags"], queryFn: teamResourcesApi.tags })
  const { data: catData } = useQuery({ queryKey: ["resource-categories"], queryFn: teamResourcesApi.categories })

  const toggleTag = (tag: string) => {
    setSelectedTags((prev) => { const next = new Set(prev); if (next.has(tag)) next.delete(tag); else next.add(tag); return next })
  }

  const updateMut = useMutation({
    mutationFn: () => teamResourcesApi.update(resource.id, {
      title, url: url || null, description: description || null,
      category, resource_type: resourceType,
      tags: selectedTags.size > 0 ? [...selectedTags].join(", ") : null,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["team-resources"] }); toast.success("Recurso actualizado"); onClose() },
    onError: () => toast.error("Error al actualizar"),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader><DialogTitle>Editar recurso</DialogTitle></DialogHeader>
      <form onSubmit={(e) => { e.preventDefault(); updateMut.mutate() }} className="space-y-4 mt-4">
        <div className="space-y-2">
          <Label>Título *</Label>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} required />
        </div>
        <div className="space-y-2">
          <Label>URL</Label>
          <Input value={url} onChange={(e) => setUrl(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label>Descripción</Label>
          <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>Categoría</Label>
            <Select value={category} onChange={(e) => setCategory(e.target.value)}>
              {(catData?.categories || []).map((c: string) => (<option key={c} value={c}>{displayLabel(c)}</option>))}
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Tipo</Label>
            <Select value={resourceType} onChange={(e) => setResourceType(e.target.value)}>
              {(catData?.resource_types || []).map((t: string) => (<option key={t} value={t}>{displayLabel(t)}</option>))}
            </Select>
          </div>
        </div>
        <div className="space-y-2">
          <Label>Tags</Label>
          {Object.entries(availableTags as Record<string, string[]>).map(([group, tags]) => (
            <div key={group} className="space-y-1">
              <span className="text-[11px] text-muted-foreground uppercase tracking-wide">{group}</span>
              <div className="flex flex-wrap gap-1.5">
                {tags.map((tag: string) => (
                  <button key={tag} type="button" onClick={() => toggleTag(tag)}
                    className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${selectedTags.has(tag) ? "bg-foreground text-background border-foreground" : "bg-background text-muted-foreground border-border hover:border-foreground/30"}`}
                  >{tag}</button>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onClose}>Cancelar</Button>
          <Button type="submit" disabled={!title.trim() || updateMut.isPending}>
            {updateMut.isPending ? "Guardando..." : "Guardar"}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
