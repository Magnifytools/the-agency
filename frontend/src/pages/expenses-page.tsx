import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { financeExpensesApi, financeExpenseCategoriesApi } from "@/lib/api"
import type { Expense, ExpenseCreate } from "@/lib/types"
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

const fmt = (n: number) => n.toLocaleString("es-ES", { style: "currency", currency: "EUR" })

export default function ExpensesPage() {
  const qc = useQueryClient()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Expense | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [filters, setFilters] = useState<{ category_id?: number; is_recurring?: boolean }>({})

  const { data: items = [], isLoading } = useQuery({
    queryKey: ["finance-expenses", filters],
    queryFn: () => financeExpensesApi.list(filters),
  })

  const { data: categories = [] } = useQuery({
    queryKey: ["expense-categories"],
    queryFn: () => financeExpenseCategoriesApi.list(),
  })

  const createMut = useMutation({
    mutationFn: (data: ExpenseCreate) => financeExpensesApi.create(data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["finance-expenses"] }); setDialogOpen(false); setEditing(null); toast.success("Gasto creado") },
    onError: () => toast.error("Error al crear"),
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ExpenseCreate> }) => financeExpensesApi.update(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["finance-expenses"] }); setDialogOpen(false); setEditing(null); toast.success("Gasto actualizado") },
    onError: () => toast.error("Error al actualizar"),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => financeExpensesApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["finance-expenses"] }); setDeleteId(null); toast.success("Gasto eliminado") },
  })

  const total = items.reduce((s, i) => s + i.amount, 0)
  const recurring = items.filter(i => i.is_recurring).reduce((s, i) => s + i.amount, 0)

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    const data: ExpenseCreate = {
      date: fd.get("date") as string,
      description: fd.get("description") as string,
      amount: parseFloat(fd.get("amount") as string) || 0,
      category_id: fd.get("category_id") ? parseInt(fd.get("category_id") as string) : undefined,
      is_recurring: fd.get("is_recurring") === "true",
      recurrence_period: (fd.get("recurrence_period") as string) || "",
      vat_rate: parseFloat(fd.get("vat_rate") as string) || 21,
      vat_amount: parseFloat(fd.get("vat_amount") as string) || 0,
      is_deductible: fd.get("is_deductible") !== "false",
      supplier: (fd.get("supplier") as string) || "",
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
          <h1 className="text-2xl font-bold">Gastos</h1>
          <p className="text-muted-foreground">Total: {fmt(total)} | Recurrentes: {fmt(recurring)} ({items.length} registros)</p>
        </div>
        <Button onClick={() => { setEditing(null); setDialogOpen(true) }}><Plus className="h-4 w-4 mr-1" />Nuevo gasto</Button>
      </div>

      <div className="flex gap-2">
        <Select value={filters.category_id?.toString() || ""} onChange={(e) => setFilters(f => ({ ...f, category_id: e.target.value ? parseInt(e.target.value) : undefined }))}>
          <option value="">Todas las categorias</option>
          {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
      </div>

      {isLoading ? <p>Cargando...</p> : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Fecha</TableHead>
                <TableHead>Descripcion</TableHead>
                <TableHead>Categoria</TableHead>
                <TableHead>Proveedor</TableHead>
                <TableHead className="text-right">Importe</TableHead>
                <TableHead>Tipo</TableHead>
                <TableHead className="w-20"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map(item => (
                <TableRow key={item.id}>
                  <TableCell>{item.date}</TableCell>
                  <TableCell>{item.description}</TableCell>
                  <TableCell>{item.category_name || "-"}</TableCell>
                  <TableCell>{item.supplier || "-"}</TableCell>
                  <TableCell className="text-right font-mono">{fmt(item.amount)}</TableCell>
                  <TableCell>
                    {item.is_recurring && <Badge variant="secondary">Recurrente</Badge>}
                    {item.is_deductible && <Badge variant="success" className="ml-1">Deducible</Badge>}
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="sm" onClick={() => { setEditing(item); setDialogOpen(true) }}><Pencil className="h-3.5 w-3.5" /></Button>
                      <Button variant="ghost" size="sm" onClick={() => setDeleteId(item.id)}><Trash2 className="h-3.5 w-3.5" /></Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {items.length === 0 && <TableRow><TableCell colSpan={7} className="text-center text-muted-foreground">Sin gastos</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={() => { setDialogOpen(false); setEditing(null) }}>
        <DialogHeader><DialogTitle>{editing ? "Editar gasto" : "Nuevo gasto"}</DialogTitle></DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div><Label>Fecha</Label><Input name="date" type="date" defaultValue={editing?.date || new Date().toISOString().slice(0, 10)} required /></div>
            <div><Label>Importe</Label><Input name="amount" type="number" step="0.01" defaultValue={editing?.amount || ""} required /></div>
          </div>
          <div><Label>Descripcion</Label><Input name="description" defaultValue={editing?.description || ""} required /></div>
          <div className="grid grid-cols-2 gap-4">
            <div><Label>Categoria</Label>
              <Select name="category_id" defaultValue={editing?.category_id?.toString() || ""}>
                <option value="">Sin categoria</option>
                {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </div>
            <div><Label>Proveedor</Label><Input name="supplier" defaultValue={editing?.supplier || ""} /></div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div><Label>Recurrente</Label>
              <Select name="is_recurring" defaultValue={editing?.is_recurring ? "true" : "false"}>
                <option value="false">No</option>
                <option value="true">Si</option>
              </Select>
            </div>
            <div><Label>Periodo</Label>
              <Select name="recurrence_period" defaultValue={editing?.recurrence_period || ""}>
                <option value="">-</option>
                <option value="mensual">Mensual</option>
                <option value="trimestral">Trimestral</option>
                <option value="anual">Anual</option>
              </Select>
            </div>
            <div><Label>Deducible</Label>
              <Select name="is_deductible" defaultValue={editing?.is_deductible === false ? "false" : "true"}>
                <option value="true">Si</option>
                <option value="false">No</option>
              </Select>
            </div>
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
        title="Eliminar gasto"
        description="Esta accion no se puede deshacer."
        onConfirm={() => deleteId && deleteMut.mutate(deleteId)}
        onOpenChange={() => setDeleteId(null)}
      />
    </div>
  )
}
