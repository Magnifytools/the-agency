import { useState, useMemo, useEffect } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import {
    Plus, Trash2, XCircle, ChevronRight, ChevronLeft,
    Euro, AlertTriangle, Calculator
} from "lucide-react"
import { proposalsApi, investmentsApi, clientsApi } from "@/lib/api"
import type {
    ProposalCreate, ServiceType, PricingOption,
    InvestmentCalculateResponse, Client, Lead, ServiceTemplate,
} from "@/lib/types"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import { serviceTypeLabels } from "@/lib/constants"

export interface WizardForm {
    title: string
    lead_id: number | null
    client_id: number | null
    contact_name: string
    company_name: string
    service_type: ServiceType | null
    business_model: string
    aov: string
    conversion_rate: string
    ltv: string
    seo_maturity_level: string
    current_monthly_traffic: string
    save_to_client: boolean
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

export const emptyForm: WizardForm = {
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

// TODO: These hourly rates should come from the API (e.g. /api/settings or /api/users/:id/rate)
// instead of being hardcoded. Update when backend supports configurable rates.
const DAVID_RATE = 50
const NACHO_RATE = 30

function RoiPreviewStep({ form }: { form: WizardForm }) {
    const [result, setResult] = useState<InvestmentCalculateResponse | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const hasRequiredFields = form.business_model && form.aov && form.conversion_rate && form.ltv && form.current_monthly_traffic

    useEffect(() => {
        if (!hasRequiredFields) return

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
                                <p>Ingresos: <span className="font-medium">{s.revenue_increase.toLocaleString("es-ES")}\u20AC</span></p>
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

interface ProposalWizardProps {
    open: boolean
    onClose: () => void
    editingId: number | null
    form: WizardForm
    setForm: React.Dispatch<React.SetStateAction<WizardForm>>
    leads: Lead[]
    clients: Client[]
    templates: ServiceTemplate[]
    onCreated?: (id: number) => void
}

export function ProposalWizard({
    open, onClose, editingId, form, setForm,
    leads, clients, templates, onCreated,
}: ProposalWizardProps) {
    const queryClient = useQueryClient()
    const [wizardStep, setWizardStep] = useState(0)

    // Reset step when opened
    useEffect(() => {
        if (open) setWizardStep(0)
    }, [open])

    const createMutation = useMutation({
        mutationFn: (data: ProposalCreate) => proposalsApi.create(data),
        onSuccess: (newProp) => {
            queryClient.invalidateQueries({ queryKey: ["proposals"] })
            onClose()
            onCreated?.(newProp.id)
            toast.success("Propuesta creada")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al crear")),
    })

    const updateMutation = useMutation({
        mutationFn: ({ id, data }: { id: number; data: ProposalCreate }) => proposalsApi.update(id, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["proposals"] })
            onClose()
            toast.success("Propuesta actualizada")
        },
        onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar")),
    })

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

    const handleSave = async () => {
        if (!form.title || !form.company_name) {
            toast.error("El título y la empresa son obligatorios")
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

        if (form.save_to_client && form.client_id) {
            try {
                await clientsApi.update(form.client_id, {
                    business_model: form.business_model || null,
                    aov: form.aov ? Number(form.aov) : null,
                    conversion_rate: form.conversion_rate ? Number(form.conversion_rate) : null,
                    ltv: form.ltv ? Number(form.ltv) : null,
                    seo_maturity_level: form.seo_maturity_level || null,
                })
            } catch (err) {
                console.error(err)
            }
        }

        if (editingId) {
            updateMutation.mutate({ id: editingId, data: payload })
        } else {
            createMutation.mutate(payload)
        }
    }

    if (!open) return null

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
            <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
            <div role="dialog" aria-modal="true" aria-label={editingId ? "Editar Propuesta" : "Nueva Propuesta"} className="relative z-50 w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-[16px] border border-border bg-card p-6 shadow-2xl">
                <button
                    onClick={onClose}
                    className="absolute right-4 top-4 text-muted-foreground hover:text-foreground transition-colors"
                    aria-label="Cerrar"
                >
                    <XCircle className="h-5 w-5" />
                </button>

                {/* Wizard header */}
                <div className="mb-6">
                    <h2 className="text-lg font-semibold">{editingId ? "Editar Propuesta" : "Nueva Propuesta"}</h2>
                    <div className="flex items-center gap-2 mt-4">
                        {["Datos básicos", "Revenue", "Contexto", "Pricing", "ROI Preview", "Interno"].map((stepName, i) => (
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
                            <Label>Título *</Label>
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
                                <Label>AOV (\u20AC)</Label>
                                <Input type="number" value={form.aov} onChange={e => setForm(f => ({ ...f, aov: e.target.value }))} placeholder="100" />
                            </div>
                            <div className="space-y-2">
                                <Label>Tasa de conversión (%)</Label>
                                <Input type="number" step="0.1" value={form.conversion_rate} onChange={e => setForm(f => ({ ...f, conversion_rate: e.target.value }))} placeholder="2.5" />
                            </div>
                            <div className="space-y-2">
                                <Label>LTV (\u20AC)</Label>
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
                            Estos campos alimentan la generación IA de la propuesta. Cuanto más contexto, mejor resultado.
                        </p>
                        <div className="space-y-2">
                            <Label>Situación actual del cliente</Label>
                            <Textarea
                                value={form.situation}
                                onChange={(e) => setForm((prev) => ({ ...prev, situation: e.target.value }))}
                                placeholder="Como esta el cliente ahora? Que tiene implementado?"
                                className="min-h-[80px]"
                            />
                        </div>
                        <div className="space-y-2">
                            <Label>Problema que resolvemos</Label>
                            <Textarea
                                value={form.problem}
                                onChange={(e) => setForm((prev) => ({ ...prev, problem: e.target.value }))}
                                placeholder="Que problema tiene? Que no esta funcionando?"
                                className="min-h-[80px]"
                            />
                        </div>
                        <div className="space-y-2">
                            <Label>Coste de no actuar</Label>
                            <Textarea
                                value={form.cost_of_inaction}
                                onChange={(e) => setForm((prev) => ({ ...prev, cost_of_inaction: e.target.value }))}
                                placeholder="Que pasa si el cliente no hace nada?"
                                className="min-h-[60px]"
                            />
                        </div>
                        <div className="space-y-2">
                            <Label>Oportunidad</Label>
                            <Textarea
                                value={form.opportunity}
                                onChange={(e) => setForm((prev) => ({ ...prev, opportunity: e.target.value }))}
                                placeholder="¿Qué puede ganar? Datos de mercado, competidores..."
                                className="min-h-[60px]"
                            />
                        </div>
                        <div className="space-y-2">
                            <Label>Enfoque / Qué incluye</Label>
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
                                placeholder="Casos de éxito similares que refuercen la propuesta..."
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
                                    <Button variant="ghost" size="sm" aria-label="Eliminar" onClick={() => removePricing(i)}>
                                        <Trash2 className="w-3.5 h-3.5 text-destructive" />
                                    </Button>
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    <div className="space-y-1">
                                        <Label className="text-xs">Nombre</Label>
                                        <Input
                                            value={opt.name}
                                            onChange={(e) => updatePricing(i, "name", e.target.value)}
                                            placeholder="Ej. Plan Básico"
                                        />
                                    </div>
                                    <div className="space-y-1">
                                        <Label className="text-xs">Precio (\u20AC)</Label>
                                        <Input
                                            type="number"
                                            min={0}
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
                                <Label>Horas David (\u20AC50/h)</Label>
                                <Input
                                    type="number"
                                    min={0}
                                    value={form.internal_hours_david ?? ""}
                                    onChange={(e) => setForm((prev) => ({
                                        ...prev,
                                        internal_hours_david: e.target.value ? Number(e.target.value) : null,
                                    }))}
                                    placeholder="0"
                                />
                            </div>
                            <div className="space-y-2">
                                <Label>Horas Nacho (\u20AC30/h)</Label>
                                <Input
                                    type="number"
                                    min={0}
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
                                        <span>{((form.internal_hours_david || 0) * DAVID_RATE).toLocaleString("es-ES")} \u20AC</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span className="text-muted-foreground">Coste Nacho</span>
                                        <span>{((form.internal_hours_nacho || 0) * NACHO_RATE).toLocaleString("es-ES")} \u20AC</span>
                                    </div>
                                    <div className="flex justify-between border-t border-border pt-2 font-medium">
                                        <span>Coste total estimado</span>
                                        <span>{computedCost.toLocaleString("es-ES")} \u20AC</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span className="text-muted-foreground">Precio al cliente (recomendado)</span>
                                        <span>{totalRevenue ? `${totalRevenue.toLocaleString("es-ES")} \u20AC` : "\u2014"}</span>
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
                        onClick={() => wizardStep > 0 ? setWizardStep(wizardStep - 1) : onClose()}
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
    )
}
