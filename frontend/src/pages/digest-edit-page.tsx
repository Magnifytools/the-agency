import { useState, useEffect } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Save, Eye, Copy, Loader2, Plus, Trash2 } from "lucide-react"
import { digestsApi } from "@/lib/api"
import type { DigestContent, DigestItem, DigestTone, DigestSections } from "@/lib/types"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

const sectionLabels: Record<keyof DigestSections, { title: string; color: string }> = {
  done: { title: "Hecho", color: "bg-green-100 text-green-800" },
  need: { title: "Necesitamos", color: "bg-amber-100 text-amber-800" },
  next: { title: "Próximamente", color: "bg-blue-100 text-blue-800" },
}

export default function DigestEditPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [greeting, setGreeting] = useState("")
  const [dateStr, setDateStr] = useState("")
  const [closing, setClosing] = useState("")
  const [sections, setSections] = useState<DigestSections>({ done: [], need: [], next: [] })
  const [tone, setTone] = useState<DigestTone>("cercano")
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewFormat, setPreviewFormat] = useState<"slack" | "email">("slack")
  const [previewContent, setPreviewContent] = useState("")

  const { data: digest, isLoading } = useQuery({
    queryKey: ["digest", id],
    queryFn: () => digestsApi.get(Number(id)),
    enabled: !!id,
  })

  // Populate form when digest loads
  /* eslint-disable react-hooks/set-state-in-effect -- Syncing form state from fetched async data */
  useEffect(() => {
    if (digest) {
      setTone(digest.tone)
      if (digest.content) {
        setGreeting(digest.content.greeting || "")
        setDateStr(digest.content.date || "")
        setClosing(digest.content.closing || "")
        setSections({
          done: digest.content.sections?.done || [],
          need: digest.content.sections?.need || [],
          next: digest.content.sections?.next || [],
        })
      }
    }
  }, [digest])
  /* eslint-enable react-hooks/set-state-in-effect */

  const updateMutation = useMutation({
    mutationFn: () => {
      const content: DigestContent = {
        greeting,
        date: dateStr,
        sections,
        closing,
      }
      return digestsApi.update(Number(id), { content, tone })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["digest", id] })
      queryClient.invalidateQueries({ queryKey: ["digests"] })
      toast.success("Digest guardado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al guardar")),
  })

  const renderMutation = useMutation({
    mutationFn: ({ format }: { format: "slack" | "email" }) =>
      digestsApi.render(Number(id), format),
    onSuccess: (data) => setPreviewContent(data.rendered),
    onError: (err) => toast.error(getErrorMessage(err, "Error al renderizar")),
  })

  const handlePreview = (fmt: "slack" | "email") => {
    // Save first, then render
    const content: DigestContent = { greeting, date: dateStr, sections, closing }
    digestsApi.update(Number(id), { content, tone }).then(() => {
      setPreviewFormat(fmt)
      setPreviewOpen(true)
      setPreviewContent("")
      renderMutation.mutate({ format: fmt })
    })
  }

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
      {/* Header */}
      <div className="flex items-center justify-between">
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
            Preview
          </Button>
          <Button onClick={() => updateMutation.mutate()} disabled={updateMutation.isPending}>
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
        <Label>Tono</Label>
        <Select value={tone} onChange={(e) => setTone(e.target.value as DigestTone)} className="w-40">
          <option value="cercano">Cercano</option>
          <option value="formal">Formal</option>
          <option value="equipo">Equipo</option>
        </Select>
        <Badge variant="secondary">{digest.status}</Badge>
      </div>

      {/* Greeting + Date */}
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="space-y-2">
            <Label>Saludo</Label>
            <Input value={greeting} onChange={(e) => setGreeting(e.target.value)} placeholder="Hola [Cliente]!" />
          </div>
          <div className="space-y-2">
            <Label>Fecha</Label>
            <Input value={dateStr} onChange={(e) => setDateStr(e.target.value)} placeholder="Semana del X al Y de mes año" />
          </div>
        </CardContent>
      </Card>

      {/* Sections */}
      {(["done", "need", "next"] as const).map((sectionKey) => (
        <Card key={sectionKey}>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Badge className={sectionLabels[sectionKey].color}>
                  {sectionLabels[sectionKey].title}
                </Badge>
                <span className="text-sm text-muted-foreground">
                  {sections[sectionKey].length} items
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
                    />
                    <Textarea
                      value={item.description}
                      onChange={(e) => updateItem(sectionKey, idx, "description", e.target.value)}
                      placeholder="Descripción"
                      rows={2}
                    />
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => removeItem(sectionKey, idx)}
                    className="text-destructive hover:text-destructive"
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              ))}
              {sections[sectionKey].length === 0 && (
                <p className="text-sm text-muted-foreground text-center py-4">
                  Sin items. Haz clic en "Añadir" para crear uno.
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
            <Label>Cierre</Label>
            <Textarea
              value={closing}
              onChange={(e) => setClosing(e.target.value)}
              placeholder="Mensaje de cierre..."
              rows={3}
            />
          </div>
        </CardContent>
      </Card>

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
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogHeader>
          <DialogTitle>Preview — {digest.client_name}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 pt-4">
          <div className="flex gap-2">
            <Button
              variant={previewFormat === "slack" ? "default" : "outline"}
              size="sm"
              onClick={() => {
                setPreviewFormat("slack")
                setPreviewContent("")
                renderMutation.mutate({ format: "slack" })
              }}
            >
              Slack
            </Button>
            <Button
              variant={previewFormat === "email" ? "default" : "outline"}
              size="sm"
              onClick={() => {
                setPreviewFormat("email")
                setPreviewContent("")
                renderMutation.mutate({ format: "email" })
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
              dangerouslySetInnerHTML={{ __html: previewContent }}
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
