import { useState, useMemo, useEffect } from "react"
import { useQuery } from "@tanstack/react-query"
import { useLocation } from "react-router-dom"
import { format } from "date-fns"
import {
    FileText, Plus, Trash2, Download, Building2, Mail, Copy
} from "lucide-react"
import { proposalsApi, serviceTemplatesApi, leadsApi, clientsApi } from "@/lib/api"
import type {
    Proposal, ProposalStatus, ServiceType,
} from "@/lib/types"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Dialog, DialogHeader, DialogTitle, DialogContent } from "@/components/ui/dialog"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

import { ProposalDetail } from "@/components/proposals/proposal-detail"
import { ProposalWizard, emptyForm } from "@/components/proposals/proposal-wizard"
import type { WizardForm } from "@/components/proposals/proposal-wizard"

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

export default function ProposalsPage() {
    const location = useLocation()
    const [view, setView] = useState<View>("list")
    const [selectedId, setSelectedId] = useState<number | null>(null)
    const [editingId, setEditingId] = useState<number | null>(null)
    const [deleteId, setDeleteId] = useState<number | null>(null)
    const [statusFilter, setStatusFilter] = useState<ProposalStatus | "all">("all")
    const [form, setForm] = useState<WizardForm>(emptyForm)
    const [wizardOpen, setWizardOpen] = useState(false)

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
            setWizardOpen(true)
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

    // --- Wizard helpers ---
    const openCreate = () => {
        setForm(emptyForm)
        setEditingId(null)
        setWizardOpen(true)
    }

    const openEdit = (p: Proposal) => {
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
        setWizardOpen(true)
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

    const openEmailModal = async (id: number) => {
        setEmailModal(id)
        setAiDraft(null)
        setAiDraftLoading(true)
        try {
            const draft = await proposalsApi.draftEmail(id)
            setAiDraft({ subject: draft.subject, body: draft.body })
        } catch (err) {
            console.error(err)
            const p = proposals.find(pr => pr.id === id)
            if (p) {
                const contact = p.contact_name || p.company_name
                const mainPrice = p.pricing_options?.find(o => o.recommended)?.price ?? p.pricing_options?.[0]?.price
                const priceStr = mainPrice ? `${mainPrice.toLocaleString("es-ES")} \u20AC` : null
                const subject = `Propuesta ${p.title} \u2014 ${p.company_name}`
                const body = [
                    `Hola ${contact},`,
                    "",
                    `Te adjunto la propuesta que hemos preparado para ${p.company_name}: "${p.title}".`,
                    "",
                    p.situation ? `Contexto: ${p.situation}` : null,
                    p.opportunity ? `Oportunidad: ${p.opportunity}` : null,
                    priceStr ? `Inversion: ${priceStr}` : null,
                    p.valid_until ? `Valida hasta: ${new Date(p.valid_until).toLocaleDateString("es-ES")}` : null,
                    "",
                    "Quedo a tu disposicion para resolver cualquier duda o concertar una llamada.",
                    "",
                    "Un saludo,",
                ].filter(l => l !== null).join("\n")
                setAiDraft({ subject, body })
            }
        } finally {
            setAiDraftLoading(false)
        }
    }

    // ============================================================
    // DETAIL VIEW
    // ============================================================
    if (view === "detail" && selectedProposal) {
        return (
            <ProposalDetail
                proposal={selectedProposal}
                clients={clients}
                onBack={() => { setView("list"); setSelectedId(null) }}
                onEdit={openEdit}
            />
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
            <div className="flex flex-wrap gap-2" role="group" aria-label="Filtro por estado">
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
                        aria-pressed={statusFilter === f.key}
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
                    <Table aria-label="Lista de propuestas">
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
                                                    <span className="truncate">{p.company_name || p.client_name || p.lead_company || "\u2014"}</span>
                                                </div>
                                            </TableCell>
                                            <TableCell>
                                                {p.service_type ? (
                                                    <span className="text-xs">{serviceTypeLabels[p.service_type] || p.service_type}</span>
                                                ) : "\u2014"}
                                            </TableCell>
                                            <TableCell>
                                                <Badge variant={sc.variant}>{sc.label}</Badge>
                                            </TableCell>
                                            <TableCell>
                                                {mainPrice ? (
                                                    <span className="font-medium">{mainPrice.toLocaleString("es-ES")} \u20AC</span>
                                                ) : "\u2014"}
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

            {/* Wizard */}
            <ProposalWizard
                open={wizardOpen}
                onClose={() => setWizardOpen(false)}
                editingId={editingId}
                form={form}
                setForm={setForm}
                leads={leads}
                clients={clients}
                templates={templates}
                onCreated={(id) => { setSelectedId(id); setView("detail") }}
            />

            <ConfirmDialog
                open={!!deleteId}
                onOpenChange={(open) => !open && setDeleteId(null)}
                title="Eliminar Propuesta"
                description="Solo se pueden eliminar propuestas en borrador. Esta accion no se puede deshacer."
                onConfirm={() => {
                    if (deleteId) {
                        proposalsApi.delete(deleteId).then(() => {
                            setDeleteId(null)
                            if (view === "detail") { setView("list"); setSelectedId(null) }
                            toast.success("Propuesta eliminada")
                        }).catch((err) => toast.error(getErrorMessage(err, "Error al eliminar")))
                    }
                }}
            />

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

