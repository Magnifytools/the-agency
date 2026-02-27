import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Receipt, CreditCard, CalendarClock, Plus } from "lucide-react"
import { toast } from "sonner"
import { billingEventsApi, clientsApi } from "@/lib/api"
import type { Client, BillingCycle, BillingEventCreate } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { getErrorMessage } from "@/lib/utils"

interface Props {
  client: Client
}

const BILLING_CYCLES: { value: BillingCycle; label: string }[] = [
  { value: "monthly", label: "Mensual" },
  { value: "bimonthly", label: "Bimestral" },
  { value: "quarterly", label: "Trimestral" },
  { value: "annual", label: "Anual" },
  { value: "one_time", label: "Unico" },
]

const EVENT_TYPE_LABELS: Record<string, { label: string; color: string }> = {
  invoice_sent: { label: "Factura enviada", color: "text-blue-500" },
  payment_received: { label: "Pago recibido", color: "text-green-500" },
  reminder_sent: { label: "Recordatorio", color: "text-amber-500" },
  note: { label: "Nota", color: "text-muted-foreground" },
}

export function BillingTab({ client }: Props) {
  const qc = useQueryClient()
  const [showConfig, setShowConfig] = useState(false)
  const [showEventForm, setShowEventForm] = useState(false)

  const { data: status } = useQuery({
    queryKey: ["billing-status", client.id],
    queryFn: () => billingEventsApi.status(client.id),
  })

  const { data: events = [] } = useQuery({
    queryKey: ["billing-events", client.id],
    queryFn: () => billingEventsApi.list(client.id),
  })

  const markInvoicedMut = useMutation({
    mutationFn: () => billingEventsApi.markInvoiced(client.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["billing-status", client.id] })
      qc.invalidateQueries({ queryKey: ["billing-events", client.id] })
      qc.invalidateQueries({ queryKey: ["client-summary", client.id] })
      toast.success("Marcado como facturado")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const markPaidMut = useMutation({
    mutationFn: () => billingEventsApi.markPaid(client.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["billing-status", client.id] })
      qc.invalidateQueries({ queryKey: ["billing-events", client.id] })
      toast.success("Pago registrado")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const createEventMut = useMutation({
    mutationFn: (data: BillingEventCreate) => billingEventsApi.create(client.id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["billing-events", client.id] })
      setShowEventForm(false)
      toast.success("Evento registrado")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const cycleName = status?.billing_cycle
    ? BILLING_CYCLES.find((c) => c.value === status.billing_cycle)?.label ?? status.billing_cycle
    : "No configurado"

  return (
    <div className="space-y-6">
      {/* Status Card */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Ciclo</p>
            <p className="text-lg font-semibold mt-1">{cycleName}</p>
            {status?.billing_day && (
              <p className="text-xs text-muted-foreground">Dia {status.billing_day} del mes</p>
            )}
          </CardContent>
        </Card>

        <Card className={status?.is_overdue ? "border-red-300 bg-red-50/10" : ""}>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <CalendarClock className="h-3 w-3" /> Proxima factura
            </p>
            {status?.next_invoice_date ? (
              <>
                <p className="text-lg font-semibold mt-1">
                  {new Date(status.next_invoice_date).toLocaleDateString("es-ES")}
                </p>
                <p className={`text-xs ${status.is_overdue ? "text-red-500 font-medium" : "text-muted-foreground"}`}>
                  {status.is_overdue
                    ? `Vencida hace ${Math.abs(status.days_until_invoice!)} dias`
                    : status.days_until_invoice === 0
                      ? "Hoy"
                      : `En ${status.days_until_invoice} dias`}
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground mt-1">Sin configurar</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Fee mensual</p>
            <p className="text-lg font-semibold mt-1">
              {status?.monthly_fee != null
                ? `${status.monthly_fee.toLocaleString("es-ES")} ${client.currency}`
                : "—"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Ultimo pago</p>
            {status?.last_payment_date ? (
              <>
                <p className="text-lg font-semibold mt-1">
                  {new Date(status.last_payment_date).toLocaleDateString("es-ES")}
                </p>
                <p className="text-xs text-muted-foreground">
                  {status.last_payment_amount?.toLocaleString("es-ES")} {client.currency}
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground mt-1">Sin pagos</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Actions */}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          onClick={() => markInvoicedMut.mutate()}
          disabled={markInvoicedMut.isPending}
        >
          <Receipt className="h-4 w-4 mr-1" />
          {markInvoicedMut.isPending ? "Marcando..." : "Marcar facturado"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => markPaidMut.mutate()}
          disabled={markPaidMut.isPending}
        >
          <CreditCard className="h-4 w-4 mr-1" />
          {markPaidMut.isPending ? "Registrando..." : "Registrar pago"}
        </Button>
        <Button size="sm" variant="outline" onClick={() => setShowConfig(true)}>
          Configurar ciclo
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setShowEventForm(true)}>
          <Plus className="h-4 w-4 mr-1" /> Evento manual
        </Button>
      </div>

      {/* History */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Historial de facturacion</CardTitle>
        </CardHeader>
        <CardContent>
          {events.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-6">
              No hay eventos de facturacion registrados
            </p>
          ) : (
            <div className="space-y-3">
              {events.map((ev) => {
                const meta = EVENT_TYPE_LABELS[ev.event_type] ?? { label: ev.event_type, color: "" }
                return (
                  <div key={ev.id} className="flex items-start gap-3 text-sm">
                    <div className="w-2 h-2 rounded-full bg-muted-foreground mt-1.5 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`font-medium ${meta.color}`}>{meta.label}</span>
                        {ev.amount != null && (
                          <span className="mono text-xs">{ev.amount.toLocaleString("es-ES")} {client.currency}</span>
                        )}
                        {ev.invoice_number && (
                          <Badge variant="secondary" className="text-[10px]">{ev.invoice_number}</Badge>
                        )}
                      </div>
                      {ev.notes && <p className="text-xs text-muted-foreground">{ev.notes}</p>}
                    </div>
                    <span className="text-xs text-muted-foreground whitespace-nowrap">
                      {new Date(ev.event_date).toLocaleDateString("es-ES")}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Config Dialog */}
      <Dialog open={showConfig} onOpenChange={setShowConfig}>
        <DialogHeader>
          <DialogTitle>Configurar facturacion</DialogTitle>
        </DialogHeader>
        <BillingConfigForm
          client={client}
          onSave={() => {
            setShowConfig(false)
            qc.invalidateQueries({ queryKey: ["billing-status", client.id] })
            qc.invalidateQueries({ queryKey: ["client-summary", client.id] })
          }}
        />
      </Dialog>

      {/* Manual Event Dialog */}
      <Dialog open={showEventForm} onOpenChange={setShowEventForm}>
        <DialogHeader>
          <DialogTitle>Registrar evento</DialogTitle>
        </DialogHeader>
        <EventForm
          onSubmit={(data) => createEventMut.mutate(data)}
          loading={createEventMut.isPending}
          onCancel={() => setShowEventForm(false)}
        />
      </Dialog>
    </div>
  )
}

function BillingConfigForm({ client, onSave }: { client: Client; onSave: () => void }) {
  const [cycle, setCycle] = useState<BillingCycle | "">(client.billing_cycle ?? "")
  const [day, setDay] = useState(client.billing_day?.toString() ?? "")
  const [nextDate, setNextDate] = useState(client.next_invoice_date ?? "")
  const [saving, setSaving] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      await clientsApi.update(client.id, {
        billing_cycle: cycle || null,
        billing_day: day ? Number(day) : null,
        next_invoice_date: nextDate || null,
      })
      toast.success("Configuracion guardada")
      onSave()
    } catch (err) {
      toast.error(getErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 p-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label>Ciclo de facturacion</Label>
          <select
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
            value={cycle}
            onChange={(e) => setCycle(e.target.value as BillingCycle | "")}
          >
            <option value="">Sin ciclo</option>
            {BILLING_CYCLES.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </div>
        <div>
          <Label>Dia de facturacion (1-28)</Label>
          <Input
            type="number"
            min={1}
            max={28}
            value={day}
            onChange={(e) => setDay(e.target.value)}
            placeholder="15"
          />
        </div>
        <div className="sm:col-span-2">
          <Label>Proxima fecha de facturacion</Label>
          <Input
            type="date"
            value={nextDate}
            onChange={(e) => setNextDate(e.target.value)}
          />
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <Button type="submit" disabled={saving}>
          {saving ? "Guardando..." : "Guardar"}
        </Button>
      </div>
    </form>
  )
}

function EventForm({
  onSubmit,
  loading,
  onCancel,
}: {
  onSubmit: (data: BillingEventCreate) => void
  loading: boolean
  onCancel: () => void
}) {
  const [eventType, setEventType] = useState<string>("note")
  const [amount, setAmount] = useState("")
  const [invoiceNumber, setInvoiceNumber] = useState("")
  const [notes, setNotes] = useState("")
  const [eventDate, setEventDate] = useState(new Date().toISOString().slice(0, 10))

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit({
      event_type: eventType as BillingEventCreate["event_type"],
      amount: amount ? Number(amount) : null,
      invoice_number: invoiceNumber.trim() || null,
      notes: notes.trim() || null,
      event_date: eventDate,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 p-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label>Tipo</Label>
          <select
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
            value={eventType}
            onChange={(e) => setEventType(e.target.value)}
          >
            <option value="invoice_sent">Factura enviada</option>
            <option value="payment_received">Pago recibido</option>
            <option value="reminder_sent">Recordatorio</option>
            <option value="note">Nota</option>
          </select>
        </div>
        <div>
          <Label>Fecha</Label>
          <Input type="date" value={eventDate} onChange={(e) => setEventDate(e.target.value)} required />
        </div>
        <div>
          <Label>Importe</Label>
          <Input type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" />
        </div>
        <div>
          <Label>Nº Factura</Label>
          <Input value={invoiceNumber} onChange={(e) => setInvoiceNumber(e.target.value)} placeholder="FAC-001" />
        </div>
      </div>
      <div>
        <Label>Notas</Label>
        <Input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notas..." />
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>Cancelar</Button>
        <Button type="submit" disabled={loading}>
          {loading ? "Guardando..." : "Registrar"}
        </Button>
      </div>
    </form>
  )
}
