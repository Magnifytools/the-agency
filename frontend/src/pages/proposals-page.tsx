import { useState, useMemo, useEffect } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useLocation } from "react-router-dom"
import { format } from "date-fns"
import { es } from "date-fns/locale"
import {
    FileText, Plus, Trash2, Download, ArrowLeft, Copy, Sparkles,
    Send, CheckCircle, XCircle, ChevronRight, ChevronLeft,
    Building2, Euro, AlertTriangle, Calculator, TrendingUp, Mail
} from "lucide-react"
import { proposalsApi, serviceTemplatesApi, leadsApi, clientsApi, investmentsApi } from "@/lib/api"
import type {
    Proposal, ProposalCreate, ProposalUpdate, ProposalStatus, ProposalStatusUpdate,
    ServiceType, PricingOption, InvestmentCalculateResponse,
} from "@/lib/types"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Dialog, DialogHeader, DialogTitle, DialogContent, DialogFooter } from "@/components/ui/dialog"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

// --- Config ---
const statusConfig: Record<ProposalStatus, { label: string; variant: "default" | "secondary" | "success" | "destructive" | "warning" }> = {
    draft: { label: "Borrador", variant: "secondary" },
    sent: { label: "Enviada", variant: "default" },
    accepted: { label: "Aceptada", variant: "success" },
    rejected: { label: "Rechazada", variant: "destructive" },
    expired: { label: "Expirada", variant: "warning" },
}

const serviceTypeLabels: Record<ServiceType, string> = {
    seo_sprint: "SEO Sprint",
    migration: "Migracion Web",
    market_study: "Estudio de Mercado",
    consulting_retainer: "Consultoria SEO",
    partnership_retainer: "Partnership SEO",
    brand_audit: "Brand Audit",
    custom: "Personalizado",
}

// --- Types ---
type View = "list" | "detail"

interface WizardForm {
    title: string
    lead_id: number | null
    client_id: number | null
    contact_name: string
    company_name: string
    service_type: ServiceType | null
    // Revenue fields (step 2)
    business_model: string
    aov: string
    conversion_rate: string
    ltv: string
    seo_maturity_level: string
    current_monthly_traffic: string
    save_to_client: boolean
    // Context fields
    situation: string
    problem: string
    cost_of_inaction: string
    opportunity: string
    approach: string
    relevant_cases: string
    pricing_options: PricingOption[]
    internal_hours_david: number | null
    internal_hours_nacho: number | null
    valid_until: string
}

const emptyForm: WizardForm = {
    title: "",
    lead_id: null,
    client_id: null,
    contact_name: "",
    company_name: "",
    service_type: null,
    business_model: "",
    aov: "",
    conversion_rate: "",
    ltv: "",
    seo_maturity_level: "",
    current_monthly_traffic: "",
    save_to_client: false,
    situation: "",
    problem: "",
    cost_of_inaction: "",
    opportunity: "",
    approach: "",
    relevant_cases: "",
    pricing_options: [],
    internal_hours_david: null,
    internal_hours_nacho: null,
    valid_until: "",
}

const emptyPricing: PricingOption = {
    name: "",
    description: "",
    ideal_for: "",
    price: 0,
    is_recurring: false,
    recommended: false,
}

const DAVID_RATE = 50
const NACHO_RATE = 30

function isNonEmptyString(value: unknown): value is string {
    return typeof value === "string" && value.trim().length > 0
}

function generateEmailDraft(p: Proposal): { subject: string; body: string } {
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
    return { subject, body }
}

function RoiPreviewStep({ form }: { form: WizardForm }) {
    const [result, setResult] = useState<InvestmentCalculateResponse | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const hasRequiredFields = form.business_model && form.aov && form.conversion_rate && form.ltv && form.current_monthly_traffic

    useEffect(() => {
        if (!hasRequiredFields) return

        // Get monthly_investment from recommended pricing
        let monthlyInvestment: number | undefined
        const recommended = form.pricing_options.find(o => o.recommended && o.is_recurring)
        if (recommended) monthlyInvestment = recommended.price
        else {
            const recurring = form.pricing_options.find(o => o.is_recurring)
            if (recurring) monthlyInvestment = recurring.price
        }
        if (!monthlyInvestment) return

        setLoading(true)
        setError(null)
        investmentsApi.calculate({
            business_model: form.business_model || undefined,
            aov: Number(form.aov),
            conversion_rate: Number(form.conversion_rate),
            ltv: Number(form.ltv),
            seo_maturity: form.seo_maturity_level || undefined,
            current_monthly_traffic: Number(form.current_monthly_traffic),
            monthly_investment: monthlyInvestment,
        }).then(setResult).catch(err => {
            setError(getErrorMessage(err))
        }).finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    if (!hasRequiredFields) {
        return (
            <div className="text-center py-8">
                <Calculator className="w-8 h-8 text-muted-foreground/30 mx-auto mb-3" />
                <p className="text-sm text-muted-foreground">Completa los datos de Revenue (paso 2) y Pricing (paso 4) para ver la previsualización.</p>
            </div>
        )
    }

    if (loading) {
        return <p className="text-sm text-muted-foreground text-center py-8">Calculando modelo de inversión...</p>
    }

    if (error) {
        return <p className="text-sm text-destructive text-center py-8">{error}</p>
    }

    if (!result) return null

    return (
        <div className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
                {result.scenarios.map(s => (
                    <Card key={s.key}>
                        <CardContent className="p-4 text-center">
                            <p className="text-xs font-medium text-muted-foreground mb-1">{s.label}</p>
                            <p className="text-xl font-bold">{s.roi_percent}%</p>
                            <p className="text-xs text-muted-foreground">ROI</p>
                            <div className="mt-2 space-y-1 text-xs text-left">
                                <p>Tráfico: <span className="font-medium text-green-400">+{s.traffic_increase.toLocaleString("es-ES")}</span></p>
                                <p>Ingresos: <span className="font-medium">{s.revenue_increase.toLocaleString("es-ES")}€</span></p>
                                {s.payback_months && <p>Payback: <span className="font-medium">mes {s.payback_months}</span></p>}
                            </div>
                        </CardContent>
                    </Card>
                ))}
            </div>
            <div className="bg-secondary/30 rounded-lg p-3 text-sm text-center">
                <p>Break-even: <strong>mes {result.summary.break_even_month ?? "N/A"}</strong> | ROI año 1: <strong>{result.summary.year1_roi_range}</strong> | Ingresos: <strong>{result.summary.year1_revenue_range}</strong></p>
            </div>
        </div>
    )
}

export default function ProposalsPage() {
    const queryClient = useQueryClient()
    const location = useLocation()
    const [view, setView] = useState<View>("list")
    const [selectedId, setSelectedId] = useState<number | null>(null)
    const [editingId, setEditingId] = useState<number | null>(null)
    const [deleteId, setDeleteId] = useState<number | null>(null)
    const [statusFilter, setStatusFilter] = useState<ProposalStatus | "all">("all")
    const [wizardStep, setWizardStep] = useState(0)
    const [form, setForm] = useState<WizardForm>(emptyForm)
    const [wizardOpen, setWizardOpen] = useState(false)
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

    // Email draft modal state
    const [emailModal, setEmailModal] = useState<number | null>(null)
    const [aiDraft, setAiDraft] = useState<{ subject: string; body: string } | null>(null)
    const [aiDraftLoading, setAiDraftLoading] = useState(false)

    // Auto-open wizard when navigating from lead detail
    useEffect(() => {
        const state = location.state as { createFromLead?: { id: number; company_name: string; contact_name?: string; service_interest?: string; estimated_value?: number } } | null
        if (state?.createFromLead) {
            const lead = state.createFromLead
            setForm({
                ...emptyForm,
                lead_id: lead.id,
                company_name: lead.company_name,
                contact_name: lead.contact_name || "",
                service_type: (lead.service_interest as ServiceType) || null,
            })
            setEditingId(null)
            setWizardStep(0)
            setWizardOpen(true)
            // Clear state so it doesn't re-trigger
            window.history.replaceState({}, document.title)
        }
    }, [location.state])

    // --- Queries ---
    const { data: proposals = [] } = useQuery({
        queryKey: ["proposals", statusFilter],
        queryFn: () => proposalsApi.list(statusFilter !== "all" ? { status: statusFilter } : {}),
    })

    const { data: templates = [] } = useQuery({
        queryKey: ["service-templates"],
        queryFn: () => serviceTemplatesApi.list(),
    })

    const { data: leads = [] } = useQuery({
        queryKey: ["leads-for-proposals"],
        queryFn: () => leadsApi.list(),
    })

    const { data: clients = [] } = useQuery({
        queryKey: ["clients-all-active"],
        queryFn: () => clientsApi.listAll("active"),
    })

    const selectedProposal = useMemo(() => {
        if (!selectedId) return null
        return proposals.find((p) => p.id === selectedId) || null
    }, [proposals, selectedId])

    // --- Mutations ---
    const createMutation = useMutation({
        mutationFn: (data: ProposalCreate) => proposalsApi.create(data),
        onSuccess: (newProp) => {
            queryClient.invalidateQueries({ queryKey: ["proposals"] })
            setWizardOpen(false)
            setWizardStep(0)
            setSelectedId(newProp.id)
            setView("detail")
            toast.success("Propuesta creada")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al crear")),
    })

    const updateMutation = useMutation({
        mutationFn: ({ id, data }: { id: number; data: ProposalUpdate }) => proposalsApi.update(id, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["proposals"] })
            setWizardOpen(false)
            setWizardStep(0)
            toast.success("Propuesta actualizada")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar")),
    })

    const deleteMutation = useMutation({
        mutationFn: (id: number) => proposalsApi.delete(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["proposals"] })
            setDeleteId(null)
            if (view === "detail") { setView("list"); setSelectedId(null) }
            toast.success("Propuesta eliminada")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar")),
    })

    const statusMutation = useMutation({
        mutationFn: ({ id, data }: { id: number; data: ProposalStatusUpdate }) => proposalsApi.changeStatus(id, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["proposals"] })
            toast.success("Estado actualizado")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al cambiar estado")),
    })

    const duplicateMutation = useMutation({
        mutationFn: (id: number) => proposalsApi.duplicate(id),
        onSuccess: (dup) => {
            queryClient.invalidateQueries({ queryKey: ["proposals"] })
            setSelectedId(dup.id)
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

    // --- Email modal helpers ---
    const openEmailModal = async (id: number) => {
        setEmailModal(id)
        setAiDraft(null)
        setAiDraftLoading(true)
        try {
            const draft = await proposalsApi.draftEmail(id)
            setAiDraft({ subject: draft.subject, body: draft.body })
        } catch {
            // Fallback: generate locally
            const p = proposals.find(pr => pr.id === id)
            if (p) setAiDraft(generateEmailDraft(p))
        } finally {
            setAiDraftLoading(false)
        }
    }

    // --- Wizard helpers ---
    const openCreate = () => {
        setForm(emptyForm)
        setEditingId(null)
        setWizardStep(0)
        setWizardOpen(true)
    }

    const openEdit = (p: Proposal) => {
        // Auto-fill revenue fields from client if available
        const clientData = p.client_id ? clients.find(c => c.id === p.client_id) : null
        setForm({
            title: p.title,
            lead_id: p.lead_id,
            client_id: p.client_id,
            contact_name: p.contact_name || "",
            company_name: p.company_name || "",
            service_type: p.service_type,
            business_model: clientData?.business_model || "",
            aov: clientData?.aov?.toString() || "",
            conversion_rate: clientData?.conversion_rate?.toString() || "",
            ltv: clientData?.ltv?.toString() || "",
            seo_maturity_level: clientData?.seo_maturity_level || "",
            current_monthly_traffic: "",
            save_to_client: false,
            situation: p.situation || "",
            problem: p.problem || "",
            cost_of_inaction: p.cost_of_inaction || "",
            opportunity: p.opportunity || "",
            approach: p.approach || "",
            relevant_cases: p.relevant_cases || "",
            pricing_options: p.pricing_options || [],
            internal_hours_david: p.internal_hours_david,
            internal_hours_nacho: p.internal_hours_nacho,
            valid_until: p.valid_until ? p.valid_until.split("T")[0] : "",
        })
        setEditingId(p.id)
        setWizardStep(0)
        setWizardOpen(true)
    }

    const applyTemplate = (serviceType: string) => {
        const tmpl = templates.find((t) => t.service_type === serviceType)
        if (!tmpl) return
        setForm((prev) => ({
            ...prev,
            service_type: tmpl.service_type as ServiceType,
            title: prev.title || tmpl.name,
            approach: prev.approach || tmpl.default_includes || "",
        }))
        toast.success(`Template "${tmpl.name}" aplicado`)
    }

    const applyLead = (leadId: number) => {
        const lead = leads.find((l) => l.id === leadId)
        if (!lead) return
        setForm((prev) => ({
            ...prev,
            lead_id: lead.id,
            company_name: lead.company_name,
            contact_name: lead.contact_name || "",
            service_type: (lead.service_interest as ServiceType) || prev.service_type,
        }))
    }

    // Auto-calculate internal cost
    const computedCost = useMemo(() => {
        const hDavid = form.internal_hours_david || 0
        const hNacho = form.internal_hours_nacho || 0
        return hDavid * DAVID_RATE + hNacho * NACHO_RATE
    }, [form.internal_hours_david, form.internal_hours_nacho])

    const totalRevenue = useMemo(() => {
        if (!form.pricing_options.length) return 0
        const rec = form.pricing_options.find((p) => p.recommended)
        return rec ? rec.price : form.pricing_options[0]?.price || 0
    }, [form.pricing_options])

    const computedMargin = useMemo(() => {
        if (!totalRevenue || !computedCost) return 0
        return Math.round(((totalRevenue - computedCost) / totalRevenue) * 100)
    }, [totalRevenue, computedCost])

    const handleSave = async () => {
        if (!form.title || !form.company_name) {
            toast.error("El titulo y la empresa son obligatorios")
            return
        }

        const payload: ProposalCreate = {
            title: form.title,
            lead_id: form.lead_id || undefined,
            client_id: form.client_id || undefined,
            contact_name: form.contact_name || undefined,
            company_name: form.company_name,
            service_type: form.service_type || undefined,
            situation: form.situation || undefined,
            problem: form.problem || undefined,
            cost_of_inaction: form.cost_of_inaction || undefined,
            opportunity: form.opportunity || undefined,
            approach: form.approach || undefined,
            relevant_cases: form.relevant_cases || undefined,
            pricing_options: form.pricing_options.length > 0 ? form.pricing_options : undefined,
            internal_hours_david: form.internal_hours_david,
            internal_hours_nacho: form.internal_hours_nacho,
            internal_cost_estimate: computedCost || undefined,
            estimated_margin_percent: computedMargin || undefined,
            valid_until: form.valid_until ? new Date(form.valid_until).toISOString() : undefined,
        }

        // Save revenue fields to client if checkbox is checked
        if (form.save_to_client && form.client_id) {
            try {
                await clientsApi.update(form.client_id, {
                    business_model: form.business_model || null,
                    aov: form.aov ? Number(form.aov) : null,
                    conversion_rate: form.conversion_rate ? Number(form.conversion_rate) : null,
                    ltv: form.ltv ? Number(form.ltv) : null,
                    seo_maturity_level: form.seo_maturity_level || null,
                })
            } catch {
                // Non-blocking — proposal save still proceeds
            }
        }

        if (editingId) {
            updateMutation.mutate({ id: editingId, data: payload })
        } else {
            createMutation.mutate(payload)
        }
    }

    const openPdf = async (id: number, e?: React.MouseEvent) => {
        e?.stopPropagation()
        try {
            const blob = await proposalsApi.pdf(id)
            const url = URL.createObjectURL(blob)
            window.open(url, "_blank")
            setTimeout(() => URL.revokeObjectURL(url), 60000)
        } catch (err) {
            toast.error(getErrorMessage(err, "Error al abrir el PDF"))
        }
    }

    // --- Pricing helpers ---
    const addPricingOption = () => {
        setForm((prev) => ({
            ...prev,
            pricing_options: [...prev.pricing_options, { ...emptyPricing }],
        }))
    }

    const updatePricing = (idx: number, field: keyof PricingOption, value: unknown) => {
        setForm((prev) => {
            const opts = [...prev.pricing_options]
            opts[idx] = { ...opts[idx], [field]: value }
            if (field === "recommended" && value) {
                opts.forEach((o, i) => { if (i !== idx) o.recommended = false })
            }
            return { ...prev, pricing_options: opts }
        })
    }

    const removePricing = (idx: number) => {
        setForm((prev) => ({
            ...prev,
            pricing_options: prev.pricing_options.filter((_, i) => i !== idx),
        }))
    }

    // ============================================================
    // DETAIL VIEW
    // ============================================================
    if (view === "detail" && selectedProposal) {
        const p = selectedProposal
        const sc = statusConfig[p.status]
        return (
            <div className="space-y-6">
                <div className="flex items-center gap-3">
                    <Button variant="ghost" size="sm" onClick={() => { setView("list"); setSelectedId(null) }}>
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
                                <Button size="sm" variant="outline" onClick={() => openEdit(p)}>Editar</Button>
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
                            <Button size="sm" variant="ghost" onClick={() => setDeleteId(p.id)}>
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
                                            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">Situacion</p>
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
                                                    <span className="text-sm font-normal text-muted-foreground"> {opt.is_recurring ? "€/mes" : "€"}</span>
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
                                        {/* Executive Summary - highlighted callout */}
                                        {isNonEmptyString(gc.executive_summary) && (
                                            <div className="bg-blue-500/5 border border-blue-500/20 rounded-lg p-4">
                                                <p className="text-xs font-medium text-blue-400 uppercase tracking-wide mb-2">Resumen ejecutivo</p>
                                                <p className="text-sm font-medium">{gc.executive_summary}</p>
                                            </div>
                                        )}

                                        {/* Null Case - warning style */}
                                        {isNonEmptyString(gc.null_case) && (
                                            <div className="bg-orange-500/5 border-l-2 border-orange-500 rounded-r-lg p-4">
                                                <p className="text-xs font-medium text-orange-400 uppercase tracking-wide mb-2">Escenario sin acción</p>
                                                <p className="text-sm">{gc.null_case}</p>
                                            </div>
                                        )}

                                        {/* Success Metrics - table */}
                                        {Array.isArray(gc.success_metrics) && gc.success_metrics.length > 0 && (
                                            <div>
                                                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">Métricas de éxito</p>
                                                <div className="border border-border rounded-lg overflow-hidden">
                                                    <table className="w-full text-sm">
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

                                        {/* Phases - cards */}
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

                                        {/* Remaining text fields */}
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
                                        <span className="font-medium">{p.internal_hours_david ?? "—"}</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span className="text-muted-foreground">Nacho (horas)</span>
                                        <span className="font-medium">{p.internal_hours_nacho ?? "—"}</span>
                                    </div>
                                    <div className="flex justify-between border-t border-border pt-2">
                                        <span className="text-muted-foreground">Coste estimado</span>
                                        <span className="font-medium">
                                            {p.internal_cost_estimate ? `${p.internal_cost_estimate.toLocaleString("es-ES")} €` : "—"}
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
                                            {p.estimated_margin_percent ? `${p.estimated_margin_percent}%` : "—"}
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
            </div>
        )
    }

    // ============================================================
    // LIST VIEW
    // ============================================================
    return (
        <div className="space-y-6">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                    <h1 className="text-2xl font-bold tracking-tight">Propuestas</h1>
                    <p className="text-muted-foreground mt-1">
                        {proposals.length} propuestas · Crea y gestiona propuestas comerciales con IA.
                    </p>
                </div>
                <Button onClick={openCreate} className="w-full sm:w-auto">
                    <Plus className="w-4 h-4 mr-2" /> Nueva Propuesta
                </Button>
            </div>

            {/* Status filter pills */}
            <div className="flex flex-wrap gap-2">
                {([
                    { key: "all" as const, label: "Todas" },
                    { key: "draft" as const, label: "Borradores" },
                    { key: "sent" as const, label: "Enviadas" },
                    { key: "accepted" as const, label: "Aceptadas" },
                    { key: "rejected" as const, label: "Rechazadas" },
                ]).map((f) => (
                    <button
                        key={f.key}
                        onClick={() => setStatusFilter(f.key)}
                        className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
                            statusFilter === f.key
                                ? "bg-brand text-white"
                                : "bg-secondary text-secondary-foreground hover:bg-secondary/80"
                        }`}
                    >
                        {f.label}
                    </button>
                ))}
            </div>

            <Card>
                <CardContent className="p-0">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Propuesta</TableHead>
                                <TableHead>Empresa</TableHead>
                                <TableHead>Servicio</TableHead>
                                <TableHead>Estado</TableHead>
                                <TableHead>Precio</TableHead>
                                <TableHead>Fecha</TableHead>
                                <TableHead className="text-right">Acciones</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {proposals.length === 0 ? (
                                <TableRow className="hover:bg-transparent">
                                    <TableCell colSpan={7} className="py-12">
                                        <div className="flex flex-col items-center">
                                            <FileText className="h-8 w-8 text-muted-foreground/30 mb-3" />
                                            <p className="text-sm font-medium text-foreground mb-1">Sin propuestas</p>
                                            <p className="text-xs text-muted-foreground">
                                                {statusFilter !== "all" ? `No hay propuestas con estado "${statusConfig[statusFilter].label}".` : "Crea propuestas con pricing y genera contenido con IA."}
                                            </p>
                                        </div>
                                    </TableCell>
                                </TableRow>
                            ) : (
                                proposals.map((p) => {
                                    const sc = statusConfig[p.status]
                                    const mainPrice = p.pricing_options?.find((o) => o.recommended)?.price || p.pricing_options?.[0]?.price
                                    return (
                                        <TableRow
                                            key={p.id}
                                            className="cursor-pointer hover:bg-muted/50"
                                            onClick={() => { setSelectedId(p.id); setView("detail") }}
                                        >
                                            <TableCell className="font-medium">{p.title}</TableCell>
                                            <TableCell>
                                                <div className="flex items-center gap-2">
                                                    <Building2 className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                                                    <span className="truncate">{p.company_name || p.client_name || p.lead_company || "—"}</span>
                                                </div>
                                            </TableCell>
                                            <TableCell>
                                                {p.service_type ? (
                                                    <span className="text-xs">{serviceTypeLabels[p.service_type] || p.service_type}</span>
                                                ) : "—"}
                                            </TableCell>
                                            <TableCell>
                                                <Badge variant={sc.variant}>{sc.label}</Badge>
                                            </TableCell>
                                            <TableCell>
                                                {mainPrice ? (
                                                    <span className="font-medium">{mainPrice.toLocaleString("es-ES")} €</span>
                                                ) : "—"}
                                            </TableCell>
                                            <TableCell className="text-muted-foreground text-sm">
                                                {format(new Date(p.created_at), "dd/MM/yyyy")}
                                            </TableCell>
                                            <TableCell className="text-right">
                                                <div className="flex justify-end gap-1">
                                                    <Button variant="ghost" size="sm" onClick={(e) => openPdf(p.id, e)} title="PDF">
                                                        <Download className="w-4 h-4 text-brand" />
                                                    </Button>
                                                    <Button variant="ghost" size="icon" onClick={(e) => { e.stopPropagation(); openEmailModal(p.id) }} title="Enviar por email">
                                                        <Mail className="h-4 w-4" />
                                                    </Button>
                                                    {p.status === "draft" && (
                                                        <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); setDeleteId(p.id) }}>
                                                            <Trash2 className="w-4 h-4 text-destructive" />
                                                        </Button>
                                                    )}
                                                </div>
                                            </TableCell>
                                        </TableRow>
                                    )
                                })
                            )}
                        </TableBody>
                    </Table>
                </CardContent>
            </Card>

            {/* ========== WIZARD DIALOG ========== */}
            {wizardOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center">
                    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setWizardOpen(false)} />
                    <div className="relative z-50 w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-[16px] border border-border bg-card p-6 shadow-2xl">
                        <button
                            onClick={() => setWizardOpen(false)}
                            className="absolute right-4 top-4 text-muted-foreground hover:text-foreground transition-colors"
                        >
                            <XCircle className="h-5 w-5" />
                        </button>

                        {/* Wizard header */}
                        <div className="mb-6">
                            <h2 className="text-lg font-semibold">{editingId ? "Editar Propuesta" : "Nueva Propuesta"}</h2>
                            <div className="flex items-center gap-2 mt-4">
                                {["Datos basicos", "Revenue", "Contexto", "Pricing", "ROI Preview", "Interno"].map((stepName, i) => (
                                    <div key={i} className="flex items-center gap-2">
                                        <button
                                            onClick={() => setWizardStep(i)}
                                            className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                                                wizardStep === i
                                                    ? "bg-brand text-white"
                                                    : wizardStep > i
                                                        ? "bg-green-500/10 text-green-400"
                                                        : "bg-secondary text-muted-foreground"
                                            }`}
                                        >
                                            <span>{i + 1}</span>
                                            <span className="hidden sm:inline">{stepName}</span>
                                        </button>
                                        {i < 5 && <ChevronRight className="w-3 h-3 text-muted-foreground" />}
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Step 0: Basic data */}
                        {wizardStep === 0 && (
                            <div className="space-y-4">
                                <div className="grid grid-cols-2 gap-4">
                                    <div className="space-y-2">
                                        <Label>Lead (opcional)</Label>
                                        <Select value={form.lead_id?.toString() || ""} onChange={(e) => {
                                            const v = e.target.value ? Number(e.target.value) : null
                                            setForm((prev) => ({ ...prev, lead_id: v }))
                                            if (v) applyLead(v)
                                        }}>
                                            <option value="">Sin lead</option>
                                            {leads.map((l) => (
                                                <option key={l.id} value={l.id}>{l.company_name}</option>
                                            ))}
                                        </Select>
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Cliente existente (opcional)</Label>
                                        <Select value={form.client_id?.toString() || ""} onChange={(e) => {
                                            const v = e.target.value ? Number(e.target.value) : null
                                            setForm((prev) => ({ ...prev, client_id: v }))
                                            if (v) {
                                                const client = clients.find((c) => c.id === v)
                                                if (client) setForm((prev) => ({
                                                    ...prev,
                                                    company_name: prev.company_name || client.name,
                                                    business_model: client.business_model || prev.business_model,
                                                    aov: client.aov?.toString() || prev.aov,
                                                    conversion_rate: client.conversion_rate?.toString() || prev.conversion_rate,
                                                    ltv: client.ltv?.toString() || prev.ltv,
                                                    seo_maturity_level: client.seo_maturity_level || prev.seo_maturity_level,
                                                }))
                                            }
                                        }}>
                                            <option value="">Sin cliente</option>
                                            {clients.map((c) => (
                                                <option key={c.id} value={c.id}>{c.name}</option>
                                            ))}
                                        </Select>
                                    </div>
                                </div>

                                <div className="space-y-2">
                                    <Label>Titulo *</Label>
                                    <Input
                                        value={form.title}
                                        onChange={(e) => setForm((prev) => ({ ...prev, title: e.target.value }))}
                                        placeholder="Ej. Propuesta SEO Sprint — Empresa X"
                                    />
                                </div>

                                <div className="grid grid-cols-2 gap-4">
                                    <div className="space-y-2">
                                        <Label>Empresa *</Label>
                                        <Input
                                            value={form.company_name}
                                            onChange={(e) => setForm((prev) => ({ ...prev, company_name: e.target.value }))}
                                            placeholder="Nombre de la empresa"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Contacto</Label>
                                        <Input
                                            value={form.contact_name}
                                            onChange={(e) => setForm((prev) => ({ ...prev, contact_name: e.target.value }))}
                                            placeholder="Nombre del contacto"
                                        />
                                    </div>
                                </div>

                                <div className="grid grid-cols-2 gap-4">
                                    <div className="space-y-2">
                                        <Label>Tipo de servicio</Label>
                                        <Select value={form.service_type || ""} onChange={(e) => {
                                            const st = (e.target.value as ServiceType) || null
                                            setForm((prev) => ({ ...prev, service_type: st }))
                                            if (st && st !== "custom") applyTemplate(st)
                                        }}>
                                            <option value="">Seleccionar...</option>
                                            {Object.entries(serviceTypeLabels).map(([k, v]) => (
                                                <option key={k} value={k}>{v}</option>
                                            ))}
                                        </Select>
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Valida hasta</Label>
                                        <Input
                                            type="date"
                                            value={form.valid_until}
                                            onChange={(e) => setForm((prev) => ({ ...prev, valid_until: e.target.value }))}
                                        />
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Step 1: Revenue */}
                        {wizardStep === 1 && (
                            <div className="space-y-4">
                                <p className="text-sm text-muted-foreground">
                                    Datos de negocio del cliente para calcular ROI. Se auto-rellenan si hay datos guardados en el cliente.
                                </p>
                                <div className="grid grid-cols-2 gap-4">
                                    <div className="space-y-2">
                                        <Label>Modelo de negocio</Label>
                                        <Select value={form.business_model} onChange={e => setForm(f => ({ ...f, business_model: e.target.value }))}>
                                            <option value="">Seleccionar...</option>
                                            <option value="ecommerce">E-commerce</option>
                                            <option value="saas">SaaS</option>
                                            <option value="lead_gen">Lead Generation</option>
                                            <option value="media">Media / Publisher</option>
                                        </Select>
                                    </div>
                                    <div className="space-y-2">
                                        <Label>AOV (€)</Label>
                                        <Input type="number" value={form.aov} onChange={e => setForm(f => ({ ...f, aov: e.target.value }))} placeholder="100" />
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Tasa de conversión (%)</Label>
                                        <Input type="number" step="0.1" value={form.conversion_rate} onChange={e => setForm(f => ({ ...f, conversion_rate: e.target.value }))} placeholder="2.5" />
                                    </div>
                                    <div className="space-y-2">
                                        <Label>LTV (€)</Label>
                                        <Input type="number" value={form.ltv} onChange={e => setForm(f => ({ ...f, ltv: e.target.value }))} placeholder="200" />
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Madurez SEO</Label>
                                        <Select value={form.seo_maturity_level} onChange={e => setForm(f => ({ ...f, seo_maturity_level: e.target.value }))}>
                                            <option value="">Seleccionar...</option>
                                            <option value="none">Sin SEO</option>
                                            <option value="basic">Básico</option>
                                            <option value="intermediate">Intermedio</option>
                                            <option value="advanced">Avanzado</option>
                                        </Select>
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Tráfico mensual actual</Label>
                                        <Input type="number" value={form.current_monthly_traffic} onChange={e => setForm(f => ({ ...f, current_monthly_traffic: e.target.value }))} placeholder="5000" />
                                    </div>
                                </div>
                                {form.client_id && (
                                    <label className="flex items-center gap-2 text-sm">
                                        <input type="checkbox" checked={form.save_to_client} onChange={e => setForm(f => ({ ...f, save_to_client: e.target.checked }))} className="rounded" />
                                        Guardar estos datos en el cliente
                                    </label>
                                )}
                            </div>
                        )}

                        {/* Step 2: Context */}
                        {wizardStep === 2 && (
                            <div className="space-y-4">
                                <p className="text-sm text-muted-foreground">
                                    Estos campos alimentan la generacion IA de la propuesta. Cuanto mas contexto, mejor resultado.
                                </p>
                                <div className="space-y-2">
                                    <Label>Situacion actual del cliente</Label>
                                    <Textarea
                                        value={form.situation}
                                        onChange={(e) => setForm((prev) => ({ ...prev, situation: e.target.value }))}
                                        placeholder="¿Cómo está el cliente ahora? ¿Qué tiene implementado?"
                                        className="min-h-[80px]"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label>Problema que resolvemos</Label>
                                    <Textarea
                                        value={form.problem}
                                        onChange={(e) => setForm((prev) => ({ ...prev, problem: e.target.value }))}
                                        placeholder="¿Qué problema tiene? ¿Qué no está funcionando?"
                                        className="min-h-[80px]"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label>Coste de no actuar</Label>
                                    <Textarea
                                        value={form.cost_of_inaction}
                                        onChange={(e) => setForm((prev) => ({ ...prev, cost_of_inaction: e.target.value }))}
                                        placeholder="¿Qué pasa si el cliente no hace nada?"
                                        className="min-h-[60px]"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label>Oportunidad</Label>
                                    <Textarea
                                        value={form.opportunity}
                                        onChange={(e) => setForm((prev) => ({ ...prev, opportunity: e.target.value }))}
                                        placeholder="¿Que puede ganar? Datos de mercado, competidores..."
                                        className="min-h-[60px]"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label>Enfoque / Que incluye</Label>
                                    <Textarea
                                        value={form.approach}
                                        onChange={(e) => setForm((prev) => ({ ...prev, approach: e.target.value }))}
                                        placeholder="Describe el enfoque del servicio..."
                                        className="min-h-[80px]"
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label>Casos relevantes</Label>
                                    <Textarea
                                        value={form.relevant_cases}
                                        onChange={(e) => setForm((prev) => ({ ...prev, relevant_cases: e.target.value }))}
                                        placeholder="Casos de exito similares que refuercen la propuesta..."
                                        className="min-h-[60px]"
                                    />
                                </div>
                            </div>
                        )}

                        {/* Step 3: Pricing */}
                        {wizardStep === 3 && (
                            <div className="space-y-4">
                                <div className="flex justify-between items-center">
                                    <p className="text-sm text-muted-foreground">Define las opciones de precio. Marca una como recomendada.</p>
                                    <Button size="sm" variant="outline" onClick={addPricingOption}>
                                        <Plus className="w-4 h-4 mr-1" /> Opción
                                    </Button>
                                </div>

                                {form.pricing_options.length === 0 && (
                                    <div className="text-center py-8 text-muted-foreground">
                                        <Euro className="w-8 h-8 mx-auto mb-3 opacity-20" />
                                        <p>No hay opciones de precio. Añade al menos una.</p>
                                    </div>
                                )}

                                {form.pricing_options.map((opt, i) => (
                                    <div key={i} className={`rounded-lg border p-4 space-y-3 ${opt.recommended ? "border-brand bg-brand/5" : "border-border"}`}>
                                        <div className="flex justify-between items-start">
                                            <div className="flex items-center gap-3">
                                                <span className="text-sm font-medium">Opción {i + 1}</span>
                                                <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                                                    <input
                                                        type="checkbox"
                                                        checked={opt.recommended}
                                                        onChange={(e) => updatePricing(i, "recommended", e.target.checked)}
                                                        className="rounded"
                                                    />
                                                    Recomendada
                                                </label>
                                                <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                                                    <input
                                                        type="checkbox"
                                                        checked={opt.is_recurring}
                                                        onChange={(e) => updatePricing(i, "is_recurring", e.target.checked)}
                                                        className="rounded"
                                                    />
                                                    Recurrente
                                                </label>
                                            </div>
                                            <Button variant="ghost" size="sm" onClick={() => removePricing(i)}>
                                                <Trash2 className="w-3.5 h-3.5 text-destructive" />
                                            </Button>
                                        </div>
                                        <div className="grid grid-cols-2 gap-3">
                                            <div className="space-y-1">
                                                <Label className="text-xs">Nombre</Label>
                                                <Input
                                                    value={opt.name}
                                                    onChange={(e) => updatePricing(i, "name", e.target.value)}
                                                    placeholder="Ej. Plan Basico"
                                                />
                                            </div>
                                            <div className="space-y-1">
                                                <Label className="text-xs">Precio (€)</Label>
                                                <Input
                                                    type="number"
                                                    value={opt.price || ""}
                                                    onChange={(e) => updatePricing(i, "price", Number(e.target.value))}
                                                    placeholder="0"
                                                />
                                            </div>
                                        </div>
                                        <div className="space-y-1">
                                            <Label className="text-xs">Descripción</Label>
                                            <Input
                                                value={opt.description}
                                                onChange={(e) => updatePricing(i, "description", e.target.value)}
                                                placeholder="¿Qué incluye esta opción?"
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <Label className="text-xs">Ideal para</Label>
                                            <Input
                                                value={opt.ideal_for || ""}
                                                onChange={(e) => updatePricing(i, "ideal_for", e.target.value)}
                                                placeholder="Ej. Empresas que..."
                                            />
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* Step 4: ROI Preview */}
                        {wizardStep === 4 && (
                            <div className="space-y-4">
                                <p className="text-sm text-muted-foreground">
                                    Vista previa del modelo de inversión calculado con los datos de Revenue (paso 2) y Pricing (paso 4).
                                </p>
                                <RoiPreviewStep form={form} />
                            </div>
                        )}

                        {/* Step 5: Internal */}
                        {wizardStep === 5 && (
                            <div className="space-y-4">
                                <p className="text-sm text-muted-foreground">
                                    Estimaciones internas de horas y coste. Esto NO aparece en la propuesta al cliente.
                                </p>

                                <div className="grid grid-cols-2 gap-4">
                                    <div className="space-y-2">
                                        <Label>Horas David (€50/h)</Label>
                                        <Input
                                            type="number"
                                            value={form.internal_hours_david ?? ""}
                                            onChange={(e) => setForm((prev) => ({
                                                ...prev,
                                                internal_hours_david: e.target.value ? Number(e.target.value) : null,
                                            }))}
                                            placeholder="0"
                                        />
                                    </div>
                                    <div className="space-y-2">
                                        <Label>Horas Nacho (€30/h)</Label>
                                        <Input
                                            type="number"
                                            value={form.internal_hours_nacho ?? ""}
                                            onChange={(e) => setForm((prev) => ({
                                                ...prev,
                                                internal_hours_nacho: e.target.value ? Number(e.target.value) : null,
                                            }))}
                                            placeholder="0"
                                        />
                                    </div>
                                </div>

                                <Card>
                                    <CardContent className="p-4">
                                        <h4 className="font-semibold mb-3">Resumen financiero</h4>
                                        <div className="space-y-2 text-sm">
                                            <div className="flex justify-between">
                                                <span className="text-muted-foreground">Coste David</span>
                                                <span>{((form.internal_hours_david || 0) * DAVID_RATE).toLocaleString("es-ES")} €</span>
                                            </div>
                                            <div className="flex justify-between">
                                                <span className="text-muted-foreground">Coste Nacho</span>
                                                <span>{((form.internal_hours_nacho || 0) * NACHO_RATE).toLocaleString("es-ES")} €</span>
                                            </div>
                                            <div className="flex justify-between border-t border-border pt-2 font-medium">
                                                <span>Coste total estimado</span>
                                                <span>{computedCost.toLocaleString("es-ES")} €</span>
                                            </div>
                                            <div className="flex justify-between">
                                                <span className="text-muted-foreground">Precio al cliente (recomendado)</span>
                                                <span>{totalRevenue ? `${totalRevenue.toLocaleString("es-ES")} €` : "—"}</span>
                                            </div>
                                            <div className="flex justify-between font-medium">
                                                <span>Margen estimado</span>
                                                <span className={
                                                    computedMargin >= 50
                                                        ? "text-green-400"
                                                        : computedMargin >= 30
                                                            ? "text-yellow-400"
                                                            : "text-red-400"
                                                }>
                                                    {computedMargin}%
                                                    {computedMargin > 0 && computedMargin < 30 && (
                                                        <AlertTriangle className="inline w-3.5 h-3.5 ml-1" />
                                                    )}
                                                </span>
                                            </div>
                                        </div>
                                    </CardContent>
                                </Card>
                            </div>
                        )}

                        {/* Navigation */}
                        <div className="flex justify-between mt-6 pt-4 border-t border-border">
                            <Button
                                variant="outline"
                                onClick={() => wizardStep > 0 ? setWizardStep(wizardStep - 1) : setWizardOpen(false)}
                            >
                                {wizardStep > 0 ? (
                                    <><ChevronLeft className="w-4 h-4 mr-1" /> Anterior</>
                                ) : "Cancelar"}
                            </Button>
                            {wizardStep < 5 ? (
                                <Button onClick={() => setWizardStep(wizardStep + 1)}>
                                    Siguiente <ChevronRight className="w-4 h-4 ml-1" />
                                </Button>
                            ) : (
                                <Button
                                    onClick={handleSave}
                                    disabled={createMutation.isPending || updateMutation.isPending}
                                >
                                    {editingId ? "Guardar cambios" : "Crear propuesta"}
                                </Button>
                            )}
                        </div>
                    </div>
                </div>
            )}

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
                                    <Label>AOV (€)</Label>
                                    <Input type="number" value={roiForm.aov} onChange={e => setRoiForm(f => ({ ...f, aov: e.target.value }))} placeholder="100" />
                                </div>
                                <div>
                                    <Label>Conversión (%)</Label>
                                    <Input type="number" step="0.1" value={roiForm.conversion_rate} onChange={e => setRoiForm(f => ({ ...f, conversion_rate: e.target.value }))} placeholder="2.5" />
                                </div>
                                <div>
                                    <Label>LTV (€)</Label>
                                    <Input type="number" value={roiForm.ltv} onChange={e => setRoiForm(f => ({ ...f, ltv: e.target.value }))} placeholder="200" />
                                </div>
                                <div>
                                    <Label>Tráfico mensual actual</Label>
                                    <Input type="number" value={roiForm.current_monthly_traffic} onChange={e => setRoiForm(f => ({ ...f, current_monthly_traffic: e.target.value }))} placeholder="5000" />
                                </div>
                                <div>
                                    <Label>Inversión mensual (€)</Label>
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
                                    // Auto-fill from proposal client
                                    if (selectedProposal?.client_id) {
                                        const clientData = clients.find(c => c.id === selectedProposal.client_id)
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
                                            client_id: selectedProposal?.client_id,
                                            proposal_id: selectedProposal?.id,
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
                            {/* Summary */}
                            <div className="grid grid-cols-3 gap-3">
                                <div className="bg-secondary/30 rounded-lg p-3 text-center">
                                    <p className="text-xs text-muted-foreground">Break-even</p>
                                    <p className="text-lg font-bold">Mes {roiResult.summary.break_even_month ?? "N/A"}</p>
                                </div>
                                <div className="bg-secondary/30 rounded-lg p-3 text-center">
                                    <p className="text-xs text-muted-foreground">ROI Año 1</p>
                                    <p className="text-lg font-bold">{roiResult.summary.year1_roi_range}</p>
                                </div>
                                <div className="bg-secondary/30 rounded-lg p-3 text-center">
                                    <p className="text-xs text-muted-foreground">Ingresos Año 1</p>
                                    <p className="text-lg font-bold text-xs">{roiResult.summary.year1_revenue_range}</p>
                                </div>
                            </div>

                            {/* Scenarios */}
                            <div className="space-y-2">
                                <p className="text-sm font-medium">Escenarios</p>
                                <div className="grid grid-cols-3 gap-2">
                                    {roiResult.scenarios.map(s => (
                                        <div key={s.key} className="border border-border rounded-lg p-3">
                                            <p className="text-xs font-medium mb-2">{s.label}</p>
                                            <div className="space-y-1 text-xs">
                                                <p>Tráfico: <span className="font-medium text-green-400">+{s.traffic_increase.toLocaleString("es-ES")}</span></p>
                                                <p>Conversiones: <span className="font-medium">+{s.new_conversions}</span></p>
                                                <p>Ingresos: <span className="font-medium">{s.revenue_increase.toLocaleString("es-ES")}€</span></p>
                                                <p>ROI: <span className="font-bold">{s.roi_percent}%</span></p>
                                                {s.payback_months && <p>Payback: <span className="font-medium">mes {s.payback_months}</span></p>}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            {/* Monthly projection (collapsed by default) */}
                            <details className="text-sm">
                                <summary className="cursor-pointer font-medium mb-2">Proyección mensual (moderado)</summary>
                                <div className="border border-border rounded-lg overflow-hidden">
                                    <table className="w-full text-xs">
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
                                                    <td className="p-1.5 text-right">{r.revenue.toLocaleString("es-ES")}€</td>
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
                                    if (!selectedProposal) return
                                    try {
                                        const currentContent = selectedProposal.generated_content || {}
                                        await proposalsApi.update(selectedProposal.id, {
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

            {/* ========== EMAIL DRAFT DIALOG ========== */}
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
                            <p className="text-sm">Redactando con IA…</p>
                        </div>
                    ) : aiDraft ? (
                        <div className="space-y-4 p-1">
                            <div>
                                <Label className="text-xs text-muted-foreground">Asunto</Label>
                                <div className="flex items-center gap-2 mt-1">
                                    <Input readOnly value={aiDraft.subject} className="font-medium" />
                                    <Button variant="ghost" size="icon" className="shrink-0" onClick={() => { navigator.clipboard.writeText(aiDraft.subject); toast.success("Asunto copiado") }}>
                                        <Copy className="w-4 h-4" />
                                    </Button>
                                </div>
                            </div>
                            <div>
                                <Label className="text-xs text-muted-foreground">Cuerpo</Label>
                                <div className="relative mt-1">
                                    <Textarea readOnly value={aiDraft.body} rows={10} className="text-xs resize-none" />
                                    <Button variant="ghost" size="icon" className="absolute top-1 right-1" onClick={() => { navigator.clipboard.writeText(aiDraft.body); toast.success("Texto copiado") }}>
                                        <Copy className="w-4 h-4" />
                                    </Button>
                                </div>
                            </div>
                            <p className="text-xs text-muted-foreground">Copia el texto, pégalo en tu cliente de email y adjunta el PDF de la propuesta.</p>
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
