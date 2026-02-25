import { useState } from "react"
import { useParams, Link, useNavigate } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { leadsApi, usersApi } from "@/lib/api"
import { useAuth } from "@/context/auth-context"
import type { LeadStatus, LeadActivityType } from "@/lib/types"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import {
  ArrowLeft, Building2, Mail, Phone, Globe, Linkedin,
  Calendar, DollarSign, ChevronRight, ChevronLeft, Plus,
  MessageSquare, PhoneCall, Video, FileText, Bell, UserCheck, Sparkles
} from "lucide-react"
import { toast } from "sonner"

const STATUS_ORDER: LeadStatus[] = ["new", "contacted", "discovery", "proposal", "negotiation", "won", "lost"]
const STATUS_LABELS: Record<LeadStatus, string> = {
  new: "Nuevo",
  contacted: "Contactado",
  discovery: "Discovery",
  proposal: "Propuesta",
  negotiation: "Negociacion",
  won: "Ganado",
  lost: "Perdido",
}

const ACTIVITY_ICONS: Record<LeadActivityType, typeof MessageSquare> = {
  note: MessageSquare,
  email_sent: Mail,
  email_received: Mail,
  call: PhoneCall,
  meeting: Video,
  proposal_sent: FileText,
  status_change: ChevronRight,
  followup_set: Bell,
}

const ACTIVITY_LABELS: Record<LeadActivityType, string> = {
  note: "Nota",
  email_sent: "Email enviado",
  email_received: "Email recibido",
  call: "Llamada",
  meeting: "Reunion",
  proposal_sent: "Propuesta enviada",
  status_change: "Cambio de estado",
  followup_set: "Followup programado",
}

function formatValue(v: number | null, currency = "EUR") {
  if (v == null) return "-"
  return new Intl.NumberFormat("es-ES", { style: "currency", currency }).format(v)
}

export default function LeadDetailPage() {
  const { id } = useParams<{ id: string }>()
  const leadId = Number(id)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { isAdmin } = useAuth()
  const [showActivity, setShowActivity] = useState(false)
  const [showConvert, setShowConvert] = useState(false)
  const [showLost, setShowLost] = useState(false)
  const [lostReason, setLostReason] = useState("")
  const [editFollowup, setEditFollowup] = useState(false)
  const [followupDate, setFollowupDate] = useState("")
  const [followupNotes, setFollowupNotes] = useState("")
  const [activityForm, setActivityForm] = useState({ activity_type: "note" as string, title: "", description: "" })

  const { data: lead, isLoading } = useQuery({
    queryKey: ["lead", leadId],
    queryFn: () => leadsApi.get(leadId),
    enabled: !!leadId,
  })

  const updateMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => leadsApi.update(leadId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["lead", leadId] })
      qc.invalidateQueries({ queryKey: ["leads"] })
      qc.invalidateQueries({ queryKey: ["pipeline-summary"] })
    },
  })

  const addActivityMutation = useMutation({
    mutationFn: (data: { activity_type: string; title: string; description?: string }) =>
      leadsApi.addActivity(leadId, data),
    onSuccess: () => {
      toast.success("Actividad registrada")
      qc.invalidateQueries({ queryKey: ["lead", leadId] })
      setShowActivity(false)
      setActivityForm({ activity_type: "note", title: "", description: "" })
    },
  })

  const convertMutation = useMutation({
    mutationFn: () => leadsApi.convert(leadId),
    onSuccess: (data) => {
      toast.success(`Lead convertido a cliente: ${data.client_name}`)
      navigate(`/clients/${data.client_id}`)
    },
    onError: () => toast.error("Error al convertir"),
  })

  const handleAdvanceStage = () => {
    if (!lead) return
    const idx = STATUS_ORDER.indexOf(lead.status)
    if (idx < 0 || idx >= 4) return // Can't advance past negotiation with this button
    const next = STATUS_ORDER[idx + 1]
    if (next === "won") {
      setShowConvert(true)
    } else {
      updateMutation.mutate({ status: next })
    }
  }

  const handleRetreatStage = () => {
    if (!lead) return
    const idx = STATUS_ORDER.indexOf(lead.status)
    if (idx <= 0) return
    const prev = STATUS_ORDER[idx - 1]
    updateMutation.mutate({ status: prev })
  }

  const handleSaveFollowup = () => {
    updateMutation.mutate(
      { next_followup_date: followupDate || null, next_followup_notes: followupNotes || null },
      {
        onSuccess: () => {
          setEditFollowup(false)
          toast.success("Followup actualizado")
        },
      }
    )
  }

  const handleLostConfirm = () => {
    updateMutation.mutate(
      { status: "lost", lost_reason: lostReason },
      {
        onSuccess: () => {
          setShowLost(false)
          setLostReason("")
          toast.success("Lead marcado como perdido")
        },
      }
    )
  }

  if (isLoading) return <p className="text-muted-foreground">Cargando...</p>
  if (!lead) return <p className="text-muted-foreground">Lead no encontrado</p>

  const currentIdx = STATUS_ORDER.indexOf(lead.status)
  const canAdvance = currentIdx >= 0 && currentIdx <= 4 && lead.status !== "won" && lead.status !== "lost"
  const canRetreat = currentIdx > 0 && lead.status !== "won" && lead.status !== "lost"
  const canConvert = lead.status === "negotiation" || lead.status === "proposal"

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Link to="/leads">
          <Button variant="ghost" size="icon"><ArrowLeft className="h-4 w-4" /></Button>
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-3 flex-wrap">
            <h2 className="text-2xl font-bold">{lead.company_name}</h2>
            <LeadStatusBadge status={lead.status} />
          </div>
          {lead.contact_name && <p className="text-muted-foreground mt-0.5">{lead.contact_name}</p>}
        </div>
        <div className="flex gap-2">
          {lead.status !== "won" && lead.status !== "lost" && (
            <Button
              variant="outline"
              onClick={() => navigate("/proposals", { state: { createFromLead: lead } })}
            >
              <Sparkles className="h-4 w-4 mr-2" /> Crear Propuesta
            </Button>
          )}
          {canConvert && (
            <Button onClick={() => setShowConvert(true)} className="bg-green-600 hover:bg-green-700">
              <UserCheck className="h-4 w-4 mr-2" /> Convertir a cliente
            </Button>
          )}
          {lead.status !== "won" && lead.status !== "lost" && (
            <Button variant="outline" className="text-red-400 border-red-400/30 hover:bg-red-400/10" onClick={() => setShowLost(true)}>
              Marcar perdido
            </Button>
          )}
        </div>
      </div>

      {/* Stage Progress */}
      {lead.status !== "won" && lead.status !== "lost" && (
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" onClick={handleRetreatStage} disabled={!canRetreat}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <div className="flex-1 flex gap-1">
            {STATUS_ORDER.slice(0, 5).map((s, i) => (
              <div
                key={s}
                className={`h-2 flex-1 rounded-full transition-colors ${i <= currentIdx ? "bg-brand" : "bg-muted"}`}
              />
            ))}
          </div>
          <Button variant="ghost" size="icon" onClick={handleAdvanceStage} disabled={!canAdvance}>
            <ChevronRight className="h-4 w-4" />
          </Button>
          <span className="text-xs text-muted-foreground ml-1">{STATUS_LABELS[lead.status]}</span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Info */}
        <div className="lg:col-span-2 space-y-6">
          {/* Contact Info */}
          <Card>
            <CardHeader><CardTitle className="text-base">Informacion de contacto</CardTitle></CardHeader>
            <CardContent className="grid grid-cols-2 gap-4">
              <InfoRow icon={Mail} label="Email" value={lead.email} link={lead.email ? `mailto:${lead.email}` : undefined} />
              <InfoRow icon={Phone} label="Telefono" value={lead.phone} />
              <InfoRow icon={Globe} label="Website" value={lead.website} link={lead.website || undefined} />
              <InfoRow icon={Linkedin} label="LinkedIn" value={lead.linkedin_url ? "Ver perfil" : null} link={lead.linkedin_url || undefined} />
            </CardContent>
          </Card>

          {/* Timeline */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base">Actividad</CardTitle>
              <Button size="sm" onClick={() => setShowActivity(true)}>
                <Plus className="h-3.5 w-3.5 mr-1.5" /> Actividad
              </Button>
            </CardHeader>
            <CardContent>
              {lead.activities && lead.activities.length > 0 ? (
                <div className="space-y-4">
                  {lead.activities.map((act) => {
                    const Icon = ACTIVITY_ICONS[act.activity_type] || MessageSquare
                    return (
                      <div key={act.id} className="flex gap-3">
                        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-muted flex items-center justify-center">
                          <Icon className="h-4 w-4 text-muted-foreground" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">{act.title}</span>
                            <span className="text-xs text-muted-foreground">
                              {ACTIVITY_LABELS[act.activity_type]}
                            </span>
                          </div>
                          {act.description && (
                            <p className="text-sm text-muted-foreground mt-0.5">{act.description}</p>
                          )}
                          <p className="text-xs text-muted-foreground mt-1">
                            {act.user_name} · {new Date(act.created_at).toLocaleString("es-ES")}
                          </p>
                        </div>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground text-center py-6">Sin actividad registrada</p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right: Sidebar */}
        <div className="space-y-6">
          {/* Value */}
          <Card>
            <CardContent className="p-4 space-y-3">
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wider font-bold">Valor estimado</p>
                <p className="text-xl font-bold mt-1">{formatValue(lead.estimated_value, lead.currency)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wider font-bold">Servicio</p>
                <p className="text-sm mt-1">{lead.service_interest || "-"}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wider font-bold">Fuente</p>
                <p className="text-sm mt-1">{lead.source}</p>
              </div>
              {lead.industry && (
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wider font-bold">Industria</p>
                  <p className="text-sm mt-1">{lead.industry}</p>
                </div>
              )}
              {lead.company_size && (
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wider font-bold">Tamano</p>
                  <p className="text-sm mt-1">{lead.company_size}</p>
                </div>
              )}
              {lead.assigned_user_name && (
                <div>
                  <p className="text-xs text-muted-foreground uppercase tracking-wider font-bold">Asignado a</p>
                  <p className="text-sm mt-1">{lead.assigned_user_name}</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Followup */}
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs text-muted-foreground uppercase tracking-wider font-bold">Proximo followup</p>
                <Button variant="ghost" size="sm" onClick={() => {
                  setFollowupDate(lead.next_followup_date || "")
                  setFollowupNotes(lead.next_followup_notes || "")
                  setEditFollowup(true)
                }}>
                  Editar
                </Button>
              </div>
              {editFollowup ? (
                <div className="space-y-2">
                  <Input type="date" value={followupDate} onChange={(e) => setFollowupDate(e.target.value)} />
                  <Textarea
                    value={followupNotes}
                    onChange={(e) => setFollowupNotes(e.target.value)}
                    placeholder="Notas del followup..."
                    rows={2}
                  />
                  <div className="flex gap-2">
                    <Button size="sm" onClick={handleSaveFollowup}>Guardar</Button>
                    <Button size="sm" variant="outline" onClick={() => setEditFollowup(false)}>Cancelar</Button>
                  </div>
                </div>
              ) : (
                <div>
                  {lead.next_followup_date ? (
                    <>
                      <p className={`text-sm font-medium ${new Date(lead.next_followup_date) < new Date() ? "text-red-400" : ""}`}>
                        {new Date(lead.next_followup_date).toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" })}
                      </p>
                      {lead.next_followup_notes && (
                        <p className="text-sm text-muted-foreground mt-1">{lead.next_followup_notes}</p>
                      )}
                    </>
                  ) : (
                    <p className="text-sm text-muted-foreground">Sin followup programado</p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Notes */}
          {lead.notes && (
            <Card>
              <CardContent className="p-4">
                <p className="text-xs text-muted-foreground uppercase tracking-wider font-bold mb-2">Notas</p>
                <p className="text-sm whitespace-pre-wrap">{lead.notes}</p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* Add Activity Dialog */}
      <Dialog open={showActivity} onOpenChange={setShowActivity}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Nueva actividad</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Tipo</Label>
              <Select
                value={activityForm.activity_type}
                onChange={(e) => setActivityForm({ ...activityForm, activity_type: e.target.value })}
              >
                {Object.entries(ACTIVITY_LABELS)
                  .filter(([k]) => k !== "status_change")
                  .map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
              </Select>
            </div>
            <div>
              <Label>Titulo *</Label>
              <Input
                value={activityForm.title}
                onChange={(e) => setActivityForm({ ...activityForm, title: e.target.value })}
                placeholder="Resumen de la actividad"
              />
            </div>
            <div>
              <Label>Descripcion</Label>
              <Textarea
                value={activityForm.description}
                onChange={(e) => setActivityForm({ ...activityForm, description: e.target.value })}
                placeholder="Detalles..."
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowActivity(false)}>Cancelar</Button>
            <Button
              onClick={() => addActivityMutation.mutate(activityForm)}
              disabled={!activityForm.title || addActivityMutation.isPending}
            >
              Registrar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Convert Dialog */}
      <Dialog open={showConvert} onOpenChange={setShowConvert}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Convertir a cliente</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Se creara un nuevo cliente con los datos de <strong>{lead.company_name}</strong>.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowConvert(false)}>Cancelar</Button>
            <Button onClick={() => convertMutation.mutate()} disabled={convertMutation.isPending}>
              {convertMutation.isPending ? "Convirtiendo..." : "Convertir a cliente"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Lost Dialog */}
      <Dialog open={showLost} onOpenChange={(o) => { if (!o) { setShowLost(false); setLostReason("") } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Marcar como perdido</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Label>Razon de perdida</Label>
            <Textarea
              value={lostReason}
              onChange={(e) => setLostReason(e.target.value)}
              placeholder="Presupuesto, timing, competencia..."
              rows={3}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setShowLost(false); setLostReason("") }}>Cancelar</Button>
            <Button variant="destructive" onClick={handleLostConfirm}>Marcar perdido</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// --- Info Row ---
function InfoRow({ icon: Icon, label, value, link }: { icon: typeof Mail; label: string; value: string | null; link?: string }) {
  if (!value) return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm">-</p>
    </div>
  )
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      {link ? (
        <a href={link} target="_blank" rel="noopener noreferrer" className="text-sm text-brand hover:underline flex items-center gap-1">
          <Icon className="h-3.5 w-3.5" /> {value}
        </a>
      ) : (
        <p className="text-sm flex items-center gap-1"><Icon className="h-3.5 w-3.5 text-muted-foreground" /> {value}</p>
      )}
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
