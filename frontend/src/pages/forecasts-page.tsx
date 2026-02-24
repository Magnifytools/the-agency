import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { financeForecastsApi } from "@/lib/api"
import type { Forecast, ForecastCreate } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Card } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Plus, Pencil, Trash2, Sparkles } from "lucide-react"
import { toast } from "sonner"

const fmt = (n: number) => n.toLocaleString("es-ES", { style: "currency", currency: "EUR" })
const currentYear = new Date().getFullYear()

export default function ForecastsPage() {
  const qc = useQueryClient()
  const [year, setYear] = useState(currentYear)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Forecast | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)

  const { data: forecasts = [], isLoading } = useQuery({
    queryKey: ["finance-forecasts", year],
    queryFn: () => financeForecastsApi.list({ year }),
  })

  const { data: runway } = useQuery({
    queryKey: ["finance-runway"],
    queryFn: () => financeForecastsApi.runway(),
  })

  const { data: vsActual = [] } = useQuery({
    queryKey: ["finance-vs-actual", year],
    queryFn: () => financeForecastsApi.vsActual(year),
  })

  const generateMut = useMutation({
    mutationFn: () => financeForecastsApi.generate(6),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["finance-forecasts"] })
      qc.invalidateQueries({ queryKey: ["finance-vs-actual"] })
      toast.success("Previsiones generadas")
    },
    onError: () => toast.error("Error al generar"),
  })

  const createMut = useMutation({
    mutationFn: (data: ForecastCreate) => financeForecastsApi.create(data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["finance-forecasts"] }); setDialogOpen(false); setEditing(null); toast.success("Prevision creada") },
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ForecastCreate> }) => financeForecastsApi.update(id, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["finance-forecasts"] }); setDialogOpen(false); setEditing(null); toast.success("Prevision actualizada") },
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => financeForecastsApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["finance-forecasts"] }); setDeleteId(null); toast.success("Prevision eliminada") },
  })

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    const data: ForecastCreate = {
      month: (fd.get("month") as string) + "-01",
      projected_income: parseFloat(fd.get("projected_income") as string) || 0,
      projected_expenses: parseFloat(fd.get("projected_expenses") as string) || 0,
      projected_taxes: parseFloat(fd.get("projected_taxes") as string) || 0,
      projected_profit: parseFloat(fd.get("projected_profit") as string) || 0,
      confidence: parseFloat(fd.get("confidence") as string) || 0.5,
      notes: (fd.get("notes") as string) || "",
    }
    if (editing) updateMut.mutate({ id: editing.id, data })
    else createMut.mutate(data)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Previsiones</h1>
          <p className="text-muted-foreground">Proyecciones financieras y runway</p>
        </div>
        <div className="flex gap-2">
          <Select value={year.toString()} onChange={(e) => setYear(parseInt(e.target.value))}>
            {[currentYear - 1, currentYear, currentYear + 1].map(y => <option key={y} value={y}>{y}</option>)}
          </Select>
          <Button variant="outline" onClick={() => generateMut.mutate()} disabled={generateMut.isPending}>
            <Sparkles className="h-4 w-4 mr-1" />Generar
          </Button>
          <Button onClick={() => { setEditing(null); setDialogOpen(true) }}><Plus className="h-4 w-4 mr-1" />Manual</Button>
        </div>
      </div>

      {runway && (
        <div className="grid grid-cols-3 gap-4">
          <Card className="p-4">
            <p className="text-sm text-muted-foreground">Cash disponible</p>
            <p className="text-2xl font-bold">{fmt(runway.current_cash)}</p>
          </Card>
          <Card className="p-4">
            <p className="text-sm text-muted-foreground">Gasto mensual medio</p>
            <p className="text-2xl font-bold">{fmt(runway.avg_monthly_burn)}</p>
          </Card>
          <Card className="p-4">
            <p className="text-sm text-muted-foreground">Runway</p>
            <p className="text-2xl font-bold">{runway.runway_months} meses</p>
          </Card>
        </div>
      )}

      {vsActual.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3">Prevision vs Real</h2>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Mes</TableHead>
                  <TableHead className="text-right">Ingresos prev.</TableHead>
                  <TableHead className="text-right">Ingresos real</TableHead>
                  <TableHead className="text-right">Gastos prev.</TableHead>
                  <TableHead className="text-right">Gastos real</TableHead>
                  <TableHead className="text-right">Beneficio prev.</TableHead>
                  <TableHead className="text-right">Beneficio real</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {vsActual.map((row) => (
                  <TableRow key={row.month}>
                    <TableCell>{row.month}</TableCell>
                    <TableCell className="text-right font-mono">{fmt(row.projected_income)}</TableCell>
                    <TableCell className="text-right font-mono">{fmt(row.actual_income)}</TableCell>
                    <TableCell className="text-right font-mono">{fmt(row.projected_expenses)}</TableCell>
                    <TableCell className="text-right font-mono">{fmt(row.actual_expenses)}</TableCell>
                    <TableCell className="text-right font-mono">{fmt(row.projected_profit)}</TableCell>
                    <TableCell className={`text-right font-mono ${row.actual_profit < 0 ? "text-red-600" : ""}`}>{fmt(row.actual_profit)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      {isLoading ? <p>Cargando...</p> : (
        <div>
          <h2 className="text-lg font-semibold mb-3">Previsiones</h2>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Mes</TableHead>
                  <TableHead className="text-right">Ingresos</TableHead>
                  <TableHead className="text-right">Gastos</TableHead>
                  <TableHead className="text-right">Impuestos</TableHead>
                  <TableHead className="text-right">Beneficio</TableHead>
                  <TableHead className="text-right">Confianza</TableHead>
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {forecasts.map(f => (
                  <TableRow key={f.id}>
                    <TableCell>{f.month}</TableCell>
                    <TableCell className="text-right font-mono">{fmt(f.projected_income)}</TableCell>
                    <TableCell className="text-right font-mono">{fmt(f.projected_expenses)}</TableCell>
                    <TableCell className="text-right font-mono">{fmt(f.projected_taxes)}</TableCell>
                    <TableCell className={`text-right font-mono ${f.projected_profit < 0 ? "text-red-600" : ""}`}>{fmt(f.projected_profit)}</TableCell>
                    <TableCell className="text-right">{(f.confidence * 100).toFixed(0)}%</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button variant="ghost" size="sm" onClick={() => { setEditing(f); setDialogOpen(true) }}><Pencil className="h-3.5 w-3.5" /></Button>
                        <Button variant="ghost" size="sm" onClick={() => setDeleteId(f.id)}><Trash2 className="h-3.5 w-3.5" /></Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={() => { setDialogOpen(false); setEditing(null) }}>
        <DialogHeader><DialogTitle>{editing ? "Editar prevision" : "Nueva prevision"}</DialogTitle></DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div><Label>Mes</Label><Input name="month" type="month" defaultValue={editing?.month?.slice(0, 7) || ""} required /></div>
          <div className="grid grid-cols-2 gap-4">
            <div><Label>Ingresos previstos</Label><Input name="projected_income" type="number" step="0.01" defaultValue={editing?.projected_income || 0} /></div>
            <div><Label>Gastos previstos</Label><Input name="projected_expenses" type="number" step="0.01" defaultValue={editing?.projected_expenses || 0} /></div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div><Label>Impuestos previstos</Label><Input name="projected_taxes" type="number" step="0.01" defaultValue={editing?.projected_taxes || 0} /></div>
            <div><Label>Beneficio previsto</Label><Input name="projected_profit" type="number" step="0.01" defaultValue={editing?.projected_profit || 0} /></div>
          </div>
          <div><Label>Confianza (0-1)</Label><Input name="confidence" type="number" step="0.01" min="0" max="1" defaultValue={editing?.confidence ?? 0.5} /></div>
          <div><Label>Notas</Label><Input name="notes" defaultValue={editing?.notes || ""} /></div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => { setDialogOpen(false); setEditing(null) }}>Cancelar</Button>
            <Button type="submit">{editing ? "Guardar" : "Crear"}</Button>
          </div>
        </form>
      </Dialog>

      <ConfirmDialog open={deleteId !== null} title="Eliminar prevision" description="Esta accion no se puede deshacer."
        onConfirm={() => deleteId && deleteMut.mutate(deleteId)} onOpenChange={() => setDeleteId(null)} />
    </div>
  )
}
