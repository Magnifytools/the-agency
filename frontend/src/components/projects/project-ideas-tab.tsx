import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { growthApi } from "@/lib/api"
import type { GrowthIdea, GrowthIdeaCreate, GrowthStatus } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Plus, Lightbulb, Trash2, ArrowUpDown, Pencil, CheckSquare, Rocket } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  idea: { label: "Idea", color: "bg-blue-500/20 text-blue-300 border-blue-500/30" },
  in_progress: { label: "En progreso", color: "bg-brand/20 text-brand border-brand/30" },
  completed: { label: "Completado", color: "bg-success/20 text-success border-success/30" },
  discarded: { label: "Descartado", color: "bg-muted text-muted-foreground border-border" },
}

function iceColor(score: number) {
  if (score >= 8) return "text-success font-bold"
  if (score >= 5) return "text-brand font-semibold"
  return "text-muted-foreground"
}

function IceSlider({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <Label className="text-xs">{label}</Label>
        <span className={`text-sm font-mono ${iceColor(value)}`}>{value}</span>
      </div>
      <input
        type="range"
        min={1}
        max={10}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1.5 bg-muted rounded-lg appearance-none cursor-pointer accent-brand"
      />
    </div>
  )
}

interface ProjectIdeasTabProps {
  projectId: number
}

export function ProjectIdeasTab({ projectId }: ProjectIdeasTabProps) {
  const queryClient = useQueryClient()
  const [showDialog, setShowDialog] = useState(false)
  const [editingIdea, setEditingIdea] = useState<GrowthIdea | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [sortBy, setSortBy] = useState<"ice" | "status" | "recent">("ice")

  const [formData, setFormData] = useState<Partial<GrowthIdeaCreate>>({
    title: "",
    description: "",
    impact: 5,
    confidence: 5,
    ease: 5,
    status: "idea",
  })

  const { data: ideas = [], isLoading } = useQuery({
    queryKey: ["growth-ideas", "project", projectId],
    queryFn: () => growthApi.list({ project_id: projectId }),
  })

  const createMutation = useMutation({
    mutationFn: (data: GrowthIdeaCreate) => growthApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["growth-ideas", "project", projectId] })
      setShowDialog(false)
      toast.success("Idea añadida al buffer")
      resetForm()
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear idea")),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<GrowthIdeaCreate> }) => growthApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["growth-ideas", "project", projectId] })
      setEditingIdea(null)
      setShowDialog(false)
      toast.success("Idea actualizada")
      resetForm()
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar")),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => growthApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["growth-ideas", "project", projectId] })
      setDeleteId(null)
      toast.success("Idea eliminada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar")),
  })

  const resetForm = () => {
    setFormData({ title: "", description: "", impact: 5, confidence: 5, ease: 5, status: "idea" })
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.title?.trim()) return

    if (editingIdea) {
      updateMutation.mutate({ id: editingIdea.id, data: formData })
    } else {
      createMutation.mutate({ ...formData, project_id: projectId } as GrowthIdeaCreate)
    }
  }

  const openEdit = (idea: GrowthIdea) => {
    setEditingIdea(idea)
    setFormData({
      title: idea.title,
      description: idea.description || "",
      impact: idea.impact,
      confidence: idea.confidence,
      ease: idea.ease,
      status: idea.status,
    })
    setShowDialog(true)
  }

  const openCreate = () => {
    setEditingIdea(null)
    resetForm()
    setShowDialog(true)
  }

  const sortedIdeas = [...ideas].sort((a, b) => {
    if (sortBy === "ice") return b.ice_score - a.ice_score
    if (sortBy === "status") {
      const order = ["in_progress", "idea", "completed", "discarded"]
      return order.indexOf(a.status) - order.indexOf(b.status)
    }
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  })

  const activeIdeas = sortedIdeas.filter((i) => i.status !== "completed" && i.status !== "discarded")
  const doneIdeas = sortedIdeas.filter((i) => i.status === "completed" || i.status === "discarded")

  if (isLoading) {
    return <div className="text-center text-muted-foreground py-8">Cargando ideas...</div>
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Lightbulb className="w-4 h-4 text-brand" />
          <span className="text-sm text-muted-foreground">
            {activeIdeas.length} idea{activeIdeas.length !== 1 ? "s" : ""} activa{activeIdeas.length !== 1 ? "s" : ""}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setSortBy(sortBy === "ice" ? "status" : sortBy === "status" ? "recent" : "ice")}>
            <ArrowUpDown className="w-3.5 h-3.5 mr-1" />
            {sortBy === "ice" ? "ICE" : sortBy === "status" ? "Estado" : "Reciente"}
          </Button>
          <Button size="sm" onClick={openCreate}>
            <Plus className="w-3.5 h-3.5 mr-1" />
            Nueva idea
          </Button>
        </div>
      </div>

      {/* Ideas List */}
      {activeIdeas.length === 0 && doneIdeas.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center">
            <Lightbulb className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
            <p className="text-sm text-muted-foreground mb-3">
              No hay ideas en el buffer de este proyecto.
            </p>
            <p className="text-xs text-muted-foreground mb-4">
              Añade ideas, ordénalas por ICE y conviértelas en tareas cuando estén listas.
            </p>
            <Button size="sm" onClick={openCreate}>
              <Plus className="w-3.5 h-3.5 mr-1" />
              Añadir primera idea
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {activeIdeas.map((idea) => (
            <IdeaCard
              key={idea.id}
              idea={idea}
              onEdit={() => openEdit(idea)}
              onDelete={() => setDeleteId(idea.id)}
              onStatusChange={(status) => updateMutation.mutate({ id: idea.id, data: { status } })}
            />
          ))}

          {doneIdeas.length > 0 && (
            <details className="mt-4">
              <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground">
                {doneIdeas.length} completada{doneIdeas.length !== 1 ? "s" : ""} / descartada{doneIdeas.length !== 1 ? "s" : ""}
              </summary>
              <div className="space-y-2 mt-2 opacity-60">
                {doneIdeas.map((idea) => (
                  <IdeaCard
                    key={idea.id}
                    idea={idea}
                    onEdit={() => openEdit(idea)}
                    onDelete={() => setDeleteId(idea.id)}
                    onStatusChange={(status) => updateMutation.mutate({ id: idea.id, data: { status } })}
                  />
                ))}
              </div>
            </details>
          )}
        </div>
      )}

      {/* Create/Edit Dialog */}
      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingIdea ? "Editar idea" : "Nueva idea"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="idea_title">Título</Label>
              <Input
                id="idea_title"
                required
                placeholder="Ej: Optimizar landing de captación..."
                value={formData.title || ""}
                onChange={(e) => setFormData((p) => ({ ...p, title: e.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="idea_desc">Descripción</Label>
              <Textarea
                id="idea_desc"
                placeholder="Contexto, hipótesis, resultado esperado..."
                rows={3}
                value={formData.description || ""}
                onChange={(e) => setFormData((p) => ({ ...p, description: e.target.value }))}
              />
            </div>

            <div className="border border-border rounded-lg p-3 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Matriz ICE</span>
                <span className={`text-lg font-mono ${iceColor(((formData.impact || 5) + (formData.confidence || 5) + (formData.ease || 5)) / 3)}`}>
                  {(((formData.impact || 5) + (formData.confidence || 5) + (formData.ease || 5)) / 3).toFixed(1)}
                </span>
              </div>
              <IceSlider label="Impact" value={formData.impact || 5} onChange={(v) => setFormData((p) => ({ ...p, impact: v }))} />
              <IceSlider label="Confidence" value={formData.confidence || 5} onChange={(v) => setFormData((p) => ({ ...p, confidence: v }))} />
              <IceSlider label="Ease" value={formData.ease || 5} onChange={(v) => setFormData((p) => ({ ...p, ease: v }))} />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="ghost" onClick={() => setShowDialog(false)}>Cancelar</Button>
              <Button type="submit" disabled={createMutation.isPending || updateMutation.isPending}>
                {editingIdea ? "Guardar" : "Añadir al buffer"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirm */}
      <ConfirmDialog
        open={deleteId !== null}
        onOpenChange={(open) => { if (!open) setDeleteId(null) }}
        title="Eliminar idea"
        description="¿Seguro que quieres eliminar esta idea del buffer?"
        onConfirm={() => deleteId && deleteMutation.mutate(deleteId)}
      />
    </div>
  )
}

function IdeaCard({
  idea,
  onEdit,
  onDelete,
  onStatusChange,
}: {
  idea: GrowthIdea
  onEdit: () => void
  onDelete: () => void
  onStatusChange: (status: GrowthStatus) => void
}) {
  const status = STATUS_LABELS[idea.status] || STATUS_LABELS.idea

  return (
    <Card className="group hover:border-brand/30 transition-colors">
      <CardContent className="p-3">
        <div className="flex items-start gap-3">
          {/* ICE Score */}
          <div className="flex flex-col items-center min-w-[40px] pt-0.5">
            <span className={`text-lg font-mono leading-none ${iceColor(idea.ice_score)}`}>
              {idea.ice_score.toFixed(1)}
            </span>
            <span className="text-[10px] text-muted-foreground uppercase">ICE</span>
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-start gap-2">
              <h4 className="text-sm font-medium text-foreground truncate">{idea.title}</h4>
              <Badge variant="outline" className={`text-[10px] shrink-0 ${status.color}`}>
                {status.label}
              </Badge>
            </div>
            {idea.description && (
              <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{idea.description}</p>
            )}
            <div className="flex items-center gap-3 mt-1.5 text-[10px] text-muted-foreground">
              <span>I:{idea.impact}</span>
              <span>C:{idea.confidence}</span>
              <span>E:{idea.ease}</span>
              {idea.task_title && (
                <span className="flex items-center gap-0.5">
                  <CheckSquare className="w-3 h-3" />
                  {idea.task_title}
                </span>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            {idea.status === "idea" && (
              <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Marcar en progreso"
                onClick={() => onStatusChange("in_progress")}>
                <Rocket className="w-3.5 h-3.5" />
              </Button>
            )}
            {idea.status === "in_progress" && (
              <Button variant="ghost" size="sm" className="h-7 w-7 p-0" title="Marcar completada"
                onClick={() => onStatusChange("completed")}>
                <CheckSquare className="w-3.5 h-3.5" />
              </Button>
            )}
            <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={onEdit}>
              <Pencil className="w-3.5 h-3.5" />
            </Button>
            <Button variant="ghost" size="sm" className="h-7 w-7 p-0 text-destructive" onClick={onDelete}>
              <Trash2 className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
