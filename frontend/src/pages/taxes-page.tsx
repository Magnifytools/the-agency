import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { financeTaxesApi } from "@/lib/api"
import type { Tax, TaxCreate } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Plus, Pencil, Trash2, Calculator } from "lucide-react"
import { toast } from "sonner"

const fmt = (n: number) => n.toLocaleString("es-ES", { style: "currency", currency: "EUR" })
const currentYear = new Date().getFullYear()

const statusBadge = (status: string) => {
  const map: Record<string, { label: string; variant: "success" | "warning" | "secondary" | "destructive" }> = {
    pendiente: { label: "Pendiente", variant: "warning" },
    pagado: { label: "Pagado", variant: "success" },
    aplazado: { label: "Aplazado", variant: "secondary" },
    sin_calcular: { label: "Sin calcular", variant: "destructive" },
  }
  const m = map[status] || { label: status, variant: "secondary" as const }
  return <Badge variant={m.variant}>{m.label}</Badge>
}

export default function TaxesPage() {
  const qc = useQueryClient()
  const [year, setYear] = useState(currentYear)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Tax | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)

  const { data: taxes = [], isLoading } = useQuery({
    queryKey: ["finance-taxes", year],
    queryFn: () => financeTaxesApi.list({ year }),
  })

  const { data: calendar = [] } = useQuery({
    queryKey: ["tax-calendar", year],
    queryFn: () => financeTaxesApi.calendar(year),
  })

  const { data: summary } = useQuery({
    queryKey: ["tax-summary", year],
    queryFn: () => financeTaxesApi.summary(year),
  })

  const calcMut = useMutation({
    mutationFn: () => financeTaxesApi.calculate(year),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["finance-taxes"] })
      qc.invalidateQueries({ queryKey: ["tax-calendar"] })
      qc.invalidateQueries({ queryKey: ["tax-summary"] })
      toast.success("Impuestos calculados")
    },
    onError: () => toast.error("Error al calcular"),
  })

  const createMut = useMutation({
    mutationFn: (data: TaxCreate) => financeTaxesApi.create(data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["finance-taxes"] }); setDialogOpen(false); setEditing(null); toast.success("Impuesto creado") },
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<TaxCreate> }) => financeTaxesApi.update(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["finance-taxes"] }); setDialogOpen(false); setEditing(null); toast.success("Impuesto actualizado") },
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => financeTaxesApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["finance-taxes"] }); setDeleteId(null); toast.success("Impuesto eliminado") },
  })

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    const data: TaxCreate = {
      name: fd.get("name") as string,
      model: (fd.get("model") as string) || "",
      period: (fd.get("period") as string) || "",
      year: parseInt(fd.get("year") as string) || currentYear,
      base_amount: parseFloat(fd.get("base_amount") as string) || 0,
      tax_rate: parseFloat(fd.get("tax_rate") as string) || 0,
      tax_amount: parseFloat(fd.get("tax_amount") as string) || 0,
      status: (fd.get("status") as string) || "pendiente",
      due_date: (fd.get("due_date") as string) || undefined,
    }
    if (editing) updateMut.mutate({ id: editing.id, data })
    else createMut.mutate(data)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Impuestos</h1>
          <p className="text-muted-foreground">Gestion fiscal - Ano {year}</p>
        </div>
        <div className="flex gap-2">
          <Select value={year.toString()} onChange={(e) => setYear(parseInt(e.target.value))}>
            {[currentYear - 1, currentYear, currentYear + 1].map(y => <option key={y} value={y}>{y}</option>)}
          </Select>
          <Button variant="outline" onClick={() => calcMut.mutate()} disabled={calcMut.isPending}>
            <Calculator className="h-4 w-4 mr-1" />Calcular
          </Button>
          <Button onClick={() => { setEditing(null); setDialogOpen(true) }}><Plus className="h-4 w-4 mr-1" />Manual</Button>
        </div>
      </div>

      {summary && (
        <div className="grid grid-cols-3 gap-4">
          <Card className="p-4">
            <p className="text-sm text-muted-foreground">Pendiente</p>
            <p className="text-2xl font-bold text-amber-600">{fmt(summary.total_pending)}</p>
          </Card>
          <Card className="p-4">
            <p className="text-sm text-muted-foreground">Pagado</p>
            <p className="text-2xl font-bold text-green-600">{fmt(summary.total_paid)}</p>
          </Card>
          <Card className="p-4">
            <p className="text-sm text-muted-foreground">Total</p>
            <p className="text-2xl font-bold">{fmt(summary.total)}</p>
          </Card>
        </div>
      )}

      <div>
        <h2 className="text-lg font-semibold mb-3">Calendario fiscal</h2>
        <div className="grid gap-2">
          {calendar.map((item: Record<string, unknown>, i: number) => (
            <div key={i} className="flex items-center justify-between p-3 rounded-lg border">
              <div className="flex items-center gap-3">
                <Badge variant="secondary">{item.model as string}</Badge>
                <span className="font-medium">{item.description as string}</span>
                <span className="text-muted-foreground text-sm">{item.period as string}</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-sm">{item.due_date as string}</span>
                {item.tax_amount != null && <span className="font-mono">{fmt(item.tax_amount as number)}</span>}
                {statusBadge(item.status as string)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {isLoading ? <p>Cargando...</p> : (
        <div className="overflow-x-auto">
          <h2 className="text-lg font-semibold mb-3">Detalle</h2>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Modelo</TableHead>
                <TableHead>Periodo</TableHead>
                <TableHead>Nombre</TableHead>
                <TableHead className="text-right">Base</TableHead>
                <TableHead className="text-right">Tipo</TableHead>
                <TableHead className="text-right">Cuota</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Vencimiento</TableHead>
                <TableHead className="w-20"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {taxes.map(tax => (
                <TableRow key={tax.id}>
                  <TableCell><Badge variant="secondary">{tax.model}</Badge></TableCell>
                  <TableCell>{tax.period}</TableCell>
                  <TableCell>{tax.name}</TableCell>
                  <TableCell className="text-right font-mono">{fmt(tax.base_amount)}</TableCell>
                  <TableCell className="text-right">{tax.tax_rate}%</TableCell>
                  <TableCell className="text-right font-mono">{fmt(tax.tax_amount)}</TableCell>
                  <TableCell>{statusBadge(tax.status)}</TableCell>
                  <TableCell>{tax.due_date || "-"}</TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="sm" onClick={() => { setEditing(tax); setDialogOpen(true) }}><Pencil className="h-3.5 w-3.5" /></Button>
                      <Button variant="ghost" size="sm" onClick={() => setDeleteId(tax.id)}><Trash2 className="h-3.5 w-3.5" /></Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={dialogOpen} onClose={() => { setDialogOpen(false); setEditing(null) }}>
        <DialogHeader><DialogTitle>{editing ? "Editar impuesto" : "Nuevo impuesto"}</DialogTitle></DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div><Label>Nombre</Label><Input name="name" defaultValue={editing?.name || ""} required /></div>
          <div className="grid grid-cols-3 gap-4">
            <div><Label>Modelo</Label><Input name="model" defaultValue={editing?.model || ""} placeholder="303" /></div>
            <div><Label>Periodo</Label><Input name="period" defaultValue={editing?.period || ""} placeholder="Q1" /></div>
            <div><Label>Ano</Label><Input name="year" type="number" defaultValue={editing?.year || currentYear} /></div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div><Label>Base imponible</Label><Input name="base_amount" type="number" step="0.01" defaultValue={editing?.base_amount || 0} /></div>
            <div><Label>Tipo (%)</Label><Input name="tax_rate" type="number" step="0.01" defaultValue={editing?.tax_rate || 0} /></div>
            <div><Label>Cuota</Label><Input name="tax_amount" type="number" step="0.01" defaultValue={editing?.tax_amount || 0} /></div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div><Label>Estado</Label>
              <Select name="status" defaultValue={editing?.status || "pendiente"}>
                <option value="pendiente">Pendiente</option>
                <option value="pagado">Pagado</option>
                <option value="aplazado">Aplazado</option>
              </Select>
            </div>
            <div><Label>Vencimiento</Label><Input name="due_date" type="date" defaultValue={editing?.due_date || ""} /></div>
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => { setDialogOpen(false); setEditing(null) }}>Cancelar</Button>
            <Button type="submit">{editing ? "Guardar" : "Crear"}</Button>
          </div>
        </form>
      </Dialog>

      <ConfirmDialog open={deleteId !== null} title="Eliminar impuesto" description="Esta accion no se puede deshacer."
        onConfirm={() => deleteId && deleteMut.mutate(deleteId)} onCancel={() => setDeleteId(null)} />
    </div>
  )
}
