import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  Camera,
  FileBarChart,
  BarChart3,
  TrendingUp,
  FileText,
  ScrollText,
  Package,
  Link2,
  Plus,
  Pencil,
  Trash2,
  ExternalLink,
  Upload,
  Download,
  Clipboard,
} from "lucide-react"
import { toast } from "sonner"
import { evidenceApi } from "@/lib/api"
import type { ProjectEvidence, ProjectEvidenceCreate, EvidenceType, ProjectPhase } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { getErrorMessage } from "@/lib/utils"

const EVIDENCE_TYPES: { value: EvidenceType; label: string; icon: typeof Camera }[] = [
  { value: "screenshot", label: "Screenshot", icon: Camera },
  { value: "report", label: "Informe", icon: FileBarChart },
  { value: "analytics", label: "Analytics", icon: BarChart3 },
  { value: "ranking", label: "Ranking", icon: TrendingUp },
  { value: "content", label: "Contenido", icon: FileText },
  { value: "deliverable", label: "Entregable", icon: Package },
  { value: "proposal", label: "Propuesta", icon: ScrollText },
  { value: "other", label: "Otro", icon: Link2 },
]

function getEvidenceIcon(type: EvidenceType) {
  return EVIDENCE_TYPES.find((t) => t.value === type)?.icon ?? Link2
}

function getEvidenceLabel(type: EvidenceType) {
  return EVIDENCE_TYPES.find((t) => t.value === type)?.label ?? type
}

function formatFileSize(bytes: number | null | undefined) {
  if (!bytes) return ""
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

interface Props {
  projectId: number
  phases: ProjectPhase[]
}

interface EvidenceFormSubmit {
  data: ProjectEvidenceCreate
  file: File | null
}

export function EvidenceList({ projectId, phases }: Props) {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<ProjectEvidence | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ProjectEvidence | null>(null)

  const { data: evidence = [], isLoading } = useQuery({
    queryKey: ["project-evidence", projectId],
    queryFn: () => evidenceApi.list(projectId),
  })

  const closeForm = () => {
    setEditing(null)
    setShowForm(false)
  }

  const createMut = useMutation({
    mutationFn: (data: ProjectEvidenceCreate) => evidenceApi.create(projectId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-evidence", projectId] })
      closeForm()
      toast.success("Evidencia creada")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const uploadMut = useMutation({
    mutationFn: ({ file, data }: { file: File; data: ProjectEvidenceCreate }) =>
      evidenceApi.upload(projectId, file, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-evidence", projectId] })
      closeForm()
      toast.success("Archivo de evidencia subido")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ProjectEvidenceCreate> }) =>
      evidenceApi.update(projectId, id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-evidence", projectId] })
      closeForm()
      toast.success("Evidencia actualizada")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => evidenceApi.delete(projectId, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-evidence", projectId] })
      setDeleteTarget(null)
      toast.success("Evidencia eliminada")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const handleSubmit = ({ data, file }: EvidenceFormSubmit) => {
    if (editing) {
      updateMut.mutate({ id: editing.id, data })
      return
    }
    if (file) {
      uploadMut.mutate({ file, data })
      return
    }
    createMut.mutate(data)
  }

  if (isLoading) return <p className="text-muted-foreground text-sm">Cargando evidencia...</p>

  const grouped = new Map<string, ProjectEvidence[]>()
  for (const ev of evidence) {
    const key = ev.phase_name || "Sin fase"
    if (!grouped.has(key)) grouped.set(key, [])
    grouped.get(key)!.push(ev)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Evidencia</h3>
        <Button size="sm" onClick={() => { setEditing(null); setShowForm(true) }}>
          <Plus className="h-4 w-4 mr-1" /> Nueva evidencia
        </Button>
      </div>

      {evidence.length === 0 ? (
        <p className="text-muted-foreground text-sm py-8 text-center">
          No hay evidencia registrada. Puedes anadir una URL, subir un archivo o pegar una captura.
        </p>
      ) : (
        <div className="space-y-6">
          {[...grouped.entries()].map(([phaseName, items]) => (
            <div key={phaseName}>
              <h4 className="text-sm font-medium text-muted-foreground mb-3">{phaseName}</h4>
              <div className="grid gap-3 sm:grid-cols-2">
                {items.map((ev) => {
                  const Icon = getEvidenceIcon(ev.evidence_type)
                  const primaryHref = ev.has_file
                    ? (ev.preview_url || evidenceApi.previewUrl(projectId, ev.id))
                    : ev.url
                  const downloadHref = ev.has_file
                    ? (ev.download_url || evidenceApi.downloadUrl(projectId, ev.id))
                    : ev.url

                  return (
                    <Card key={ev.id} className="relative">
                      <CardContent className="p-4">
                        <div className="flex items-start justify-between">
                          <div className="flex items-center gap-2.5 min-w-0">
                            <div className="h-9 w-9 rounded-lg bg-muted flex items-center justify-center shrink-0">
                              <Icon className="h-4 w-4 text-muted-foreground" />
                            </div>
                            <div className="min-w-0">
                              <span className="font-medium truncate block">{ev.title}</span>
                              <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                                <Badge variant="secondary" className="text-[10px]">
                                  {getEvidenceLabel(ev.evidence_type)}
                                </Badge>
                                {ev.has_file && (
                                  <Badge variant="outline" className="text-[10px]">
                                    Archivo
                                  </Badge>
                                )}
                              </div>
                            </div>
                          </div>
                          <div className="flex gap-1 shrink-0">
                            {primaryHref && (
                              <a href={primaryHref} target="_blank" rel="noopener noreferrer">
                                <Button variant="ghost" size="icon" aria-label="Abrir evidencia" className="h-7 w-7">
                                  <ExternalLink className="h-3.5 w-3.5" />
                                </Button>
                              </a>
                            )}
                            {ev.has_file && downloadHref && (
                              <a href={downloadHref} target="_blank" rel="noopener noreferrer">
                                <Button variant="ghost" size="icon" aria-label="Descargar evidencia" className="h-7 w-7">
                                  <Download className="h-3.5 w-3.5" />
                                </Button>
                              </a>
                            )}
                            <Button variant="ghost" size="icon" aria-label="Editar evidencia" className="h-7 w-7" onClick={() => { setEditing(ev); setShowForm(true) }}>
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                            <Button variant="ghost" size="icon" aria-label="Eliminar evidencia" className="h-7 w-7 text-destructive" onClick={() => setDeleteTarget(ev)}>
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </div>
                        {ev.has_file ? (
                          <p className="mt-2 text-xs text-brand break-all">
                            {ev.file_name}
                            {ev.file_size_bytes ? ` · ${formatFileSize(ev.file_size_bytes)}` : ""}
                          </p>
                        ) : ev.url ? (
                          <a
                            href={ev.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="mt-2 text-xs text-brand hover:underline truncate block"
                          >
                            {ev.url}
                          </a>
                        ) : null}
                        {ev.description && (
                          <p className="mt-2 text-xs text-muted-foreground border-t pt-2">{ev.description}</p>
                        )}
                        {ev.creator_name && (
                          <p className="mt-1 text-[10px] text-muted-foreground">
                            por {ev.creator_name} · {new Date(ev.created_at).toLocaleDateString("es-ES")}
                          </p>
                        )}
                      </CardContent>
                    </Card>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      <Dialog open={showForm} onOpenChange={(open) => { setShowForm(open); if (!open) setEditing(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? "Editar evidencia" : "Nueva evidencia"}</DialogTitle>
          </DialogHeader>
          <EvidenceForm
            initial={editing}
            phases={phases}
            onSubmit={handleSubmit}
            loading={createMut.isPending || uploadMut.isPending || updateMut.isPending}
            onCancel={closeForm}
          />
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title="Eliminar evidencia"
        description={`Se eliminará "${deleteTarget?.title}". Esta acción no se puede deshacer.`}
        onConfirm={() => deleteTarget && deleteMut.mutate(deleteTarget.id)}
      />
    </div>
  )
}

function EvidenceForm({
  initial,
  phases,
  onSubmit,
  loading,
  onCancel,
}: {
  initial: ProjectEvidence | null
  phases: ProjectPhase[]
  onSubmit: (payload: EvidenceFormSubmit) => void
  loading: boolean
  onCancel: () => void
}) {
  const [title, setTitle] = useState(initial?.title ?? "")
  const [url, setUrl] = useState(initial?.url ?? "")
  const [evidenceType, setEvidenceType] = useState<EvidenceType>(initial?.evidence_type ?? "other")
  const [phaseId, setPhaseId] = useState<string>(initial?.phase_id?.toString() ?? "")
  const [description, setDescription] = useState(initial?.description ?? "")
  const [mode, setMode] = useState<"url" | "file">(initial?.has_file ? "file" : "url")
  const [file, setFile] = useState<File | null>(null)

  const handlePaste = (e: React.ClipboardEvent<HTMLDivElement>) => {
    const items = Array.from(e.clipboardData.items || [])
    const rawFile = items.find((item) => item.kind === "file")?.getAsFile()
    const pastedFile = rawFile
      ? new File(
          [rawFile],
          rawFile.name || `captura${rawFile.type === "image/png" ? ".png" : rawFile.type === "image/jpeg" ? ".jpg" : ""}`,
          { type: rawFile.type || "application/octet-stream" }
        )
      : null
    if (!pastedFile) return
    e.preventDefault()
    setMode("file")
    setFile(pastedFile)
    if (!title.trim() && pastedFile.name) {
      setTitle(pastedFile.name.replace(/\.[^.]+$/, ""))
    }
    toast.success("Captura pegada")
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return
    const data: ProjectEvidenceCreate = {
      title: title.trim(),
      evidence_type: evidenceType,
      phase_id: phaseId ? parseInt(phaseId) : null,
      description: description.trim() || null,
      url: mode === "url" ? (url.trim() || null) : null,
    }
    if (!initial && mode === "file") {
      if (!file) return
      onSubmit({ data, file })
      return
    }
    if (mode === "url" && !data.url) return
    onSubmit({ data, file: null })
  }

  const fileHelp = initial?.has_file
    ? "Esta evidencia ya tiene un archivo. Puedes editar metadatos, pero no reemplazarlo desde este formulario."
    : "Sube un archivo o pega una captura con Cmd/Ctrl+V."

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {!initial && (
        <div className="flex items-center gap-2">
          <Button type="button" variant={mode === "url" ? "default" : "outline"} size="sm" onClick={() => setMode("url")}>
            <Link2 className="h-3.5 w-3.5 mr-1.5" />
            URL
          </Button>
          <Button type="button" variant={mode === "file" ? "default" : "outline"} size="sm" onClick={() => setMode("file")}>
            <Upload className="h-3.5 w-3.5 mr-1.5" />
            Archivo o captura
          </Button>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label>Título *</Label>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Informe de ranking Q1" required />
        </div>
        <div>
          <Label>Tipo</Label>
          <Select value={evidenceType} onChange={(e) => setEvidenceType(e.target.value as EvidenceType)}>
            {EVIDENCE_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </Select>
        </div>
      </div>

      {mode === "url" ? (
        <div>
          <Label>URL *</Label>
          <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." required />
        </div>
      ) : (
        <div className="space-y-3">
          <div>
            <Label>Archivo</Label>
            <Input
              type="file"
              accept=".pdf,.jpg,.jpeg,.png,.gif,.webp,.doc,.docx,.xls,.xlsx,.txt,.csv,.zip"
              disabled={!!initial}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <p className="text-[11px] text-muted-foreground mt-1">{fileHelp}</p>
          </div>
          {!initial && (
            <div
              tabIndex={0}
              onPaste={handlePaste}
              className="rounded-lg border border-dashed border-border bg-muted/20 p-4 text-sm text-muted-foreground focus:outline-none focus:ring-1 focus:ring-brand"
            >
              <div className="flex items-center gap-2 mb-1">
                <Clipboard className="h-4 w-4" />
                <span className="font-medium text-foreground">Pegar desde portapapeles</span>
              </div>
              <p>Pega aquí una captura o archivo con Cmd/Ctrl+V.</p>
            </div>
          )}
          {initial?.has_file && (
            <div className="rounded-lg border border-border bg-muted/20 p-3 text-sm">
              <p className="font-medium text-foreground">{initial.file_name}</p>
              <p className="text-xs text-muted-foreground">
                {initial.file_size_bytes ? formatFileSize(initial.file_size_bytes) : ""}
              </p>
            </div>
          )}
          {file && !initial && (
            <div className="rounded-lg border border-border bg-muted/20 p-3 text-sm">
              <p className="font-medium text-foreground">{file.name}</p>
              <p className="text-xs text-muted-foreground">{formatFileSize(file.size)}</p>
            </div>
          )}
        </div>
      )}

      <div>
        <Label>Fase</Label>
        <Select value={phaseId} onChange={(e) => setPhaseId(e.target.value)}>
          <option value="">Sin fase</option>
          {phases.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </Select>
      </div>

      <div>
        <Label>Descripción</Label>
        <Textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Contexto o notas sobre esta evidencia..." rows={3} />
      </div>

      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>Cancelar</Button>
        <Button type="submit" disabled={loading || !title.trim() || (mode === "url" ? !url.trim() : !initial && !file)}>
          {loading ? "Guardando..." : initial ? "Guardar cambios" : mode === "file" ? "Subir evidencia" : "Crear evidencia"}
        </Button>
      </div>
    </form>
  )
}
