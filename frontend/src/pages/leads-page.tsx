import { useState, useRef } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { leadsApi, usersApi } from "@/lib/api"
import { useAuth } from "@/context/auth-context"
import type { Lead, LeadCreate, LeadStatus, LeadSource } from "@/lib/types"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import {
  LayoutGrid, List, Plus, DollarSign, Calendar,
  GripVertical, Trophy, X as XIcon, Target
} from "lucide-react"
import { EmptyTableState } from "@/components/ui/empty-state"
import { toast } from "sonner"
import { useNavigate } from "react-router-dom"

const PIPELINE_STAGES: { key: LeadStatus; label: string; color: string }[] = [
  { key: "new", label: "Nuevo", color: "bg-blue-500" },
  { key: "contacted", label: "Contactado", color: "bg-cyan-500" },
  { key: "discovery", label: "Discovery", color: "bg-violet-500" },
  { key: "proposal", label: "Propuesta", color: "bg-amber-500" },
  { key: "negotiation", label: "Negociacion", color: "bg-orange-500" },
]

const CLOSED_STAGES: { key: LeadStatus; label: string; color: string }[] = [
  { key: "won", label: "Ganado", color: "bg-green-500" },
  { key: "lost", label: "Perdido", color: "bg-red-500" },
]

const SOURCE_LABELS: Record<LeadSource, string> = {
  website: "Web",
  referral: "Referencia",
  linkedin: "LinkedIn",
  conference: "Conferencia",
  cold_outreach: "Cold Outreach",
  other: "Otro",
}

function formatValue(v: number | null, currency = "EUR") {
  if (v == null) return "-"
  return new Intl.NumberFormat("es-ES", { style: "currency", currency }).format(v)
}

function daysInStage(createdAt: string): number {
  return Math.floor((Date.now() - new Date(createdAt).getTime()) / 86400000)
}

export default function LeadsPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const [view, setView] = useState<"kanban" | "table">("kanban")
  const [showCreate, setShowCreate] = useState(false)
  const [showLostDialog, setShowLostDialog] = useState<Lead | null>(null)
  const [showConvertDialog, setShowConvertDialog] = useState<Lead | null>(null)
  const [lostReason, setLostReason] = useState("")
  const [expandWon, setExpandWon] = useState(false)
  const [expandLost, setExpandLost] = useState(false)
  const [filterStatus, setFilterStatus] = useState<string>("")
  const [filterSource, setFilterSource] = useState<string>("")
  const [filterAssigned, setFilterAssigned] = useState<string>("")

  // Drag state
  const dragLeadRef = useRef<Lead | null>(null)

  const { data: leads = [], isLoading } = useQuery({
    queryKey: ["leads", filterStatus, filterSource, filterAssigned],
    queryFn: () => leadsApi.list({
      status: filterStatus || undefined,
      source: filterSource || undefined,
      assigned_to: filterAssigned ? Number(filterAssigned) : undefined,
    }),
  })

  const { data: users = [] } = useQuery({
    queryKey: ["users-all"],
    queryFn: () => usersApi.listAll(),
    enabled: isAdmin,
  })

  const { data: pipelineSummary } = useQuery({
    queryKey: ["pipeline-summary"],
    queryFn: () => leadsApi.pipelineSummary(),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Record<string, unknown> }) => leadsApi.update(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["leads"] })
      qc.invalidateQueries({ queryKey: ["pipeline-summary"] })
    },
  })

  const convertMutation = useMutation({
    mutationFn: (leadId: number) => leadsApi.convert(leadId),
    onSuccess: (data) => {
      toast.success(`Lead convertido a cliente: ${data.client_name}`)
      qc.invalidateQueries({ queryKey: ["leads"] })
      qc.invalidateQueries({ queryKey: ["pipeline-summary"] })
      setShowConvertDialog(null)
    },
    onError: () => toast.error("Error al convertir lead"),
  })

  const handleDrop = (lead: Lead, newStatus: LeadStatus) => {
    if (lead.status === newStatus) return
    if (newStatus === "won") {
      setShowConvertDialog(lead)
      return
    }
    if (newStatus === "lost") {
      setShowLostDialog(lead)
      return
    }
    updateMutation.mutate({ id: lead.id, data: { status: newStatus } })
  }

  const handleLostConfirm = () => {
    if (!showLostDialog) return
    updateMutation.mutate(
      { id: showLostDialog.id, data: { status: "lost", lost_reason: lostReason } },
      { onSuccess: () => { setShowLostDialog(null); setLostReason("") } }
    )
  }

  const leadsForStage = (status: LeadStatus) => leads.filter((l) => l.status === status)
  const stageValue = (status: LeadStatus) => {
    const stage = pipelineSummary?.stages.find((s) => s.status === status)
    return stage ? formatValue(stage.total_value) : "-"
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Pipeline</h2>
          <p className="text-muted-foreground text-sm mt-1">
            {pipelineSummary ? `${pipelineSummary.total_leads} leads · ${formatValue(pipelineSummary.total_value)} pipeline` : "Cargando..."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center bg-muted/30 border border-border rounded-lg p-1">
            <Button variant={view === "kanban" ? "default" : "ghost"} size="sm" onClick={() => setView("kanban")}>
              <LayoutGrid className="h-4 w-4" />
            </Button>
            <Button variant={view === "table" ? "default" : "ghost"} size="sm" onClick={() => setView("table")}>
              <List className="h-4 w-4" />
            </Button>
          </div>
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="h-4 w-4 mr-2" /> Nuevo lead
          </Button>
        </div>
      </div>

      {/* Filters for table view */}
      {view === "table" && (
        <div className="flex gap-3 flex-wrap">
          <Select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className="w-[160px]">
            <option value="">Todos</option>
            {[...PIPELINE_STAGES, ...CLOSED_STAGES].map((s) => (
              <option key={s.key} value={s.key}>{s.label}</option>
            ))}
          </Select>
          <Select value={filterSource} onChange={(e) => setFilterSource(e.target.value)} className="w-[160px]">
            <option value="">Todas</option>
            {Object.entries(SOURCE_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </Select>
          {isAdmin && (
            <Select value={filterAssigned} onChange={(e) => setFilterAssigned(e.target.value)} className="w-[160px]">
              <option value="">Todos</option>
              {users.map((u) => (
                <option key={u.id} value={String(u.id)}>{u.full_name}</option>
              ))}
            </Select>
          )}
        </div>
      )}

      {/* Kanban View */}
      {view === "kanban" && (
        <div className="flex gap-4 overflow-x-auto pb-4">
          {PIPELINE_STAGES.map((stage) => (
            <KanbanColumn
              key={stage.key}
              stage={stage}
              leads={leadsForStage(stage.key)}
              totalValue={stageValue(stage.key)}
              onDrop={(lead) => handleDrop(lead, stage.key)}
              onDragStart={(lead) => { dragLeadRef.current = lead }}
              dragLeadRef={dragLeadRef}
              onClick={(lead) => navigate(`/leads/${lead.id}`)}
            />
          ))}
          {/* Won Column (collapsed by default) */}
          <div className="min-w-[260px] flex-shrink-0">
            <button
              onClick={() => setExpandWon(!expandWon)}
              className="flex items-center gap-2 px-3 py-2 w-full rounded-lg bg-green-500/10 border border-green-500/20 mb-2 hover:bg-green-500/20 transition-colors"
            >
              <Trophy className="h-4 w-4 text-green-500" />
              <span className="text-sm font-semibold text-green-400">Ganados ({leadsForStage("won").length})</span>
            </button>
            {expandWon && leadsForStage("won").map((lead) => (
              <LeadCard key={lead.id} lead={lead} onClick={() => navigate(`/leads/${lead.id}`)} />
            ))}
          </div>
          {/* Lost Column (collapsed by default) */}
          <div className="min-w-[260px] flex-shrink-0">
            <button
              onClick={() => setExpandLost(!expandLost)}
              className="flex items-center gap-2 px-3 py-2 w-full rounded-lg bg-red-500/10 border border-red-500/20 mb-2 hover:bg-red-500/20 transition-colors"
            >
              <XIcon className="h-4 w-4 text-red-500" />
              <span className="text-sm font-semibold text-red-400">Perdidos ({leadsForStage("lost").length})</span>
            </button>
            {expandLost && leadsForStage("lost").map((lead) => (
              <LeadCard key={lead.id} lead={lead} onClick={() => navigate(`/leads/${lead.id}`)} />
            ))}
          </div>
        </div>
      )}

      {/* Table View */}
      {view === "table" && (
        <Card>
          <CardContent className="pt-4">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Empresa</TableHead>
                  <TableHead>Contacto</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Valor</TableHead>
                  <TableHead>Servicio</TableHead>
                  <TableHead>Fuente</TableHead>
                  <TableHead>Followup</TableHead>
                  <TableHead>Asignado</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {leads.map((lead) => (
                  <TableRow
                    key={lead.id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => navigate(`/leads/${lead.id}`)}
                  >
                    <TableCell className="font-medium">{lead.company_name}</TableCell>
                    <TableCell>{lead.contact_name || "-"}</TableCell>
                    <TableCell>
                      <LeadStatusBadge status={lead.status} />
                    </TableCell>
                    <TableCell className="mono">{formatValue(lead.estimated_value, lead.currency)}</TableCell>
                    <TableCell>{lead.service_interest || "-"}</TableCell>
                    <TableCell>{SOURCE_LABELS[lead.source] || lead.source}</TableCell>
                    <TableCell className="mono">
                      {lead.next_followup_date
                        ? new Date(lead.next_followup_date).toLocaleDateString("es-ES")
                        : "-"}
                    </TableCell>
                    <TableCell>{lead.assigned_user_name || "-"}</TableCell>
                  </TableRow>
                ))}
                {!isLoading && leads.length === 0 && (
                  <EmptyTableState colSpan={8} icon={Target} title="Pipeline vacío" description="Añade leads y sigue su progreso por etapas del funnel." />
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Create Lead Dialog */}
      <CreateLeadDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        users={users}
        isAdmin={isAdmin}
      />

      {/* Lost Reason Dialog */}
      <Dialog open={!!showLostDialog} onOpenChange={(o) => { if (!o) { setShowLostDialog(null); setLostReason("") } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Marcar como perdido</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Vas a marcar <strong>{showLostDialog?.company_name}</strong> como perdido.
            </p>
            <div>
              <Label>Razon de perdida</Label>
              <Textarea
                value={lostReason}
                onChange={(e) => setLostReason(e.target.value)}
                placeholder="Presupuesto, timing, competencia..."
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setShowLostDialog(null); setLostReason("") }}>Cancelar</Button>
            <Button variant="destructive" onClick={handleLostConfirm}>Marcar perdido</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Convert Dialog */}
      <Dialog open={!!showConvertDialog} onOpenChange={(o) => { if (!o) setShowConvertDialog(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Convertir a cliente</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Se creara un nuevo cliente con los datos de <strong>{showConvertDialog?.company_name}</strong>.
            </p>
            <div className="bg-muted/50 rounded-lg p-3 text-sm space-y-1">
              <p><span className="text-muted-foreground">Empresa:</span> {showConvertDialog?.company_name}</p>
              <p><span className="text-muted-foreground">Email:</span> {showConvertDialog?.email || "N/A"}</p>
              <p><span className="text-muted-foreground">Valor:</span> {formatValue(showConvertDialog?.estimated_value ?? null, showConvertDialog?.currency)}</p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowConvertDialog(null)}>Cancelar</Button>
            <Button
              onClick={() => showConvertDialog && convertMutation.mutate(showConvertDialog.id)}
              disabled={convertMutation.isPending}
            >
              {convertMutation.isPending ? "Convirtiendo..." : "Convertir a cliente"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// --- Kanban Column ---
function KanbanColumn({
  stage,
  leads,
  totalValue,
  onDrop,
  onDragStart,
  dragLeadRef,
  onClick,
}: {
  stage: { key: LeadStatus; label: string; color: string }
  leads: Lead[]
  totalValue: string
  onDrop: (lead: Lead) => void
  onDragStart: (lead: Lead) => void
  dragLeadRef: React.MutableRefObject<Lead | null>
  onClick: (lead: Lead) => void
}) {
  const [dragOver, setDragOver] = useState(false)

  return (
    <div
      className={`min-w-[260px] max-w-[280px] flex-shrink-0 flex flex-col rounded-xl transition-colors ${dragOver ? "bg-brand/5 ring-2 ring-brand/20" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        if (dragLeadRef.current) onDrop(dragLeadRef.current)
      }}
    >
      <div className="flex items-center justify-between px-3 py-2 mb-2">
        <div className="flex items-center gap-2">
          <div className={`w-2.5 h-2.5 rounded-full ${stage.color}`} />
          <span className="text-sm font-semibold">{stage.label}</span>
          <span className="text-xs text-muted-foreground bg-muted px-1.5 py-0.5 rounded-md">{leads.length}</span>
        </div>
        <span className="text-xs text-muted-foreground mono">{totalValue}</span>
      </div>
      <div className="flex flex-col gap-2 min-h-[100px]">
        {leads.map((lead) => (
          <LeadCard
            key={lead.id}
            lead={lead}
            draggable
            onDragStart={() => onDragStart(lead)}
            onClick={() => onClick(lead)}
          />
        ))}
      </div>
    </div>
  )
}

// --- Lead Card ---
function LeadCard({
  lead,
  draggable,
  onDragStart,
  onClick,
}: {
  lead: Lead
  draggable?: boolean
  onDragStart?: () => void
  onClick?: () => void
}) {
  return (
    <div
      draggable={draggable}
      onDragStart={onDragStart}
      onClick={onClick}
      className="bg-card border border-border rounded-lg px-3 py-2.5 cursor-pointer hover:border-brand/30 transition-all group"
    >
      <div className="flex items-start justify-between">
        <p className="text-sm font-semibold truncate flex-1">{lead.company_name}</p>
        {draggable && <GripVertical className="h-3.5 w-3.5 text-muted-foreground/40 group-hover:text-muted-foreground transition-colors flex-shrink-0 mt-0.5" />}
      </div>
      {lead.contact_name && (
        <p className="text-xs text-muted-foreground mt-0.5">{lead.contact_name}</p>
      )}
      <div className="flex items-center gap-2 mt-2 flex-wrap">
        {lead.estimated_value != null && (
          <span className="flex items-center gap-1 text-xs text-green-400 bg-green-500/10 px-1.5 py-0.5 rounded">
            <DollarSign className="h-3 w-3" />{formatValue(lead.estimated_value, lead.currency)}
          </span>
        )}
        {lead.service_interest && (
          <span className="text-xs text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
            {lead.service_interest}
          </span>
        )}
      </div>
      <div className="flex items-center justify-between mt-2 text-xs text-muted-foreground">
        {lead.next_followup_date && (
          <span className={`flex items-center gap-1 ${new Date(lead.next_followup_date) < new Date() ? "text-red-400" : ""}`}>
            <Calendar className="h-3 w-3" />
            {new Date(lead.next_followup_date).toLocaleDateString("es-ES", { day: "numeric", month: "short" })}
          </span>
        )}
        <span>{daysInStage(lead.created_at)}d</span>
      </div>
    </div>
  )
}

// --- Status Badge ---
function LeadStatusBadge({ status }: { status: LeadStatus }) {
  const map: Record<LeadStatus, { label: string; variant: "secondary" | "warning" | "success" | "destructive" }> = {
    new: { label: "Nuevo", variant: "secondary" },
    contacted: { label: "Contactado", variant: "secondary" },
    discovery: { label: "Discovery", variant: "warning" },
    proposal: { label: "Propuesta", variant: "warning" },
    negotiation: { label: "Negociacion", variant: "warning" },
    won: { label: "Ganado", variant: "success" },
    lost: { label: "Perdido", variant: "destructive" },
  }
  const { label, variant } = map[status] || { label: status, variant: "secondary" as const }
  return <Badge variant={variant}>{label}</Badge>
}

// --- Create Lead Dialog ---
function CreateLeadDialog({
  open,
  onOpenChange,
  users,
  isAdmin,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  users: { id: number; full_name: string }[]
  isAdmin: boolean
}) {
  const qc = useQueryClient()
  const [form, setForm] = useState<LeadCreate>({ company_name: "" })

  const createMutation = useMutation({
    mutationFn: (data: LeadCreate) => leadsApi.create(data),
    onSuccess: () => {
      toast.success("Lead creado")
      qc.invalidateQueries({ queryKey: ["leads"] })
      qc.invalidateQueries({ queryKey: ["pipeline-summary"] })
      onOpenChange(false)
      setForm({ company_name: "" })
    },
    onError: () => toast.error("Error al crear lead"),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Nuevo lead</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <Label>Empresa *</Label>
              <Input
                value={form.company_name}
                onChange={(e) => setForm({ ...form, company_name: e.target.value })}
                placeholder="Nombre de la empresa"
              />
            </div>
            <div>
              <Label>Contacto</Label>
              <Input
                value={form.contact_name || ""}
                onChange={(e) => setForm({ ...form, contact_name: e.target.value })}
                placeholder="Nombre del contacto"
              />
            </div>
            <div>
              <Label>Email</Label>
              <Input
                type="email"
                value={form.email || ""}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="email@empresa.com"
              />
            </div>
            <div>
              <Label>Telefono</Label>
              <Input
                value={form.phone || ""}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                placeholder="+34..."
              />
            </div>
            <div>
              <Label>Website</Label>
              <Input
                value={form.website || ""}
                onChange={(e) => setForm({ ...form, website: e.target.value })}
                placeholder="https://..."
              />
            </div>
            <div>
              <Label>LinkedIn URL</Label>
              <Input
                value={form.linkedin_url || ""}
                onChange={(e) => setForm({ ...form, linkedin_url: e.target.value })}
                placeholder="https://linkedin.com/..."
              />
            </div>
            <div>
              <Label>Fuente</Label>
              <Select
                value={form.source || "other"}
                onChange={(e) => setForm({ ...form, source: e.target.value as LeadSource })}
              >
                {Object.entries(SOURCE_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </Select>
            </div>
            <div>
              <Label>Valor estimado</Label>
              <Input
                type="number"
                value={form.estimated_value || ""}
                onChange={(e) => setForm({ ...form, estimated_value: e.target.value ? Number(e.target.value) : undefined })}
                placeholder="0.00"
              />
            </div>
            <div>
              <Label>Servicio</Label>
              <Select
                value={form.service_interest || ""}
                onChange={(e) => setForm({ ...form, service_interest: e.target.value || undefined })}
              >
                <option value="">Seleccionar</option>
                <option value="seo_audit">SEO Audit</option>
                <option value="retainer">Retainer</option>
                <option value="content">Content</option>
                <option value="technical">Technical SEO</option>
                <option value="consulting">Consulting</option>
              </Select>
            </div>
            <div>
              <Label>Industria</Label>
              <Select
                value={form.industry || ""}
                onChange={(e) => setForm({ ...form, industry: e.target.value || undefined })}
              >
                <option value="">Seleccionar</option>
                <option value="fintech">Fintech</option>
                <option value="health">Salud</option>
                <option value="education">Educacion</option>
                <option value="b2b_saas">B2B SaaS</option>
                <option value="ecommerce">Ecommerce</option>
                <option value="other">Otro</option>
              </Select>
            </div>
            <div>
              <Label>Tamano</Label>
              <Select
                value={form.company_size || ""}
                onChange={(e) => setForm({ ...form, company_size: e.target.value || undefined })}
              >
                <option value="">Seleccionar</option>
                <option value="startup">Startup</option>
                <option value="pyme">PYME</option>
                <option value="enterprise">Enterprise</option>
              </Select>
            </div>
            {isAdmin && (
              <div>
                <Label>Asignar a</Label>
                <Select
                  value={form.assigned_to ? String(form.assigned_to) : ""}
                  onChange={(e) => setForm({ ...form, assigned_to: e.target.value ? Number(e.target.value) : undefined })}
                >
                  <option value="">Sin asignar</option>
                  {users.map((u) => (
                    <option key={u.id} value={String(u.id)}>{u.full_name}</option>
                  ))}
                </Select>
              </div>
            )}
            <div>
              <Label>Proximo followup</Label>
              <Input
                type="date"
                value={form.next_followup_date || ""}
                onChange={(e) => setForm({ ...form, next_followup_date: e.target.value })}
              />
            </div>
          </div>
          <div>
            <Label>Notas</Label>
            <Textarea
              value={form.notes || ""}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              placeholder="Notas sobre el lead..."
              rows={3}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button
            onClick={() => createMutation.mutate(form)}
            disabled={!form.company_name || createMutation.isPending}
          >
            {createMutation.isPending ? "Creando..." : "Crear lead"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
