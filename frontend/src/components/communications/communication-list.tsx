import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  Mail,
  Phone,
  Video,
  MessageCircle,
  Hash,
  MoreHorizontal,
  Plus,
  ArrowDownLeft,
  ArrowUpRight,
  Bell,
  Trash2,
} from "lucide-react"
import { toast } from "sonner"
import { communicationsApi } from "@/lib/api"
import type { Communication, CommunicationChannel, CommunicationDirection } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { getErrorMessage } from "@/lib/utils"

const CHANNEL_ICONS: Record<CommunicationChannel, typeof Mail> = {
  email: Mail,
  call: Phone,
  meeting: Video,
  whatsapp: MessageCircle,
  slack: Hash,
  other: MoreHorizontal,
}

const CHANNEL_LABELS: Record<CommunicationChannel, string> = {
  email: "Email",
  call: "Llamada",
  meeting: "Reunión",
  whatsapp: "WhatsApp",
  slack: "Slack",
  other: "Otro",
}

interface CommunicationListProps {
  clientId: number
}

export function CommunicationList({ clientId }: CommunicationListProps) {
  const queryClient = useQueryClient()
  const [showAddDialog, setShowAddDialog] = useState(false)
  const [deleteId, setDeleteId] = useState<number | null>(null)

  const { data: communications = [], isLoading } = useQuery({
    queryKey: ["communications", clientId],
    queryFn: () => communicationsApi.list(clientId),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => communicationsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["communications", clientId] })
      toast.success("Comunicación eliminada")
      setDeleteId(null)
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar")),
  })

  const formatDate = (date: string) => {
    return new Date(date).toLocaleDateString("es-ES", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  }

  const formatRelativeDate = (date: string) => {
    const now = new Date()
    const d = new Date(date)
    const diffDays = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24))

    if (diffDays === 0) return "Hoy"
    if (diffDays === 1) return "Ayer"
    if (diffDays < 7) return `Hace ${diffDays} días`
    if (diffDays < 30) return `Hace ${Math.floor(diffDays / 7)} semanas`
    return formatDate(date)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Comunicaciones</h3>
        <Button size="sm" onClick={() => setShowAddDialog(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Registrar
        </Button>
      </div>

      {isLoading ? (
        <p className="text-muted-foreground text-sm">Cargando...</p>
      ) : communications.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center">
            <MessageCircle className="h-10 w-10 mx-auto text-muted-foreground mb-3" />
            <p className="text-muted-foreground text-sm">No hay comunicaciones registradas</p>
            <Button variant="outline" size="sm" className="mt-3" onClick={() => setShowAddDialog(true)}>
              Registrar primera comunicación
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {communications.map((comm) => (
            <CommunicationCard
              key={comm.id}
              communication={comm}
              onDelete={() => setDeleteId(comm.id)}
              formatRelativeDate={formatRelativeDate}
            />
          ))}
        </div>
      )}

      <AddCommunicationDialog
        open={showAddDialog}
        onOpenChange={setShowAddDialog}
        clientId={clientId}
      />

      <ConfirmDialog
        open={deleteId !== null}
        onOpenChange={(open) => !open && setDeleteId(null)}
        title="Eliminar comunicación"
        description="¿Seguro que quieres eliminar este registro de comunicación?"
        confirmLabel="Eliminar"
        onConfirm={() => deleteId && deleteMutation.mutate(deleteId)}
      />
    </div>
  )
}

function CommunicationCard({
  communication,
  onDelete,
  formatRelativeDate,
}: {
  communication: Communication
  onDelete: () => void
  formatRelativeDate: (date: string) => string
}) {
  const Icon = CHANNEL_ICONS[communication.channel]
  const isInbound = communication.direction === "inbound"

  return (
    <div className="p-4 rounded-lg border border-border bg-card hover:border-brand/20 transition-colors group">
      <div className="flex items-start gap-3">
        <div className={`p-2 rounded-lg ${isInbound ? "bg-blue-500/10" : "bg-green-500/10"}`}>
          <Icon className={`h-4 w-4 ${isInbound ? "text-blue-400" : "text-green-400"}`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-sm">{CHANNEL_LABELS[communication.channel]}</span>
            {isInbound ? (
              <ArrowDownLeft className="h-3.5 w-3.5 text-blue-400" />
            ) : (
              <ArrowUpRight className="h-3.5 w-3.5 text-green-400" />
            )}
            <span className="text-xs text-muted-foreground">
              {formatRelativeDate(communication.occurred_at)}
            </span>
            {communication.requires_followup && (
              <Badge variant="warning" className="ml-auto">
                <Bell className="h-3 w-3 mr-1" />
                Seguimiento
              </Badge>
            )}
          </div>
          {communication.subject && (
            <p className="text-sm font-medium mb-1">{communication.subject}</p>
          )}
          <p className="text-sm text-muted-foreground line-clamp-2">{communication.summary}</p>
          <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
            {communication.contact_name && (
              <span>Con: {communication.contact_name}</span>
            )}
            {communication.user_name && (
              <span>Por: {communication.user_name}</span>
            )}
          </div>
        </div>
        <button
          onClick={onDelete}
          className="p-1.5 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 opacity-0 group-hover:opacity-100 transition-opacity"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}

function AddCommunicationDialog({
  open,
  onOpenChange,
  clientId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  clientId: number
}) {
  const queryClient = useQueryClient()
  const [formData, setFormData] = useState({
    channel: "email" as CommunicationChannel,
    direction: "outbound" as CommunicationDirection,
    subject: "",
    summary: "",
    contact_name: "",
    occurred_at: new Date().toISOString().slice(0, 16),
    requires_followup: false,
    followup_date: "",
    followup_notes: "",
  })

  const createMutation = useMutation({
    mutationFn: () =>
      communicationsApi.create(clientId, {
        channel: formData.channel,
        direction: formData.direction,
        subject: formData.subject || undefined,
        summary: formData.summary,
        contact_name: formData.contact_name || undefined,
        occurred_at: new Date(formData.occurred_at).toISOString(),
        requires_followup: formData.requires_followup,
        followup_date: formData.followup_date ? new Date(formData.followup_date).toISOString() : undefined,
        followup_notes: formData.followup_notes || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["communications", clientId] })
      toast.success("Comunicación registrada")
      onOpenChange(false)
      setFormData({
        channel: "email",
        direction: "outbound",
        subject: "",
        summary: "",
        contact_name: "",
        occurred_at: new Date().toISOString().slice(0, 16),
        requires_followup: false,
        followup_date: "",
        followup_notes: "",
      })
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al registrar")),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Registrar comunicación</DialogTitle>
      </DialogHeader>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          createMutation.mutate()
        }}
        className="space-y-4 mt-4"
      >
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>Canal *</Label>
            <Select
              value={formData.channel}
              onChange={(e) => setFormData({ ...formData, channel: e.target.value as CommunicationChannel })}
            >
              <option value="email">Email</option>
              <option value="call">Llamada</option>
              <option value="meeting">Reunión</option>
              <option value="whatsapp">WhatsApp</option>
              <option value="slack">Slack</option>
              <option value="other">Otro</option>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Dirección *</Label>
            <Select
              value={formData.direction}
              onChange={(e) => setFormData({ ...formData, direction: e.target.value as CommunicationDirection })}
            >
              <option value="outbound">Enviado (saliente)</option>
              <option value="inbound">Recibido (entrante)</option>
            </Select>
          </div>
        </div>

        <div className="space-y-2">
          <Label>Asunto</Label>
          <Input
            value={formData.subject}
            onChange={(e) => setFormData({ ...formData, subject: e.target.value })}
            placeholder="Asunto o tema de la comunicación"
          />
        </div>

        <div className="space-y-2">
          <Label>Resumen *</Label>
          <textarea
            value={formData.summary}
            onChange={(e) => setFormData({ ...formData, summary: e.target.value })}
            placeholder="¿De qué se habló? Puntos clave..."
            className="flex min-h-[100px] w-full rounded-[10px] border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand"
            required
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>Contacto del cliente</Label>
            <Input
              value={formData.contact_name}
              onChange={(e) => setFormData({ ...formData, contact_name: e.target.value })}
              placeholder="Nombre del contacto"
            />
          </div>
          <div className="space-y-2">
            <Label>Fecha y hora *</Label>
            <Input
              type="datetime-local"
              value={formData.occurred_at}
              onChange={(e) => setFormData({ ...formData, occurred_at: e.target.value })}
              required
            />
          </div>
        </div>

        <div className="p-3 rounded-lg bg-surface space-y-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={formData.requires_followup}
              onChange={(e) => setFormData({ ...formData, requires_followup: e.target.checked })}
              className="rounded border-border"
            />
            <span className="text-sm">Requiere seguimiento</span>
          </label>

          {formData.requires_followup && (
            <>
              <div className="space-y-2">
                <Label>Fecha de seguimiento</Label>
                <Input
                  type="date"
                  value={formData.followup_date}
                  onChange={(e) => setFormData({ ...formData, followup_date: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label>Notas de seguimiento</Label>
                <Input
                  value={formData.followup_notes}
                  onChange={(e) => setFormData({ ...formData, followup_notes: e.target.value })}
                  placeholder="Qué hay que hacer..."
                />
              </div>
            </>
          )}
        </div>

        <div className="flex justify-end gap-2 pt-4">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button type="submit" disabled={createMutation.isPending}>
            {createMutation.isPending ? "Guardando..." : "Guardar"}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
