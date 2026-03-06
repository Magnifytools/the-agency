import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { format } from "date-fns"
import { es } from "date-fns/locale"
import {
    Sparkles, Trash2, Download, ArrowLeft, Copy, Send, CheckCircle, XCircle,
    Calculator, TrendingUp, Mail
} from "lucide-react"
import { proposalsApi, investmentsApi } from "@/lib/api"
import type {
    Proposal, ProposalStatus, ProposalStatusUpdate,
    InvestmentCalculateResponse, Client,
} from "@/lib/types"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Dialog, DialogHeader, DialogTitle, DialogContent, DialogFooter } from "@/components/ui/dialog"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import { serviceTypeLabels } from "@/lib/constants"

const statusConfig: Record<ProposalStatus, { label: string; variant: "default" | "secondary" | "success" | "destructive" | "warning" }> = {
    draft: { label: "Borrador", variant: "secondary" },
    sent: { label: "Enviada", variant: "default" },
    accepted: { label: "Aceptada", variant: "success" },
    rejected: { label: "Rechazada", variant: "destructive" },
    expired: { label: "Expirada", variant: "warning" },
}

function isNonEmptyString(value: unknown): value is string {
    return typeof value === "string" && value.trim().length > 0
}

interface ProposalDetailProps {
    proposal: Proposal
    clients: Client[]
    onBack: () => void
    onEdit: (p: Proposal) => void
}

export function ProposalDetail({ proposal: p, clients, onBack, onEdit }: ProposalDetailProps) {
    const queryClient = useQueryClient()
    const [deleteId, setDeleteId] = useState<number | null>(null)
    const [roiDialogOpen, setRoiDialogOpen] = useState(false)
    const [roiResult, setRoiResult] = useState<InvestmentCalculateResponse | null>(null)
    const [roiForm, setRoiForm] = useState({
        business_model: "",
        aov: "",
        conversion_rate: "",
        ltv: "",
        seo_maturity: "",
        current_monthly_traffic: "",
        monthly_investment: "",
    })
    const [roiLoading, setRoiLoading] = useState(false)
    const [emailModal, setEmailModal] = useState<number | null>(null)
    const [aiDraft, setAiDraft] = useState<{ subject: string; body: string } | null>(null)
    const [aiDraftLoading, setAiDraftLoading] = useState(false)

    const sc = statusConfig[p.status]

    const statusMutation = useMutation({
        mutationFn: ({ id, data }: { id: number; data: ProposalStatusUpdate }) => proposalsApi.changeStatus(id, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["proposals"] })
            toast.success("Estado actualizado")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al cambiar estado")),
    })

    const deleteMutation = useMutation({
        mutationFn: (id: number) => proposalsApi.delete(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["proposals"] })
            setDeleteId(null)
            onBack()
            toast.success("Propuesta eliminada")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar")),
    })

    const duplicateMutation = useMutation({
        mutationFn: (id: number) => proposalsApi.duplicate(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["proposals"] })
            toast.success("Propuesta duplicada")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al duplicar")),
    })

    const generateMutation = useMutation({
        mutationFn: (id: number) => proposalsApi.generate(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["proposals"] })
            toast.success("Contenido generado con IA")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al generar contenido")),
    })

    const convertMutation = useMutation({
        mutationFn: (id: number) => proposalsApi.convert(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["proposals"] })
            toast.success("Propuesta convertida a proyecto")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al convertir")),
    })

    const openPdf = async (id: number) => {
        try {
            const blob = await proposalsApi.pdf(id)
            const url = URL.createObjectURL(blob)
            window.open(url, "_blank")
            setTimeout(() => URL.revokeObjectURL(url), 60000)
        } catch (err) {
            toast.error(getErrorMessage(err, "Error al abrir el PDF"))
        }
    }

    const openEmailModal = async (id: number) => {
        setEmailModal(id)
        setAiDraft(null)
        setAiDraftLoading(true)
        try {
            const draft = await proposalsApi.draftEmail(id)
            setAiDraft({ subject: draft.subject, body: draft.body })
        } catch {
            const contact = p.contact_name || p.company_name
            const mainPrice = p.pricing_options?.find(o => o.recommended)?.price ?? p.pricing_options?.[0]?.price
            const priceStr = mainPrice ? `${mainPrice.toLocaleString("es-ES")} €` : null
            const subject = `Propuesta ${p.title} — ${p.company_name}`
            const body = [
                `Hola ${contact},`,
                "",
                `Te adjunto la propuesta que hemos preparado para ${p.company_name}: "${p.title}".`,
                "",
                p.situation ? `Contexto: ${p.situation}` : null,
                p.opportunity ? `Oportunidad: ${p.opportunity}` : null,
                priceStr ? `Inversión: ${priceStr}` : null,
                p.valid_until ? `Válida hasta: ${new Date(p.valid_until).toLocaleDateString("es-ES")}` : null,
                "",
                "Quedo a tu disposición para resolver cualquier duda o concertar una llamada.",
                "",
                "Un saludo,",
            ].filter(l => l !== null).join("\n")
            setAiDraft({ subject, body })
        } finally {
            setAiDraftLoading(false)
        }
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center gap-3">
                <Button variant="ghost" size="sm" onClick={onBack}>
                    <ArrowLeft className="w-4 h-4 mr-1" /> Volver
                </Button>
            </div>

            <div className="flex flex-col sm:flex-row justify-between items-start gap-4">
                <div>
                    <div className="flex items-center gap-3 mb-2">
                        <h1 className="text-2xl font-bold tracking-tight">{p.title}</h1>
                        <Badge variant={sc.variant}>{sc.label}</Badge>
                    </div>
                    <p className="text-muted-foreground">
                        {p.company_name}{p.contact_name && ` · ${p.contact_name}`}
                        {p.service_type && ` · ${serviceTypeLabels[p.service_type] || p.service_type}`}
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">
                        Creada {format(new Date(p.created_at), "dd MMM yyyy", { locale: es })}
                        {p.created_by_name && ` por ${p.created_by_name}`}
                    </p>
                </div>

                <div className="flex flex-wrap gap-2">
                    {p.status === "draft" && (
                        <>
                            <Button size="sm" variant="outline" onClick={() => onEdit(p)}>Editar</Button>
                            <Button size="sm" variant="outline" onClick={() => generateMutation.mutate(p.id)} disabled={generateMutation.isPending}>
                                <Sparkles className="w-4 h-4 mr-1" />
                                {generateMutation.isPending ? "Generando..." : "Generar IA"}
                            </Button>
                            <Button size="sm" onClick={() => statusMutation.mutate({ id: p.id, data: { status: "sent" } })}>
                                <Send className="w-4 h-4 mr-1" /> Marcar Enviada
                            </Button>
                        </>
                    )}
                    {p.status === "sent" && (
                        <>
                            <Button size="sm" variant="outline" onClick={() => statusMutation.mutate({ id: p.id, data: { status: "accepted" } })}>
                                <CheckCircle className="w-4 h-4 mr-1" /> Aceptada
                            </Button>
                            <Button size="sm" variant="outline" onClick={() => statusMutation.mutate({ id: p.id, data: { status: "rejected" } })}>
                                <XCircle className="w-4 h-4 mr-1" /> Rechazada
                            </Button>
                        </>
                    )}
                    {p.status === "accepted" && !p.converted_project_id && (
                        <Button size="sm" onClick={() => convertMutation.mutate(p.id)} disabled={convertMutation.isPending}>
                            Convertir a Proyecto
                        </Button>
                    )}
                    <Button size="sm" variant="outline" onClick={() => openPdf(p.id)}>
                        <Download className="w-4 h-4 mr-1" /> PDF
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => openEmailModal(p.id)} title="Enviar por email">
                        <Mail className="w-4 h-4 mr-1" /> Enviar email
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setRoiDialogOpen(true)}>
                        <Calculator className="w-4 h-4 mr-1" /> Calculadora ROI
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => duplicateMutation.mutate(p.id)}>
                        <Copy className="w-4 h-4 mr-1" /> Duplicar
                    </Button>
                    {p.status === "draft" && (
                        <Button size="sm" variant="ghost" aria-label="Eliminar" onClick={() => setDeleteId(p.id)}>
                            <Trash2 className="w-4 h-4 text-destructive" />
                        </Button>
                    )}
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Main content */}
                <div className="lg:col-span-2 space-y-6">
                    {(p.situation || p.problem || p.opportunity || p.approach) && (
                        <Card>
                            <CardContent className="p-6 space-y-4">
                                <h3 className="font-semibold text-lg">Contexto de la propuesta</h3>
                                {p.situation && (
                                    <div>
                                        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Situación</p>
                                        <p className="text-sm whitespace-pre-wrap">{p.situation}</p>
                                    </div>
                                )}
                                {p.problem && (
                                    <div>
                                        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Problema</p>
                                        <p className="text-sm whitespace-pre-wrap">{p.problem}</p>
                                    </div>
                                )}
                                {p.cost_of_inaction && (
                                    <div>
                                        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Coste de no actuar</p>
                                        <p className="text-sm whitespace-pre-wrap">{p.cost_of_inaction}</p>
                                    </div>
                                )}
                                {p.opportunity && (
                                    <div>
                                        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Oportunidad</p>
                                        <p className="text-sm whitespace-pre-wrap">{p.opportunity}</p>
                                    </div>
                                )}
                                {p.approach && (
                                    <div>
                                        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Enfoque</p>
                                        <p className="text-sm whitespace-pre-wrap">{p.approach}</p>
                                    </div>
                                )}
                                {p.relevant_cases && (
                                    <div>
                                        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Casos relevantes</p>
                                        <p className="text-sm whitespace-pre-wrap">{p.relevant_cases}</p>
                                    </div>
                                )}
                            </CardContent>
                        </Card>
                    )}

                    {p.pricing_options && p.pricing_options.length > 0 && (
                        <Card>
                            <CardContent className="p-6">
                                <h3 className="font-semibold text-lg mb-4">Opciones de precio</h3>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    {p.pricing_options.map((opt, i) => (
                                        <div key={i} className={`rounded-lg border p-4 ${opt.recommended ? "border-brand bg-brand/5" : "border-border"}`}>
                                            {opt.recommended && <span className="text-xs font-medium text-brand uppercase tracking-wide">Recomendado</span>}
                                            <h4 className="font-semibold mt-1">{opt.name}</h4>
                                            <p className="text-2xl font-bold mt-2">
                                                {opt.price.toLocaleString("es-ES")}
                                                <span className="text-sm font-normal text-muted-foreground"> {opt.is_recurring ? "\u20AC/mes" : "\u20AC"}</span>
                                            </p>
                                            {opt.description && <p className="text-sm text-muted-foreground mt-2">{opt.description}</p>}
                                            {opt.ideal_for && <p className="text-xs text-muted-foreground mt-1">Ideal para: {opt.ideal_for}</p>}
                                        </div>
                                    ))}
                                </div>
                            </CardContent>
                        </Card>
                    )}

                    {p.generated_content && Object.keys(p.generated_content).length > 0 && (() => {
                        const gc = p.generated_content as Record<string, unknown>
                        const labelMap: Record<string, string> = {
                            executive_summary: "Resumen ejecutivo",
                            opening: "Apertura",
                            situation: "Situación actual",
                            problem: "El reto",
                            cost_of_inaction: "Coste de no actuar",
                            null_case: "Escenario sin acción",
                            opportunity: "La oportunidad",
                            approach: "Nuestra propuesta",
                            phases: "Fases del proyecto",
                            includes: "Qué incluye",
                            excludes: "Qué no incluye",
                            success_metrics: "Métricas de éxito",
                            credibility: "Sobre Magnify",
                            cases: "Casos de éxito",
                            next_steps: "Siguientes pasos",
                            investment_model: "Modelo de inversión",
                        }
                        return (
                        <Card>
                            <CardContent className="p-6">
                                <h3 className="font-semibold text-lg mb-4 flex items-center gap-2">
                                    <Sparkles className="w-5 h-5 text-brand" /> Contenido generado por IA
                                </h3>
                                <div className="space-y-4">
                                    {isNonEmptyString(gc.executive_summary) && (
                                        <div className="bg-blue-500/5 border border-blue-500/20 rounded-lg p-4">
                                            <p className="text-xs font-medium text-blue-400 uppercase tracking-wide mb-2">Resumen ejecutivo</p>
                                            <p className="text-sm font-medium">{gc.executive_summary}</p>
                                        </div>
                                    )}

                                    {isNonEmptyString(gc.null_case) && (
                                        <div className="bg-orange-500/5 border-l-2 border-orange-500 rounded-r-lg p-4">
                                            <p className="text-xs font-medium text-orange-400 uppercase tracking-wide mb-2">Escenario sin acción</p>
                                            <p className="text-sm">{gc.null_case}</p>
                                        </div>
                                    )}

                                    {Array.isArray(gc.success_metrics) && gc.success_metrics.length > 0 && (
                                        <div>
                                            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Métricas de éxito</p>
                                            <div className="border border-border rounded-lg overflow-hidden">
                                                <table className="w-full text-sm" aria-label="Métricas de éxito">
                                                    <thead>
                                                        <tr className="bg-secondary/50">
                                                            <th className="text-left p-2 font-medium">Métrica</th>
                                                            <th className="text-left p-2 font-medium">Actual</th>
                                                            <th className="text-left p-2 font-medium">Objetivo 12m</th>
                                                            <th className="text-left p-2 font-medium">Impacto</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                                        {(gc.success_metrics as Array<{metric: string; current: string; target_12m: string; impact: string}>).map((m, i) => (
                                                            <tr key={i} className="border-t border-border">
                                                                <td className="p-2 font-medium">{m.metric}</td>
                                                                <td className="p-2">{m.current}</td>
                                                                <td className="p-2">{m.target_12m}</td>
                                                                <td className="p-2">{m.impact}</td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            </div>
                                        </div>
                                    )}

                                    {Array.isArray(gc.phases) && gc.phases.length > 0 && (
                                        <div>
                                            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Fases del proyecto</p>
                                            <div className="space-y-2">
                                                {(gc.phases as Array<{name: string; duration: string; outcome: string}>).map((phase, i) => (
                                                    <div key={i} className="bg-secondary/30 border-l-2 border-foreground/30 rounded-r-lg p-3">
                                                        <div className="flex justify-between items-baseline">
                                                            <span className="font-medium text-sm">{phase.name}</span>
                                                            <span className="text-xs text-muted-foreground">{phase.duration}</span>
                                                        </div>
                                                        <p className="text-xs text-muted-foreground mt-1">{phase.outcome}</p>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {Object.entries(gc)
                                        .filter(([key]) => !["executive_summary", "null_case", "success_metrics", "phases", "investment_model"].includes(key))
                                        .filter(([, value]) => value && typeof value === "string")
                                        .map(([key, value]) => (
                                        <div key={key}>
                                            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">
                                                {labelMap[key] || key.replace(/_/g, " ")}
                                            </p>
                                            <p className="text-sm whitespace-pre-wrap">{String(value)}</p>
                                        </div>
                                    ))}
                                </div>
                            </CardContent>
                        </Card>
                        )
                    })()}
                </div>

                {/* Sidebar */}
                <div className="space-y-6">
                    <Card>
                        <CardContent className="p-6 space-y-4">
                            <h3 className="font-semibold">Datos internos</h3>
                            <div className="space-y-3 text-sm">
                                <div className="flex justify-between">
                                    <span className="text-muted-foreground">David (horas)</span>
                                    <span className="font-medium">{p.internal_hours_david ?? "\u2014"}</span>
                                </div>
                                <div className="flex justify-between">
                                    <span className="text-muted-foreground">Nacho (horas)</span>
                                    <span className="font-medium">{p.internal_hours_nacho ?? "\u2014"}</span>
                                </div>
                                <div className="flex justify-between border-t border-border pt-2">
                                    <span className="text-muted-foreground">Coste estimado</span>
                                    <span className="font-medium">
                                        {p.internal_cost_estimate ? `${p.internal_cost_estimate.toLocaleString("es-ES")} \u20AC` : "\u2014"}
                                    </span>
                                </div>
                                <div className="flex justify-between">
                                    <span className="text-muted-foreground">Margen estimado</span>
                                    <span className={`font-medium ${
                                        (p.estimated_margin_percent || 0) >= 50
                                            ? "text-green-400"
                                            : (p.estimated_margin_percent || 0) >= 30
                                                ? "text-yellow-400"
                                                : "text-red-400"
                                    }`}>
                                        {p.estimated_margin_percent ? `${p.estimated_margin_percent}%` : "\u2014"}
                                    </span>
                                </div>
                            </div>
                        </CardContent>
                    </Card>

                    <Card>
                        <CardContent className="p-6 space-y-3 text-sm">
                            <h3 className="font-semibold">Detalles</h3>
                            {p.lead_company && (
                                <div className="flex justify-between">
                                    <span className="text-muted-foreground">Lead</span>
                                    <span>{p.lead_company}</span>
                                </div>
                            )}
                            {p.client_name && (
                                <div className="flex justify-between">
                                    <span className="text-muted-foreground">Cliente</span>
                                    <span>{p.client_name}</span>
                                </div>
                            )}
                            {p.valid_until && (
                                <div className="flex justify-between">
                                    <span className="text-muted-foreground">Valida hasta</span>
                                    <span>{format(new Date(p.valid_until), "dd/MM/yyyy")}</span>
                                </div>
                            )}
                            {p.sent_at && (
                                <div className="flex justify-between">
                                    <span className="text-muted-foreground">Enviada</span>
                                    <span>{format(new Date(p.sent_at), "dd/MM/yyyy")}</span>
                                </div>
                            )}
                            {p.responded_at && (
                                <div className="flex justify-between">
                                    <span className="text-muted-foreground">Respondida</span>
                                    <span>{format(new Date(p.responded_at), "dd/MM/yyyy")}</span>
                                </div>
                            )}
                            {p.converted_project_id && (
                                <div className="flex justify-between">
                                    <span className="text-muted-foreground">Proyecto</span>
                                    <span className="text-brand">#{p.converted_project_id}</span>
                                </div>
                            )}
                        </CardContent>
                    </Card>
                </div>
            </div>

            <ConfirmDialog
                open={!!deleteId}
                onOpenChange={(open) => !open && setDeleteId(null)}
                title="Eliminar Propuesta"
                description="Solo se pueden eliminar propuestas en borrador. Esta accion no se puede deshacer."
                onConfirm={() => deleteMutation.mutate(deleteId!)}
            />

            {/* ROI Calculator Dialog */}
            <Dialog open={roiDialogOpen} onOpenChange={(open) => { setRoiDialogOpen(open); if (!open) setRoiResult(null) }}>
                <DialogHeader>
                    <DialogTitle>Calculadora ROI SEO</DialogTitle>
                </DialogHeader>
                <DialogContent>
                    {!roiResult ? (
                        <div className="space-y-3">
                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <Label>Modelo de negocio</Label>
                                    <Select value={roiForm.business_model} onChange={e => setRoiForm(f => ({ ...f, business_model: e.target.value }))}>
                                        <option value="">Seleccionar...</option>
                                        <option value="ecommerce">E-commerce</option>
                                        <option value="saas">SaaS</option>
                                        <option value="lead_gen">Lead Generation</option>
                                        <option value="media">Media / Publisher</option>
                                    </Select>
                                </div>
                                <div>
                                    <Label>AOV (\u20AC)</Label>
                                    <Input type="number" value={roiForm.aov} onChange={e => setRoiForm(f => ({ ...f, aov: e.target.value }))} placeholder="100" />
                                </div>
                                <div>
                                    <Label>Conversión (%)</Label>
                                    <Input type="number" step="0.1" value={roiForm.conversion_rate} onChange={e => setRoiForm(f => ({ ...f, conversion_rate: e.target.value }))} placeholder="2.5" />
                                </div>
                                <div>
                                    <Label>LTV (\u20AC)</Label>
                                    <Input type="number" value={roiForm.ltv} onChange={e => setRoiForm(f => ({ ...f, ltv: e.target.value }))} placeholder="200" />
                                </div>
                                <div>
                                    <Label>Tráfico mensual actual</Label>
                                    <Input type="number" value={roiForm.current_monthly_traffic} onChange={e => setRoiForm(f => ({ ...f, current_monthly_traffic: e.target.value }))} placeholder="5000" />
                                </div>
                                <div>
                                    <Label>Inversion mensual (\u20AC)</Label>
                                    <Input type="number" value={roiForm.monthly_investment} onChange={e => setRoiForm(f => ({ ...f, monthly_investment: e.target.value }))} placeholder="2000" />
                                </div>
                                <div className="col-span-2">
                                    <Label>Madurez SEO</Label>
                                    <Select value={roiForm.seo_maturity} onChange={e => setRoiForm(f => ({ ...f, seo_maturity: e.target.value }))}>
                                        <option value="">Seleccionar...</option>
                                        <option value="none">Sin SEO</option>
                                        <option value="basic">Básico</option>
                                        <option value="intermediate">Intermedio</option>
                                        <option value="advanced">Avanzado</option>
                                    </Select>
                                </div>
                            </div>
                            <DialogFooter>
                                <Button variant="outline" onClick={() => {
                                    if (p.client_id) {
                                        const clientData = clients.find(c => c.id === p.client_id)
                                        if (clientData) {
                                            setRoiForm(f => ({
                                                ...f,
                                                business_model: clientData.business_model || f.business_model,
                                                aov: clientData.aov?.toString() || f.aov,
                                                conversion_rate: clientData.conversion_rate?.toString() || f.conversion_rate,
                                                ltv: clientData.ltv?.toString() || f.ltv,
                                                seo_maturity: clientData.seo_maturity_level || f.seo_maturity,
                                            }))
                                        }
                                    }
                                }}>Autorellenar de cliente</Button>
                                <Button onClick={async () => {
                                    setRoiLoading(true)
                                    try {
                                        const res = await investmentsApi.calculate({
                                            client_id: p.client_id,
                                            proposal_id: p.id,
                                            business_model: roiForm.business_model || undefined,
                                            aov: roiForm.aov ? Number(roiForm.aov) : undefined,
                                            conversion_rate: roiForm.conversion_rate ? Number(roiForm.conversion_rate) : undefined,
                                            ltv: roiForm.ltv ? Number(roiForm.ltv) : undefined,
                                            seo_maturity: roiForm.seo_maturity || undefined,
                                            current_monthly_traffic: roiForm.current_monthly_traffic ? Number(roiForm.current_monthly_traffic) : undefined,
                                            monthly_investment: roiForm.monthly_investment ? Number(roiForm.monthly_investment) : undefined,
                                        })
                                        setRoiResult(res)
                                    } catch (err) {
                                        toast.error(getErrorMessage(err))
                                    } finally {
                                        setRoiLoading(false)
                                    }
                                }} disabled={roiLoading}>
                                    {roiLoading ? "Calculando..." : "Calcular ROI"}
                                </Button>
                            </DialogFooter>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            <div className="grid grid-cols-3 gap-3">
                                <div className="bg-secondary/30 rounded-lg p-3 text-center">
                                    <p className="text-xs text-muted-foreground">Break-even</p>
                                    <p className="text-lg font-bold">Mes {roiResult.summary.break_even_month ?? "N/A"}</p>
                                </div>
                                <div className="bg-secondary/30 rounded-lg p-3 text-center">
                                    <p className="text-xs text-muted-foreground">ROI Ano 1</p>
                                    <p className="text-lg font-bold">{roiResult.summary.year1_roi_range}</p>
                                </div>
                                <div className="bg-secondary/30 rounded-lg p-3 text-center">
                                    <p className="text-xs text-muted-foreground">Ingresos Ano 1</p>
                                    <p className="text-lg font-bold text-xs">{roiResult.summary.year1_revenue_range}</p>
                                </div>
                            </div>

                            <div className="space-y-2">
                                <p className="text-sm font-medium">Escenarios</p>
                                <div className="grid grid-cols-3 gap-2">
                                    {roiResult.scenarios.map(s => (
                                        <div key={s.key} className="border border-border rounded-lg p-3">
                                            <p className="text-xs font-medium mb-2">{s.label}</p>
                                            <div className="space-y-1 text-xs">
                                                <p>Tráfico: <span className="font-medium text-green-400">+{s.traffic_increase.toLocaleString("es-ES")}</span></p>
                                                <p>Conversiones: <span className="font-medium">+{s.new_conversions}</span></p>
                                                <p>Ingresos: <span className="font-medium">{s.revenue_increase.toLocaleString("es-ES")}\u20AC</span></p>
                                                <p>ROI: <span className="font-bold">{s.roi_percent}%</span></p>
                                                {s.payback_months && <p>Payback: <span className="font-medium">mes {s.payback_months}</span></p>}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            <details className="text-sm">
                                <summary className="cursor-pointer font-medium mb-2">Proyección mensual (moderado)</summary>
                                <div className="border border-border rounded-lg overflow-hidden">
                                    <table className="w-full text-xs" aria-label="Proyección mensual">
                                        <thead>
                                            <tr className="bg-secondary/50">
                                                <th className="p-1.5 text-left">Mes</th>
                                                <th className="p-1.5 text-right">Tráfico</th>
                                                <th className="p-1.5 text-right">Conv.</th>
                                                <th className="p-1.5 text-right">Ingresos</th>
                                                <th className="p-1.5 text-right">ROI</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {roiResult.monthly_projection.map(r => (
                                                <tr key={r.month} className="border-t border-border">
                                                    <td className="p-1.5">{r.month}</td>
                                                    <td className="p-1.5 text-right">{r.traffic.toLocaleString("es-ES")}</td>
                                                    <td className="p-1.5 text-right">{r.conversions}</td>
                                                    <td className="p-1.5 text-right">{r.revenue.toLocaleString("es-ES")}\u20AC</td>
                                                    <td className="p-1.5 text-right">{r.roi}%</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </details>

                            <DialogFooter>
                                <Button variant="outline" onClick={() => setRoiResult(null)}>Recalcular</Button>
                                <Button onClick={async () => {
                                    try {
                                        const currentContent = p.generated_content || {}
                                        await proposalsApi.update(p.id, {
                                            generated_content: {
                                                ...currentContent,
                                                investment_model: {
                                                    scenarios: roiResult.scenarios,
                                                    summary: roiResult.summary,
                                                    assumptions: roiResult.assumptions,
                                                },
                                            },
                                        })
                                        queryClient.invalidateQueries({ queryKey: ["proposals"] })
                                        toast.success("Modelo de inversión incluido en la propuesta")
                                        setRoiDialogOpen(false)
                                        setRoiResult(null)
                                    } catch (err) {
                                        toast.error(getErrorMessage(err))
                                    }
                                }}>
                                    <TrendingUp className="w-4 h-4 mr-1" /> Incluir en propuesta
                                </Button>
                            </DialogFooter>
                        </div>
                    )}
                </DialogContent>
            </Dialog>

            {/* Email Draft Dialog */}
            <Dialog open={emailModal !== null} onOpenChange={(o) => !o && setEmailModal(null)}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            Borrador de email
                            <span className="text-xs font-normal text-muted-foreground bg-muted px-1.5 py-0.5 rounded">Generado con IA</span>
                        </DialogTitle>
                    </DialogHeader>
                    {aiDraftLoading ? (
                        <div className="flex flex-col items-center justify-center py-12 gap-3 text-muted-foreground">
                            <div className="h-6 w-6 rounded-full border-2 border-brand border-t-transparent animate-spin" />
                            <p className="text-sm">Redactando con IA...</p>
                        </div>
                    ) : aiDraft ? (
                        <div className="space-y-4 p-1">
                            <div>
                                <Label className="text-xs text-muted-foreground">Asunto</Label>
                                <div className="flex items-center gap-2 mt-1">
                                    <Input readOnly value={aiDraft.subject} className="font-medium" />
                                    <Button variant="ghost" size="icon" aria-label="Copiar asunto" className="shrink-0" onClick={() => { navigator.clipboard.writeText(aiDraft.subject); toast.success("Asunto copiado") }}>
                                        <Copy className="w-4 h-4" />
                                    </Button>
                                </div>
                            </div>
                            <div>
                                <Label className="text-xs text-muted-foreground">Cuerpo</Label>
                                <div className="relative mt-1">
                                    <Textarea readOnly value={aiDraft.body} rows={10} className="text-xs resize-none" />
                                    <Button variant="ghost" size="icon" aria-label="Copiar cuerpo" className="absolute top-1 right-1" onClick={() => { navigator.clipboard.writeText(aiDraft.body); toast.success("Texto copiado") }}>
                                        <Copy className="w-4 h-4" />
                                    </Button>
                                </div>
                            </div>
                            <p className="text-xs text-muted-foreground">Copia el texto, pegalo en tu cliente de email y adjunta el PDF de la propuesta.</p>
                            <div className="flex justify-end gap-2">
                                <Button variant="outline" onClick={() => setEmailModal(null)}>Cerrar</Button>
                                <Button onClick={() => { navigator.clipboard.writeText(`Asunto: ${aiDraft.subject}\n\n${aiDraft.body}`); toast.success("Email completo copiado") }}>
                                    <Copy className="w-4 h-4 mr-1" /> Copiar todo
                                </Button>
                            </div>
                        </div>
                    ) : null}
                </DialogContent>
            </Dialog>
        </div>
    )
}
