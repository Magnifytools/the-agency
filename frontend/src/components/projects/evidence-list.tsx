import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Camera, FileBarChart, BarChart3, TrendingUp, FileText, Package, Link2, Plus, Pencil, Trash2, ExternalLink } from "lucide-react"
import { toast } from "sonner"
import { evidenceApi } from "@/lib/api"
import type { ProjectEvidence, ProjectEvidenceCreate, EvidenceType, ProjectPhase } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
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
  { value: "other", label: "Otro", icon: Link2 },
]

function getEvidenceIcon(type: EvidenceType) {
  return EVIDENCE_TYPES.find((t) => t.value === type)?.icon ?? Link2
}

function getEvidenceLabel(type: EvidenceType) {
  return EVIDENCE_TYPES.find((t) => t.value === type)?.label ?? type
}

interface Props {
  projectId: number
  phases: ProjectPhase[]
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

  const createMut = useMutation({
    mutationFn: (data: ProjectEvidenceCreate) => evidenceApi.create(projectId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-evidence", projectId] })
      setShowForm(false)
      toast.success("Evidencia creada")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ProjectEvidenceCreate> }) =>
      evidenceApi.update(projectId, id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project-evidence", projectId] })
      setEditing(null)
      setShowForm(false)
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

  if (isLoading) return <p className="text-muted-foreground text-sm">Cargando evidencia...</p>

  // Group by phase
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
          No hay evidencia registrada. Anade URLs de screenshots, informes, rankings, etc.
        </p>
      ) : (
        <div className="space-y-6">
          {[...grouped.entries()].map(([phaseName, items]) => (
            <div key={phaseName}>
              <h4 className="text-sm font-medium text-muted-foreground mb-3">{phaseName}</h4>
              <div className="grid gap-3 sm:grid-cols-2">
                {items.map((ev) => {
                  const Icon = getEvidenceIcon(ev.evidence_type)
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
                              <Badge variant="secondary" className="text-[10px] mt-0.5">
                                {getEvidenceLabel(ev.evidence_type)}
                              </Badge>
                            </div>
                          </div>
                          <div className="flex gap-1 shrink-0">
                            <a href={ev.url} target="_blank" rel="noopener noreferrer">
                              <Button variant="ghost" size="icon" className="h-7 w-7">
                                <ExternalLink className="h-3.5 w-3.5" />
                              </Button>
                            </a>
                            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => { setEditing(ev); setShowForm(true) }}>
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                            <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => setDeleteTarget(ev)}>
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </div>
                        <a
                          href={ev.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-2 text-xs text-brand hover:underline truncate block"
                        >
                          {ev.url}
                        </a>
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

      {/* Create/Edit Dialog */}
      <Dialog open={showForm} onOpenChange={setShowForm}>
        <DialogHeader>
          <DialogTitle>{editing ? "Editar evidencia" : "Nueva evidencia"}</DialogTitle>
        </DialogHeader>
        <EvidenceForm
          initial={editing}
          phases={phases}
          onSubmit={(data) => {
            if (editing) {
              updateMut.mutate({ id: editing.id, data })
            } else {
              createMut.mutate(data)
            }
          }}
          loading={createMut.isPending || updateMut.isPending}
          onCancel={() => setShowForm(false)}
        />
      </Dialog>

      {/* Delete Confirm */}
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
  onSubmit: (data: ProjectEvidenceCreate) => void
  loading: boolean
  onCancel: () => void
}) {
  const [title, setTitle] = useState(initial?.title ?? "")
  const [url, setUrl] = useState(initial?.url ?? "")
  const [evidenceType, setEvidenceType] = useState<EvidenceType>(initial?.evidence_type ?? "other")
  const [phaseId, setPhaseId] = useState<string>(initial?.phase_id?.toString() ?? "")
  const [description, setDescription] = useState(initial?.description ?? "")

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim() || !url.trim()) return
    onSubmit({
      title: title.trim(),
      url: url.trim(),
      evidence_type: evidenceType,
      phase_id: phaseId ? parseInt(phaseId) : null,
      description: description.trim() || null,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 p-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label>Título *</Label>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Informe de ranking Q1" required />
        </div>
        <div>
          <Label>Tipo</Label>
          <Select
            value={evidenceType}
            onChange={(e) => setEvidenceType(e.target.value as EvidenceType)}
          >
            {EVIDENCE_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </Select>
        </div>
      </div>
      <div>
        <Label>URL *</Label>
        <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." required />
      </div>
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
        <Textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Contexto o notas sobre esta evidencia..." rows={2} />
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>Cancelar</Button>
        <Button type="submit" disabled={loading || !title.trim() || !url.trim()}>
          {loading ? "Guardando..." : initial ? "Guardar" : "Crear"}
        </Button>
      </div>
    </form>
  )
}
