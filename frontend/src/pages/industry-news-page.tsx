import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { newsApi, newsSourcesApi } from "@/lib/api"
import type { NewsSource } from "@/lib/api"
import { newsKeys } from "@/lib/query-keys"
import type { IndustryNewsItem, IndustryNewsCreate } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Card } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Plus, Pencil, Trash2, ExternalLink, Globe, Link, Loader2, Rss } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import { cn } from "@/lib/utils"

const emptyForm: IndustryNewsCreate = {
  title: "",
  published_date: new Date().toISOString().slice(0, 10),
  content: "",
  url: "",
}

export default function IndustryNewsPage() {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<"news" | "sources">("news")
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<IndustryNewsCreate>({ ...emptyForm })
  const [deleteId, setDeleteId] = useState<number | null>(null)

  // URL extraction step
  const [extractUrl, setExtractUrl] = useState("")
  const [extractStep, setExtractStep] = useState(false)

  const { data: news = [], isLoading } = useQuery({
    queryKey: newsKeys.all(),
    queryFn: newsApi.list,
  })

  const createMutation = useMutation({
    mutationFn: newsApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: newsKeys.all() })
      toast.success("Noticia creada")
      closeDialog()
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<IndustryNewsCreate> }) =>
      newsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: newsKeys.all() })
      toast.success("Noticia actualizada")
      closeDialog()
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const deleteMutation = useMutation({
    mutationFn: newsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: newsKeys.all() })
      toast.success("Noticia eliminada")
      setDeleteId(null)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const extractMutation = useMutation({
    mutationFn: newsApi.extract,
    onSuccess: (data) => {
      setForm({
        title: data.title ?? "",
        published_date: data.published_date ?? new Date().toISOString().slice(0, 10),
        content: data.content ?? "",
        url: extractUrl,
      })
      setExtractStep(false)
      setDialogOpen(true)
    },
    onError: (e) => {
      toast.error(getErrorMessage(e))
      // Fall back to manual form with the URL pre-filled
      setForm({ ...emptyForm, url: extractUrl })
      setExtractStep(false)
      setDialogOpen(true)
    },
  })

  function openCreate() {
    setEditingId(null)
    setExtractUrl("")
    setExtractStep(true)
  }

  function openManual() {
    setExtractStep(false)
    setForm({ ...emptyForm })
    setEditingId(null)
    setDialogOpen(true)
  }

  function handleExtract() {
    const url = extractUrl.trim()
    if (!url) return
    extractMutation.mutate(url)
  }

  function openEdit(item: IndustryNewsItem) {
    setEditingId(item.id)
    setForm({
      title: item.title,
      published_date: item.published_date,
      content: item.content ?? "",
      url: item.url ?? "",
    })
    setDialogOpen(true)
  }

  function closeDialog() {
    setDialogOpen(false)
    setEditingId(null)
    setExtractStep(false)
  }

  function handleSubmit() {
    if (!form.title.trim() || !form.published_date) return
    if (editingId) {
      updateMutation.mutate({ id: editingId, data: form })
    } else {
      createMutation.mutate(form)
    }
  }

  const isSaving = createMutation.isPending || updateMutation.isPending

  return (
    <div className="space-y-8 max-w-5xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Noticias del Sector</h1>
          <p className="text-muted-foreground mt-1">
            Google Updates, cambios de algoritmo y novedades relevantes
          </p>
        </div>
        {tab === "news" ? (
          <Button onClick={openCreate}>
            <Plus className="h-4 w-4 mr-2" />
            Nueva noticia
          </Button>
        ) : null}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b">
        <button
          className={cn("px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors", tab === "news" ? "border-brand text-brand" : "border-transparent text-muted-foreground hover:text-foreground")}
          onClick={() => setTab("news")}
        >
          Noticias
        </button>
        <button
          className={cn("px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors", tab === "sources" ? "border-brand text-brand" : "border-transparent text-muted-foreground hover:text-foreground")}
          onClick={() => setTab("sources")}
        >
          Fuentes
        </button>
      </div>

      {tab === "sources" ? (
        <SourcesTab />
      ) : (
      <>

      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="p-6 animate-pulse">
              <div className="h-5 bg-muted rounded w-2/3 mb-3" />
              <div className="h-4 bg-muted rounded w-1/4 mb-3" />
              <div className="h-4 bg-muted rounded w-full" />
            </Card>
          ))}
        </div>
      ) : news.length === 0 ? (
        <Card className="p-12 text-center">
          <Globe className="h-12 w-12 text-muted-foreground/40 mx-auto mb-4" />
          <h3 className="text-lg font-semibold mb-1">Sin noticias</h3>
          <p className="text-muted-foreground text-sm">
            Añade noticias del sector para que el equipo esté al día.
          </p>
        </Card>
      ) : (
        <div className="space-y-4">
          {news.map((item) => (
            <Card key={item.id} className="p-6">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 mb-1">
                    <h3 className="font-semibold text-base truncate">{item.title}</h3>
                  </div>
                  <p className="text-xs text-muted-foreground mb-2">
                    {new Date(item.published_date + "T00:00:00").toLocaleDateString("es-ES", {
                      day: "numeric",
                      month: "long",
                      year: "numeric",
                    })}
                  </p>
                  {item.content && (
                    <p className="text-sm text-muted-foreground line-clamp-3">
                      {item.content}
                    </p>
                  )}
                  {item.url && (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-brand hover:underline mt-2"
                    >
                      <ExternalLink className="h-3 w-3" />
                      Fuente
                    </a>
                  )}
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    onClick={() => openEdit(item)}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-destructive hover:text-destructive"
                    onClick={() => setDeleteId(item.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      </>
      )}

      {/* Step 1: URL Extraction Dialog */}
      <Dialog open={extractStep} onOpenChange={(open) => !open && setExtractStep(false)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nueva noticia</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Pega la URL del artículo</Label>
              <div className="flex gap-2 mt-1.5">
                <Input
                  value={extractUrl}
                  onChange={(e) => setExtractUrl(e.target.value)}
                  placeholder="https://..."
                  onKeyDown={(e) => e.key === "Enter" && handleExtract()}
                />
                <Button
                  onClick={handleExtract}
                  disabled={!extractUrl.trim() || extractMutation.isPending}
                >
                  {extractMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Link className="h-4 w-4" />
                  )}
                </Button>
              </div>
              <p className="text-xs text-muted-foreground mt-1.5">
                Se extraerán título y descripción automáticamente.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setExtractStep(false)}>
              Cancelar
            </Button>
            <Button variant="ghost" onClick={openManual}>
              Crear manualmente
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Step 2: Create / Edit News Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingId ? "Editar noticia" : "Nueva noticia"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Título *</Label>
              <Input
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                placeholder="Ej: Google March 2026 Core Update"
              />
            </div>
            <div>
              <Label>Fecha de publicación *</Label>
              <Input
                type="date"
                value={form.published_date}
                onChange={(e) => setForm({ ...form, published_date: e.target.value })}
              />
            </div>
            <div>
              <Label>Descripción</Label>
              <Textarea
                value={form.content ?? ""}
                onChange={(e) => setForm({ ...form, content: e.target.value })}
                placeholder="Descripción de la noticia..."
                rows={4}
              />
            </div>
            <div>
              <Label>URL fuente</Label>
              <Input
                value={form.url ?? ""}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
                placeholder="https://..."
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeDialog}>
              Cancelar
            </Button>
            <Button onClick={handleSubmit} disabled={isSaving || !form.title.trim()}>
              {isSaving ? "Guardando..." : editingId ? "Guardar" : "Crear"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete News Confirm */}
      <ConfirmDialog
        open={deleteId !== null}
        onOpenChange={(open) => !open && setDeleteId(null)}
        title="Eliminar noticia"
        description="Esta acción no se puede deshacer."
        onConfirm={() => deleteId && deleteMutation.mutate(deleteId)}
      />
    </div>
  )
}


function SourcesTab() {
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingSource, setEditingSource] = useState<NewsSource | null>(null)
  const [form, setForm] = useState({ name: "", url: "", category: "" })
  const [deleteId, setDeleteId] = useState<number | null>(null)

  const { data: sources = [], isLoading } = useQuery({
    queryKey: ["news-sources"],
    queryFn: newsSourcesApi.list,
  })

  const createMutation = useMutation({
    mutationFn: newsSourcesApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["news-sources"] })
      toast.success("Fuente añadida")
      setDialogOpen(false)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<NewsSource> }) =>
      newsSourcesApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["news-sources"] })
      toast.success("Fuente actualizada")
      setDialogOpen(false)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const deleteMutation = useMutation({
    mutationFn: newsSourcesApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["news-sources"] })
      toast.success("Fuente eliminada")
      setDeleteId(null)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  function openCreate() {
    setEditingSource(null)
    setForm({ name: "", url: "", category: "" })
    setDialogOpen(true)
  }

  function openEdit(source: NewsSource) {
    setEditingSource(source)
    setForm({ name: source.name, url: source.url, category: source.category ?? "" })
    setDialogOpen(true)
  }

  function handleSubmit() {
    if (!form.name.trim() || !form.url.trim()) return
    const data = { name: form.name, url: form.url, category: form.category || null }
    if (editingSource) {
      updateMutation.mutate({ id: editingSource.id, data })
    } else {
      createMutation.mutate(data)
    }
  }

  const isSaving = createMutation.isPending || updateMutation.isPending

  // Group by category
  const grouped = sources.reduce<Record<string, NewsSource[]>>((acc, s) => {
    const cat = s.category || "Sin categoría"
    ;(acc[cat] ??= []).push(s)
    return acc
  }, {})

  return (
    <>
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Medios y fuentes de referencia del sector ({sources.length})
        </p>
        <Button onClick={openCreate} size="sm">
          <Plus className="h-4 w-4 mr-2" />
          Añadir fuente
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="p-4 animate-pulse">
              <div className="h-4 bg-muted rounded w-1/3" />
            </Card>
          ))}
        </div>
      ) : sources.length === 0 ? (
        <Card className="p-12 text-center">
          <Rss className="h-12 w-12 text-muted-foreground/40 mx-auto mb-4" />
          <h3 className="text-lg font-semibold mb-1">Sin fuentes</h3>
          <p className="text-muted-foreground text-sm">
            Añade medios y fuentes de referencia para tener acceso rápido.
          </p>
        </Card>
      ) : (
        <div className="space-y-6">
          {Object.entries(grouped).map(([cat, items]) => (
            <div key={cat}>
              <h3 className="text-sm font-medium text-muted-foreground mb-2 uppercase tracking-wide">{cat}</h3>
              <div className="grid gap-2">
                {items.map((source) => (
                  <Card key={source.id} className="p-3 flex items-center justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm truncate">{source.name}</p>
                      <p className="text-xs text-muted-foreground truncate">{source.url}</p>
                    </div>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <Button variant="ghost" size="icon" className="h-8 w-8">
                          <ExternalLink className="h-3.5 w-3.5" />
                        </Button>
                      </a>
                      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => openEdit(source)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-8 w-8 text-destructive" onClick={() => setDeleteId(source.id)}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </Card>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create/Edit Source Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingSource ? "Editar fuente" : "Nueva fuente"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Nombre *</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Ej: Search Engine Journal"
              />
            </div>
            <div>
              <Label>URL *</Label>
              <Input
                value={form.url}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
                placeholder="https://..."
              />
            </div>
            <div>
              <Label>Categoría</Label>
              <Input
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
                placeholder="Ej: SEO, Marketing, IA..."
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
            <Button onClick={handleSubmit} disabled={isSaving || !form.name.trim() || !form.url.trim()}>
              {isSaving ? "Guardando..." : editingSource ? "Guardar" : "Crear"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Source Confirm */}
      <ConfirmDialog
        open={deleteId !== null}
        onOpenChange={(open) => !open && setDeleteId(null)}
        title="Eliminar fuente"
        description="Esta acción no se puede deshacer."
        onConfirm={() => deleteId && deleteMutation.mutate(deleteId)}
      />
    </>
  )
}
