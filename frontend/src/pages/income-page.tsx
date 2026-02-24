import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { financeIncomeApi, clientsApi } from "@/lib/api"
import type { Income, IncomeCreate } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Plus, Pencil, Trash2 } from "lucide-react"
import { toast } from "sonner"

const TYPES = [
  { label: "Factura", value: "factura" },
  { label: "Recurrente", value: "recurrente" },
  { label: "Extra", value: "extra" },
]

const STATUSES = [
  { label: "Cobrado", value: "cobrado" },
  { label: "Pendiente", value: "pendiente" },
]

const fmt = (n: number) => n.toLocaleString("es-ES", { style: "currency", currency: "EUR" })

export default function IncomePage() {
  const qc = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Income | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [filters, setFilters] = useState<{ type?: string; status?: string }>({})

  const { data: items = [], isLoading } = useQuery({
    queryKey: ["finance-income", filters],
    queryFn: () => financeIncomeApi.list(filters),
  })

  const { data: clients = [] } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list(),
  })

  const createMut = useMutation({
    mutationFn: (data: IncomeCreate) => financeIncomeApi.create(data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["finance-income"] }); setDialogOpen(false); setEditing(null); toast.success("Ingreso creado") },
    onError: () => toast.error("Error al crear"),
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<IncomeCreate> }) => financeIncomeApi.update(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["finance-income"] }); setDialogOpen(false); setEditing(null); toast.success("Ingreso actualizado") },
    onError: () => toast.error("Error al actualizar"),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => financeIncomeApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["finance-income"] }); setDeleteId(null); toast.success("Ingreso eliminado") },
  })

  const total = items.reduce((s, i) => s + i.amount, 0)

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    const data: IncomeCreate = {
      date: fd.get("date") as string,
      description: fd.get("description") as string,
      amount: parseFloat(fd.get("amount") as string) || 0,
      type: (fd.get("type") as string) || "factura",
      client_id: fd.get("client_id") ? parseInt(fd.get("client_id") as string) : undefined,
      invoice_number: (fd.get("invoice_number") as string) || "",
      vat_rate: parseFloat(fd.get("vat_rate") as string) || 21,
      vat_amount: parseFloat(fd.get("vat_amount") as string) || 0,
      status: (fd.get("status") as string) || "cobrado",
      notes: (fd.get("notes") as string) || "",
    }
    if (editing) {
      updateMut.mutate({ id: editing.id, data })
    } else {
      createMut.mutate(data)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Ingresos</h1>
          <p className="text-muted-foreground">Total: {fmt(total)} ({items.length} registros)</p>
        </div>
        <Button onClick={() => { setEditing(null); setDialogOpen(true) }}><Plus className="h-4 w-4 mr-1" />Nuevo ingreso</Button>
      </div>

      <div className="flex gap-2">
        <Select value={filters.type || ""} onChange={(e) => setFilters(f => ({ ...f, type: e.target.value || undefined }))}>
          <option value="">Todos los tipos</option>
          {TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
        </Select>
        <Select value={filters.status || ""} onChange={(e) => setFilters(f => ({ ...f, status: e.target.value || undefined }))}>
          <option value="">Todos los estados</option>
          {STATUSES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
        </Select>
      </div>

      {isLoading ? <p>Cargando...</p> : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Fecha</TableHead>
                <TableHead>Descripcion</TableHead>
                <TableHead>Cliente</TableHead>
                <TableHead>Tipo</TableHead>
                <TableHead className="text-right">Importe</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead className="w-20"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map(item => (
                <TableRow key={item.id}>
                  <TableCell>{item.date}</TableCell>
                  <TableCell>{item.description}</TableCell>
                  <TableCell>{item.client_name || "-"}</TableCell>
                  <TableCell><Badge variant="secondary">{item.type}</Badge></TableCell>
                  <TableCell className="text-right font-mono">{fmt(item.amount)}</TableCell>
                  <TableCell>
                    <Badge variant={item.status === "cobrado" ? "success" : "warning"}>
                      {item.status === "cobrado" ? "Cobrado" : "Pendiente"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="sm" onClick={() => { setEditing(item); setDialogOpen(true) }}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setDeleteId(item.id)}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {items.length === 0 && <TableRow><TableCell colSpan={7} className="text-center text-muted-foreground">Sin ingresos</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={dialogOpen} onClose={() => { setDialogOpen(false); setEditing(null) }}>
        <DialogHeader><DialogTitle>{editing ? "Editar ingreso" : "Nuevo ingreso"}</DialogTitle></DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div><Label>Fecha</Label><Input name="date" type="date" defaultValue={editing?.date || new Date().toISOString().slice(0, 10)} required /></div>
            <div><Label>Importe</Label><Input name="amount" type="number" step="0.01" defaultValue={editing?.amount || ""} required /></div>
          </div>
          <div><Label>Descripcion</Label><Input name="description" defaultValue={editing?.description || ""} required /></div>
          <div className="grid grid-cols-2 gap-4">
            <div><Label>Tipo</Label>
              <Select name="type" defaultValue={editing?.type || "factura"}>
                {TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
              </Select>
            </div>
            <div><Label>Estado</Label>
              <Select name="status" defaultValue={editing?.status || "cobrado"}>
                {STATUSES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div><Label>Cliente</Label>
              <Select name="client_id" defaultValue={editing?.client_id?.toString() || ""}>
                <option value="">Sin cliente</option>
                {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </div>
            <div><Label>N. Factura</Label><Input name="invoice_number" defaultValue={editing?.invoice_number || ""} /></div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div><Label>Tipo IVA (%)</Label><Input name="vat_rate" type="number" step="0.01" defaultValue={editing?.vat_rate ?? 21} /></div>
            <div><Label>IVA importe</Label><Input name="vat_amount" type="number" step="0.01" defaultValue={editing?.vat_amount ?? 0} /></div>
          </div>
          <div><Label>Notas</Label><Input name="notes" defaultValue={editing?.notes || ""} /></div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => { setDialogOpen(false); setEditing(null) }}>Cancelar</Button>
            <Button type="submit">{editing ? "Guardar" : "Crear"}</Button>
          </div>
        </form>
      </Dialog>

      <ConfirmDialog
        open={deleteId !== null}
        title="Eliminar ingreso"
        description="Esta accion no se puede deshacer."
        onConfirm={() => deleteId && deleteMut.mutate(deleteId)}
        onCancel={() => setDeleteId(null)}
      />
    </div>
  )
}
