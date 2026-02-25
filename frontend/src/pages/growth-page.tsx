import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { growthApi } from "@/lib/api"
import type { GrowthIdeaCreate, GrowthFunnelStage, GrowthStatus } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Plus, Rocket, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { getErrorMessage } from "@/lib/utils"

const FUNNEL_STAGES: Record<GrowthFunnelStage, string> = {
    referral: "Referral",
    desire: "Desire",
    activate: "Activate",
    revenue: "Revenue",
    retention: "Retention",
    other: "Otros",
}

const STATUS_LABELS: Record<GrowthStatus, string> = {
    idea: "Idea / Backlog",
    in_progress: "En Progreso",
    completed: "Completado",
    discarded: "Descartado",
}

function iceColor(score: number) {
    if (score >= 500) return "text-success font-bold"
    if (score >= 200) return "text-brand font-semibold"
    return "text-muted-foreground"
}

export default function GrowthPage() {
    const queryClient = useQueryClient()
    const [showDialog, setShowDialog] = useState(false)
    const [deleteId, setDeleteId] = useState<number | null>(null)

    // Filters
    const [filterStatus, setFilterStatus] = useState<string>("")
    const [filterFunnel, setFilterFunnel] = useState<string>("")

    // Form State
    const [formData, setFormData] = useState<Partial<GrowthIdeaCreate>>({
        title: "",
        description: "",
        funnel_stage: "other",
        target_kpi: "",
        status: "idea",
        impact: 5,
        confidence: 5,
        ease: 5,
    })

    const { data: ideas = [], isLoading } = useQuery({
        queryKey: ["growth-ideas", filterStatus, filterFunnel],
        queryFn: () => growthApi.list({
            status: filterStatus || undefined,
            funnel_stage: filterFunnel || undefined
        }),
    })

    const createMutation = useMutation({
        mutationFn: (data: GrowthIdeaCreate) => growthApi.create(data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["growth-ideas"] })
            setShowDialog(false)
            toast.success("Idea añadida al backlog")
            setFormData({
                title: "", description: "", funnel_stage: "other", target_kpi: "", status: "idea", impact: 5, confidence: 5, ease: 5
            })
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al crear la idea")),
    })

    const updateMutation = useMutation({
        mutationFn: ({ id, data }: { id: number; data: Partial<GrowthIdeaCreate> }) => growthApi.update(id, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["growth-ideas"] })
            toast.success("Idea actualizada")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar la idea")),
    })

    const deleteMutation = useMutation({
        mutationFn: (id: number) => growthApi.delete(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["growth-ideas"] })
            setDeleteId(null)
            toast.success("Idea eliminada")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar la idea")),
    })

    const handleCreate = (e: React.FormEvent) => {
        e.preventDefault()
        if (!formData.title) return
        createMutation.mutate(formData as GrowthIdeaCreate)
    }

    const computedIce = (formData.impact || 5) * (formData.confidence || 5) * (formData.ease || 5)

    return (
        <div className="space-y-6 max-w-7xl mx-auto">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold flex items-center gap-2">
                        <Rocket className="h-6 w-6 text-brand" />
                        Growth Operations
                    </h1>
                    <p className="text-muted-foreground text-sm mt-1">
                        {ideas.length} ideas · Priorización ICE y gestión de experimentos
                    </p>
                </div>
                <Button onClick={() => setShowDialog(true)}>
                    <Plus className="h-4 w-4 mr-2" />
                    Nueva Idea
                </Button>
            </div>

            <div className="flex gap-4">
                <Select
                    value={filterFunnel}
                    onChange={(e) => setFilterFunnel(e.target.value)}
                    className="w-48"
                >
                    <option value="">Todo el Funnel</option>
                    {Object.entries(FUNNEL_STAGES).map(([k, v]) => (
                        <option key={k} value={k}>{v}</option>
                    ))}
                </Select>
                <Select
                    value={filterStatus}
                    onChange={(e) => setFilterStatus(e.target.value)}
                    className="w-48"
                >
                    <option value="">Cualquier estado</option>
                    <option value="idea">Sólo Ideas</option>
                    <option value="in_progress">En progreso</option>
                    <option value="completed">Completados</option>
                </Select>
            </div>

            <div className="bg-card rounded-xl border border-border overflow-hidden">
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>Experimento / Idea</TableHead>
                            <TableHead>Funnel</TableHead>
                            <TableHead>KPI</TableHead>
                            <TableHead className="text-center">I</TableHead>
                            <TableHead className="text-center">C</TableHead>
                            <TableHead className="text-center">E</TableHead>
                            <TableHead className="text-center font-bold">ICE Score</TableHead>
                            <TableHead>Estado</TableHead>
                            <TableHead className="text-right"></TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {ideas.length === 0 && !isLoading && (
                            <TableRow className="hover:bg-transparent">
                                <TableCell colSpan={9} className="py-12">
                                    <div className="flex flex-col items-center">
                                        <Rocket className="h-8 w-8 text-muted-foreground/30 mb-3" />
                                        <p className="text-sm font-medium text-foreground mb-1">Sin ideas</p>
                                        <p className="text-xs text-muted-foreground">Añade hipótesis, prioriza con ICE y trackea resultados.</p>
                                    </div>
                                </TableCell>
                            </TableRow>
                        )}
                        {ideas.map((idea) => (
                            <TableRow key={idea.id}>
                                <TableCell>
                                    <div className="font-medium">{idea.title}</div>
                                    {idea.description && (
                                        <div className="text-xs text-muted-foreground line-clamp-1 mt-0.5">{idea.description}</div>
                                    )}
                                </TableCell>
                                <TableCell>
                                    <Badge variant="outline" className="text-xs">
                                        {FUNNEL_STAGES[idea.funnel_stage as GrowthFunnelStage]}
                                    </Badge>
                                </TableCell>
                                <TableCell className="text-sm">{idea.target_kpi || "—"}</TableCell>
                                <TableCell className="text-center font-mono">{idea.impact}</TableCell>
                                <TableCell className="text-center font-mono">{idea.confidence}</TableCell>
                                <TableCell className="text-center font-mono">{idea.ease}</TableCell>
                                <TableCell className={`text-center font-mono text-lg ${iceColor(idea.ice_score)}`}>
                                    {idea.ice_score}
                                </TableCell>
                                <TableCell>
                                    <Select
                                        value={idea.status}
                                        onChange={(e) => updateMutation.mutate({ id: idea.id, data: { status: e.target.value as GrowthStatus } })}
                                        className="w-[130px] h-8 text-xs"
                                    >
                                        {Object.entries(STATUS_LABELS).map(([k, v]) => (
                                            <option key={k} value={k}>{v}</option>
                                        ))}
                                    </Select>
                                </TableCell>
                                <TableCell className="text-right">
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                                        onClick={() => setDeleteId(idea.id)}
                                    >
                                        <Trash2 className="h-4 w-4" />
                                    </Button>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>

            <Dialog open={showDialog} onOpenChange={setShowDialog}>
                <DialogHeader>
                    <DialogTitle>Añadir Idea al Backlog</DialogTitle>
                </DialogHeader>
                <form onSubmit={handleCreate} className="space-y-4 mt-4">
                    <div className="space-y-2">
                        <Label>Idea o Hipótesis</Label>
                        <Input
                            value={formData.title}
                            onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                            placeholder="Ej. Añadir Member Get Member gamificado"
                            required
                        />
                    </div>
                    <div className="space-y-2">
                        <Label>Contexto / Evidencias</Label>
                        <Textarea
                            value={formData.description || ""}
                            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                            placeholder="¿Por qué creemos que esto funcionará?"
                            rows={2}
                        />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-2">
                            <Label>Fase del Funnel</Label>
                            <Select
                                value={formData.funnel_stage}
                                onChange={(e) => setFormData({ ...formData, funnel_stage: e.target.value as GrowthFunnelStage })}
                            >
                                {Object.entries(FUNNEL_STAGES).map(([k, v]) => (
                                    <option key={k} value={k}>{v}</option>
                                ))}
                            </Select>
                        </div>
                        <div className="space-y-2">
                            <Label>KPI Objetivo</Label>
                            <Input
                                value={formData.target_kpi || ""}
                                onChange={(e) => setFormData({ ...formData, target_kpi: e.target.value })}
                                placeholder="Ej. Leads, MAU, SQLs"
                            />
                        </div>
                    </div>

                    <div className="pt-2 border-t mt-4">
                        <Label className="text-sm font-bold flex items-center justify-between mb-3">
                            <span>Puntuación I.C.E.</span>
                            <span className="text-xl text-brand font-mono">{computedIce}</span>
                        </Label>
                        <div className="grid grid-cols-3 gap-4">
                            <div className="space-y-2">
                                <Label className="text-xs text-muted-foreground">Impacto (1-10)</Label>
                                <Input
                                    type="number"
                                    min="1" max="10"
                                    value={formData.impact}
                                    onChange={(e) => setFormData({ ...formData, impact: Number(e.target.value) })}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label className="text-xs text-muted-foreground">Confianza (1-10)</Label>
                                <Input
                                    type="number"
                                    min="1" max="10"
                                    value={formData.confidence}
                                    onChange={(e) => setFormData({ ...formData, confidence: Number(e.target.value) })}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label className="text-xs text-muted-foreground">Facilidad (1-10)</Label>
                                <Input
                                    type="number"
                                    min="1" max="10"
                                    value={formData.ease}
                                    onChange={(e) => setFormData({ ...formData, ease: Number(e.target.value) })}
                                />
                            </div>
                        </div>
                    </div>

                    <div className="flex justify-end gap-2 pt-4">
                        <Button type="button" variant="outline" onClick={() => setShowDialog(false)}>
                            Cancelar
                        </Button>
                        <Button type="submit" disabled={createMutation.isPending || !formData.title}>
                            Guardar Idea
                        </Button>
                    </div>
                </form>
            </Dialog>

            <ConfirmDialog
                open={deleteId !== null}
                onOpenChange={(open) => !open && setDeleteId(null)}
                title="¿Eliminar idea?"
                description="Esta acción descartará esta idea permanentemente de la lista."
                onConfirm={() => {
                    if (deleteId) deleteMutation.mutate(deleteId)
                }}
            />
        </div>
    )
}
