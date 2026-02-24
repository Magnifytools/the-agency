import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Button } from "@/components/ui/button"
import { billingApi } from "@/lib/api"

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

  const { data } = useQuery({
    queryKey: ["billing-json", year, month],
    queryFn: () => billingApi.preview({ year, month }) as Promise<BillingRow[]>,
  })

  const downloadCsv = () => {
    const url = `/api/billing/export?format=csv&year=${year}&month=${month}`
    window.location.href = url
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold uppercase tracking-wide">Export facturación</h2>
        <div className="flex gap-2">
          <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="border border-border rounded-md px-3 py-2 text-sm bg-background">
            {Array.from({ length: 12 }).map((_, i) => (
              <option key={i + 1} value={i + 1}>{i + 1}</option>
            ))}
          </select>
          <select value={year} onChange={(e) => setYear(Number(e.target.value))} className="border border-border rounded-md px-3 py-2 text-sm bg-background">
            {[now.getFullYear() - 1, now.getFullYear(), now.getFullYear() + 1].map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
          <Button onClick={downloadCsv}>Descargar CSV</Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Vista previa</CardTitle>
        </CardHeader>
        <CardContent className="pt-4">
          {!data ? (
            <div className="text-sm text-muted-foreground">Cargando...</div>
          ) : data.length === 0 ? (
            <div className="text-sm text-muted-foreground">Sin datos para este periodo.</div>
          ) : (
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
          )}
        </CardContent>
      </Card>
    </div>
  )
}
