import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { newsApi } from "@/lib/api"
import { newsKeys } from "@/lib/query-keys"
import { useAuth } from "@/context/auth-context"
import type { IndustryNewsItem, IndustryNewsCreate, NewsFeedCreate } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Card } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Plus, Pencil, Trash2, ExternalLink, Globe, Rss, RefreshCw, Power } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

const emptyForm: IndustryNewsCreate = {
  title: "",
  published_date: new Date().toISOString().slice(0, 10),
  content: "",
  url: "",
}

const emptyFeedForm: NewsFeedCreate = {
  name: "",
  url: "",
  category: "general",
}

export default function IndustryNewsPage() {
  const { isAdmin } = useAuth()
  const queryClient = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<IndustryNewsCreate>({ ...emptyForm })
  const [deleteId, setDeleteId] = useState<number | null>(null)

  // Feed management state
  const [feedDialogOpen, setFeedDialogOpen] = useState(false)
  const [feedForm, setFeedForm] = useState<NewsFeedCreate>({ ...emptyFeedForm })
  const [deleteFeedId, setDeleteFeedId] = useState<number | null>(null)
  const [showFeeds, setShowFeeds] = useState(false)

  const { data: news = [], isLoading } = useQuery({
    queryKey: newsKeys.all(),
    queryFn: newsApi.list,
  })

  const { data: feeds = [] } = useQuery({
    queryKey: newsKeys.feeds(),
    queryFn: newsApi.listFeeds,
    enabled: isAdmin,
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

  // Feed mutations
  const createFeedMutation = useMutation({
    mutationFn: newsApi.createFeed,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: newsKeys.feeds() })
      toast.success("Feed añadido")
      setFeedDialogOpen(false)
      setFeedForm({ ...emptyFeedForm })
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const toggleFeedMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      newsApi.updateFeed(id, { enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: newsKeys.feeds() })
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const deleteFeedMutation = useMutation({
    mutationFn: newsApi.deleteFeed,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: newsKeys.feeds() })
      toast.success("Feed eliminado")
      setDeleteFeedId(null)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const fetchMutation = useMutation({
    mutationFn: newsApi.fetchFeeds,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: newsKeys.all() })
      queryClient.invalidateQueries({ queryKey: newsKeys.feeds() })
      if (data.new_articles > 0) {
        toast.success(`${data.new_articles} noticia(s) nueva(s) de ${data.feeds_processed} feed(s)`)
      } else {
        toast.info(`Sin noticias nuevas (${data.feeds_processed} feed(s) revisados)`)
      }
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  function openCreate() {
    setEditingId(null)
    setForm({ ...emptyForm })
    setDialogOpen(true)
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
  }

  function handleSubmit() {
    if (!form.title.trim() || !form.published_date) return
    if (editingId) {
      updateMutation.mutate({ id: editingId, data: form })
    } else {
      createMutation.mutate(form)
    }
  }

  function handleFeedSubmit() {
    if (!feedForm.name.trim() || !feedForm.url.trim()) return
    createFeedMutation.mutate(feedForm)
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
        {isAdmin && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={() => setShowFeeds(!showFeeds)}
            >
              <Rss className="h-4 w-4 mr-2" />
              Feeds RSS{feeds.length > 0 && ` (${feeds.length})`}
            </Button>
            <Button
              variant="outline"
              onClick={() => fetchMutation.mutate()}
              disabled={fetchMutation.isPending || feeds.length === 0}
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${fetchMutation.isPending ? "animate-spin" : ""}`} />
              Recoger noticias
            </Button>
            <Button onClick={openCreate}>
              <Plus className="h-4 w-4 mr-2" />
              Nueva noticia
            </Button>
          </div>
        )}
      </div>

      {/* RSS Feeds Management (admin only) */}
      {isAdmin && showFeeds && (
        <Card className="p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">Feeds RSS configurados</h2>
            <Button size="sm" onClick={() => setFeedDialogOpen(true)}>
              <Plus className="h-4 w-4 mr-1" />
              Añadir feed
            </Button>
          </div>
          {feeds.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No hay feeds configurados. Añade un feed RSS para recoger noticias automáticamente.
            </p>
          ) : (
            <div className="space-y-2">
              {feeds.map((feed) => (
                <div
                  key={feed.id}
                  className="flex items-center justify-between gap-4 p-3 rounded-md border"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`font-medium text-sm ${!feed.enabled ? "text-muted-foreground line-through" : ""}`}>
                        {feed.name}
                      </span>
                      <span className="text-xs px-1.5 py-0.5 bg-muted rounded">{feed.category}</span>
                    </div>
                    <p className="text-xs text-muted-foreground truncate mt-0.5">{feed.url}</p>
                    {feed.last_fetched_at && (
                      <p className="text-xs text-muted-foreground mt-0.5">
                        Última recogida: {new Date(feed.last_fetched_at).toLocaleString("es-ES")}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      title={feed.enabled ? "Desactivar" : "Activar"}
                      onClick={() => toggleFeedMutation.mutate({ id: feed.id, enabled: !feed.enabled })}
                    >
                      <Power className={`h-3.5 w-3.5 ${feed.enabled ? "text-green-600" : "text-muted-foreground"}`} />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-destructive hover:text-destructive"
                      onClick={() => setDeleteFeedId(feed.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

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
            {isAdmin
              ? "Configura feeds RSS o crea noticias manualmente para que aparezcan aquí."
              : "No hay noticias del sector registradas aún."}
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
                {isAdmin && (
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
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Create / Edit News Dialog */}
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

      {/* Add Feed Dialog */}
      <Dialog open={feedDialogOpen} onOpenChange={setFeedDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Añadir feed RSS</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Nombre *</Label>
              <Input
                value={feedForm.name}
                onChange={(e) => setFeedForm({ ...feedForm, name: e.target.value })}
                placeholder="Ej: Search Engine Journal"
              />
            </div>
            <div>
              <Label>URL del feed *</Label>
              <Input
                value={feedForm.url}
                onChange={(e) => setFeedForm({ ...feedForm, url: e.target.value })}
                placeholder="https://www.searchenginejournal.com/feed/"
              />
            </div>
            <div>
              <Label>Categoría</Label>
              <Input
                value={feedForm.category ?? "general"}
                onChange={(e) => setFeedForm({ ...feedForm, category: e.target.value })}
                placeholder="SEO, marketing, IA..."
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFeedDialogOpen(false)}>
              Cancelar
            </Button>
            <Button
              onClick={handleFeedSubmit}
              disabled={createFeedMutation.isPending || !feedForm.name.trim() || !feedForm.url.trim()}
            >
              {createFeedMutation.isPending ? "Guardando..." : "Añadir"}
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

      {/* Delete Feed Confirm */}
      <ConfirmDialog
        open={deleteFeedId !== null}
        onOpenChange={(open) => !open && setDeleteFeedId(null)}
        title="Eliminar feed RSS"
        description="Se eliminará el feed. Las noticias ya importadas se mantendrán."
        onConfirm={() => deleteFeedId && deleteFeedMutation.mutate(deleteFeedId)}
      />
    </div>
  )
}
