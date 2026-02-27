import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { billingApi } from "@/lib/api"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

interface BillingRow {
  client_id: number
  client_name: string
  period: string
  hours: number
  cost: number
  budget: number
  margin: number
}

export default function BillingPage() {
  const now = new Date()
  const [year, setYear] = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["billing-json", year, month],
    queryFn: () => billingApi.preview({ year, month }) as Promise<BillingRow[]>,
  })

  const downloadCsv = async () => {
    try {
      const blob = await billingApi.exportCsv({ year, month })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `facturacion-${year}-${String(month).padStart(2, "0")}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast.error(getErrorMessage(err, "No se pudo descargar el CSV"))
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <h2 className="text-2xl font-bold uppercase tracking-wide flex items-center gap-2">Export facturación <Badge variant="warning" dot={false}>Beta</Badge></h2>
        <div className="flex flex-wrap gap-2">
          <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="border border-border rounded-md px-3 py-2 text-sm bg-background min-w-[90px]">
            {Array.from({ length: 12 }).map((_, i) => (
              <option key={i + 1} value={i + 1}>{i + 1}</option>
            ))}
          </select>
          <select value={year} onChange={(e) => setYear(Number(e.target.value))} className="border border-border rounded-md px-3 py-2 text-sm bg-background min-w-[100px]">
            {[now.getFullYear() - 1, now.getFullYear(), now.getFullYear() + 1].map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
          <Button onClick={downloadCsv} className="w-full sm:w-auto">Descargar CSV</Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Vista previa</CardTitle>
        </CardHeader>
        <CardContent className="pt-4">
          {isLoading ? (
            <div className="text-sm text-muted-foreground">Cargando...</div>
          ) : error ? (
            <div className="text-red-500 text-sm">Error al cargar datos. <button className="underline ml-1" onClick={() => refetch()}>Reintentar</button></div>
          ) : !data || data.length === 0 ? (
            <div className="text-sm text-muted-foreground">Sin datos para este periodo.</div>
          ) : (
            <>
              <div className="hidden md:block">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Cliente</TableHead>
                      <TableHead>Horas</TableHead>
                      <TableHead>Coste</TableHead>
                      <TableHead>Presupuesto</TableHead>
                      <TableHead>Margen</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.map((row) => (
                      <TableRow key={row.client_id}>
                        <TableCell className="font-medium">{row.client_name}</TableCell>
                        <TableCell className="mono">{row.hours}h</TableCell>
                        <TableCell className="mono">{row.cost.toFixed(2)}€</TableCell>
                        <TableCell className="mono">{row.budget.toFixed(2)}€</TableCell>
                        <TableCell className="mono">{row.margin.toFixed(2)}€</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <div className="md:hidden space-y-3">
                {data.map((row) => (
                  <div key={row.client_id} className="rounded-lg border border-border p-3 space-y-2">
                    <p className="font-medium text-sm">{row.client_name}</p>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <p className="mono">Horas: {row.hours}h</p>
                      <p className="mono">Coste: {row.cost.toFixed(2)}€</p>
                      <p className="mono">Presupuesto: {row.budget.toFixed(2)}€</p>
                      <p className="mono">Margen: {row.margin.toFixed(2)}€</p>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
