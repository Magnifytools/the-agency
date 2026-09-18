import { useState, useEffect, useLayoutEffect, useRef } from "react"
import DOMPurify from "dompurify"
import { useParams, useNavigate, useLocation } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Save, Eye, Copy, Loader2, Plus, Trash2 } from "lucide-react"
import { digestsApi } from "@/lib/api"
import type { Digest, DigestContent, DigestItem, DigestTone, DigestSections } from "@/lib/types"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

const sectionLabels: Record<keyof DigestSections, { title: string; color: string }> = {
  done: { title: "Hecho", color: "bg-green-100 text-green-800" },
  need: { title: "Necesitamos", color: "bg-amber-100 text-amber-800" },
  next: { title: "Próximamente", color: "bg-blue-100 text-blue-800" },
  metrics: { title: "Métricas", color: "bg-slate-100 text-slate-800" },
}

export default function DigestEditPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { key: routeKey } = useLocation()
  const viewEpoch = useRef(0)
  useLayoutEffect(() => { viewEpoch.current += 1 }, [routeKey])
  const queryClient = useQueryClient()

  const [greeting, setGreeting] = useState("")
  const [dateStr, setDateStr] = useState("")
  const [closing, setClosing] = useState("")
  const [sections, setSections] = useState<Required<DigestSections>>({ done: [], need: [], next: [], metrics: [] })
  const [tone, setTone] = useState<DigestTone>("cercano")
  const [pendingTone, setPendingTone] = useState<DigestTone | null>(null)
  const [previewSaving, setPreviewSaving] = useState(false)
  const [previewId, setPreviewId] = useState<number | null>(null)
  const loadedId = useRef<number | null>(null)
  const active = useRef(true)
  const liveId = useRef(id)
  const previousId = useRef(id)
  useEffect(() => { liveId.current = id }, [id])
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewFormat, setPreviewFormat] = useState<"slack" | "email">("slack")
  const [previewContent, setPreviewContent] = useState("")

  const { data: digest, isLoading } = useQuery({
    queryKey: ["digest", id],
    queryFn: () => digestsApi.get(Number(id)),
    enabled: !!id,
  })

  // Populate form when digest loads
  useEffect(() => {
    if (digest && loadedId.current !== digest.id) {
      loadedId.current = digest.id
      setTone(digest.tone)
      setGreeting(digest.content?.greeting || "")
      setDateStr(digest.content?.date || "")
      setClosing(digest.content?.closing || "")
      setSections({
        done: digest.content?.sections?.done || [],
        need: digest.content?.sections?.need || [],
        next: digest.content?.sections?.next || [],
        metrics: digest.content?.sections?.metrics || [],
      })
    }
  }, [digest])

  useEffect(() => {
    if (previousId.current !== id) {
      previousId.current = id
      if (previewId !== Number(id)) {
        setPreviewOpen(false)
        setPreviewId(null)
        setPreviewContent("")
      }
    }
  }, [id, previewId])

  const draftContent = (): DigestContent => ({ greeting, date: dateStr, sections, closing })
  const acceptVersion = (saved: Digest, sourceId: number, sourceEpoch: number) => {
    if (!active.current || Number(liveId.current) !== sourceId || viewEpoch.current !== sourceEpoch) return
    queryClient.setQueryData(["digest", String(saved.id)], saved)
    queryClient.invalidateQueries({ queryKey: ["digests"] })
    if (saved.id !== Number(id)) {
      liveId.current = String(saved.id)
      navigate(`/digests/${saved.id}/edit`, { replace: true })
    }
  }
  const updateMutation = useMutation({
    mutationFn: (request: { sourceId: number; epoch: number; content: DigestContent; tone: DigestTone }) => digestsApi.update(request.sourceId, { content: request.content, tone: request.tone }),
    onSuccess: (saved, request) => {
      acceptVersion(saved, request.sourceId, request.epoch)
      if (active.current) toast.success("Versión guardada; las anteriores se conservan")
    },
    onError: (err) => toast.error(getErrorMessage(err, "No se pudo guardar. Tu borrador se conserva.")),
  })

  const toneChangeMutation = useMutation({
    mutationFn: async (request: { sourceId: number; epoch: number; newTone: DigestTone; content: DigestContent; tone: DigestTone }) => {
      // Preserve manual edits before asking the model for another version.
      const saved = await digestsApi.update(request.sourceId, { content: request.content, tone: request.tone })
      if (!active.current || Number(liveId.current) !== request.sourceId || viewEpoch.current !== request.epoch) return null
      try {
        return await digestsApi.update(saved.id, { tone: request.newTone })
      } catch (error) {
        acceptVersion(saved, request.sourceId, request.epoch)
        throw error
      }
    },
    onSuccess: (saved, request) => {
      if (!saved || !active.current || Number(liveId.current) !== request.sourceId || viewEpoch.current !== request.epoch) return
      acceptVersion(saved, request.sourceId, request.epoch)
      toast.success("Nueva versión generada; el borrador anterior se conserva")
    },
    onError: (err) => toast.error(getErrorMessage(err, "No se pudo regenerar. Tu borrador se conserva.")),
  })

  const renderMutation = useMutation({
    mutationFn: ({ digestId, format }: { digestId: number; format: "slack" | "email" }) =>
      digestsApi.render(digestId, format),
    onSuccess: (data, variables) => { if (active.current && Number(liveId.current) === variables.digestId) setPreviewContent(data.rendered) },
    onError: (err) => toast.error(getErrorMessage(err, "Error al renderizar")),
  })

  const handlePreview = async (fmt: "slack" | "email") => {
    const sourceEpoch = viewEpoch.current
    setPreviewSaving(true)
    try {
      const saved = await digestsApi.update(Number(id), { content: draftContent(), tone })
      if (!active.current || Number(liveId.current) !== Number(id) || viewEpoch.current !== sourceEpoch) return
      acceptVersion(saved, Number(id), sourceEpoch)
      setPreviewId(saved.id)
      setPreviewFormat(fmt)
      setPreviewOpen(true)
      setPreviewContent("")
      renderMutation.mutate({ digestId: saved.id, format: fmt })
    } catch (error) {
      if (active.current) toast.error(getErrorMessage(error, "No se pudo guardar antes de previsualizar. Tu borrador se conserva."))
    } finally {
      if (active.current) setPreviewSaving(false)
    }
  }
  const busy = updateMutation.isPending || toneChangeMutation.isPending || previewSaving

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(previewContent)
      toast.success("Copiado al portapapeles")
    } catch {
      toast.error("Error al copiar")
    }
  }

  const updateItem = (section: keyof DigestSections, index: number, field: keyof DigestItem, value: string) => {
    setSections((prev) => {
      const items = [...prev[section]]
      items[index] = { ...items[index], [field]: value }
      return { ...prev, [section]: items }
    })
  }

  const addItem = (section: keyof DigestSections) => {
    setSections((prev) => ({
      ...prev,
      [section]: [...prev[section], { title: "", description: "" }],
    }))
  }

  const removeItem = (section: keyof DigestSections, index: number) => {
    setSections((prev) => ({
      ...prev,
      [section]: prev[section].filter((_, i) => i !== index),
    }))
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="w-8 h-8 animate-spin opacity-40" />
      </div>
    )
  }

  if (!digest) {
    return (
      <div className="text-center py-20">
        <p className="text-muted-foreground">Digest no encontrado</p>
        <Button variant="outline" className="mt-4" onClick={() => navigate("/digests")}>
          Volver
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <fieldset disabled={busy} className="space-y-6 min-w-0">
      {/* Header */}
      <div className="flex flex-wrap gap-4 items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => navigate("/digests")}>
            <ArrowLeft className="w-4 h-4 mr-1" />
            Volver
          </Button>
          <div>
            <h1 className="text-2xl font-bold">{digest.client_name}</h1>
            <p className="text-muted-foreground text-sm">
              {digest.period_start} — {digest.period_end}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => handlePreview("slack")}>
            <Eye className="w-4 h-4 mr-2" />
            Vista previa
          </Button>
          <Button onClick={() => updateMutation.mutate({ sourceId: Number(id), epoch: viewEpoch.current, content: draftContent(), tone })} disabled={updateMutation.isPending}>
            {updateMutation.isPending ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Save className="w-4 h-4 mr-2" />
            )}
            Guardar
          </Button>
        </div>
      </div>

      {/* Tone selector */}
      <div className="flex gap-4 items-center">
        <Label htmlFor="digest-tone">Tono</Label>
        <Select
          id="digest-tone"
          value={tone}
          onChange={(e) => { if (e.target.value !== tone) setPendingTone(e.target.value as DigestTone) }}
          className="w-40"
          disabled={toneChangeMutation.isPending}
        >
          <option value="cercano">Cercano</option>
          <option value="formal">Formal</option>
          <option value="equipo">Equipo</option>
        </Select>
        {toneChangeMutation.isPending && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin" />
            Regenerando con nuevo tono...
          </div>
        )}
        <Badge variant="secondary">{{ draft: "Borrador", reviewed: "Revisado", sent: "Marcado como enviado" }[digest.status]}</Badge>
      </div>

      {/* Greeting + Date */}
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="space-y-2">
            <Label htmlFor="digest-greeting">Saludo</Label>
            <Input id="digest-greeting" value={greeting} onChange={(e) => setGreeting(e.target.value)} placeholder="Hola [Cliente]!" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="digest-period">Período del informe</Label>
            <Input id="digest-period" value={dateStr} readOnly />
            <p className="text-xs text-muted-foreground">Se calcula con las fechas del informe; no cambia al editar el texto.</p>
          </div>
        </CardContent>
      </Card>

      {/* Sections */}
      {(["done", "need", "next", "metrics"] as const).map((sectionKey) => (
        <Card key={sectionKey}>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Badge className={sectionLabels[sectionKey].color}>
                  {sectionLabels[sectionKey].title}
                </Badge>
                <span className="text-sm text-muted-foreground">
                  {sections[sectionKey].length} elementos
                </span>
              </div>
              <Button variant="outline" size="sm" onClick={() => addItem(sectionKey)}>
                <Plus className="w-4 h-4 mr-1" />
                Añadir
              </Button>
            </div>

            <div className="space-y-3">
              {sections[sectionKey].map((item, idx) => (
                <div key={idx} className="flex gap-3 items-start border rounded-lg p-3">
                  <div className="flex-1 space-y-2">
                    <Input
                      value={item.title}
                      onChange={(e) => updateItem(sectionKey, idx, "title", e.target.value)}
                      placeholder="Título"
                      className="font-medium"
                      aria-label={`${sectionLabels[sectionKey].title}: título ${idx + 1}`}
                    />
                    <Textarea
                      value={item.description}
                      onChange={(e) => updateItem(sectionKey, idx, "description", e.target.value)}
                      placeholder="Descripción"
                      aria-label={`${sectionLabels[sectionKey].title}: descripción ${idx + 1}`}
                      rows={2}
                    />
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Eliminar ${sectionLabels[sectionKey].title.toLowerCase()} ${idx + 1}`}
                    onClick={() => removeItem(sectionKey, idx)}
                    className="text-destructive hover:text-destructive"
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              ))}
              {sections[sectionKey].length === 0 && (
                <p className="text-sm text-muted-foreground text-center py-4">
                  Sin elementos. Haz clic en "Añadir" para crear uno.
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      ))}

      {/* Closing */}
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="space-y-2">
            <Label htmlFor="digest-closing">Cierre</Label>
            <Textarea
              id="digest-closing"
              value={closing}
              onChange={(e) => setClosing(e.target.value)}
              placeholder="Mensaje de cierre..."
              rows={3}
            />
            <p className="text-xs text-muted-foreground">Soporta HTML en email (ej: enlaces con &lt;a href=&quot;...&quot;&gt;)</p>
          </div>
        </CardContent>
      </Card>

      </fieldset>
      <p className="text-sm text-muted-foreground">Versión #{digest.id} · Guardar crea una versión si hay cambios. Las anteriores siguen disponibles en Resúmenes.</p>
      <ConfirmDialog open={pendingTone !== null} onOpenChange={(open) => { if (!open) setPendingTone(null) }} title="Crear una versión con otro tono" description="Se guardará tu borrador actual y se generará otra versión. Podrás volver a la anterior desde Resúmenes." confirmLabel="Guardar y generar" onConfirm={() => { if (pendingTone) toneChangeMutation.mutate({ sourceId: Number(id), epoch: viewEpoch.current, newTone: pendingTone, content: draftContent(), tone }) }} />

      {/* Raw context sidebar (collapsible) */}
      {digest.raw_context && (
        <details className="border rounded-lg p-4">
          <summary className="cursor-pointer text-sm font-medium text-muted-foreground">
            Datos crudos (raw context)
          </summary>
          <pre className="mt-4 bg-muted p-4 rounded text-xs overflow-auto max-h-96">
            {JSON.stringify(digest.raw_context, null, 2)}
          </pre>
        </details>
      )}

      {/* Preview Dialog */}
      <Dialog open={previewOpen && previewId === Number(id)} onOpenChange={setPreviewOpen}>
        <DialogHeader>
          <DialogTitle>Vista previa — {digest.client_name}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 pt-4">
          <div className="flex gap-2">
            <Button
              disabled={renderMutation.isPending}
              variant={previewFormat === "slack" ? "default" : "outline"}
              size="sm"
              onClick={() => {
                setPreviewFormat("slack")
                setPreviewContent("")
                renderMutation.mutate({ digestId: previewId ?? Number(id), format: "slack" })
              }}
            >
              Slack
            </Button>
            <Button
              disabled={renderMutation.isPending}
              variant={previewFormat === "email" ? "default" : "outline"}
              size="sm"
              onClick={() => {
                setPreviewFormat("email")
                setPreviewContent("")
                renderMutation.mutate({ digestId: previewId ?? Number(id), format: "email" })
              }}
            >
              Email
            </Button>
          </div>

          {renderMutation.isPending ? (
            <div className="flex justify-center py-12">
              <Loader2 className="w-6 h-6 animate-spin opacity-40" />
            </div>
          ) : previewFormat === "slack" ? (
            <pre className="bg-muted p-4 rounded-lg text-sm whitespace-pre-wrap max-h-[60vh] overflow-auto">
              {previewContent}
            </pre>
          ) : (
            <div
              className="border rounded-lg max-h-[60vh] overflow-auto"
              dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(previewContent) }}
            />
          )}

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setPreviewOpen(false)}>Cerrar</Button>
            <Button onClick={handleCopy} disabled={!previewContent}>
              <Copy className="w-4 h-4 mr-2" />
              Copiar
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  )
}
