import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { financeSyncApi } from "@/lib/api"
import type { CsvPreviewResponse } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Card } from "@/components/ui/card"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Upload, FileSpreadsheet } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

export default function ImportPage() {
  const qc = useQueryClient()
  const [step, setStep] = useState<"upload" | "map" | "done">("upload")
  const [csvContent, setCsvContent] = useState("")
  const [preview, setPreview] = useState<CsvPreviewResponse | null>(null)
  const [target, setTarget] = useState<"expenses" | "income">("expenses")
  const [mapping, setMapping] = useState<Record<string, string>>({})

  const { data: logs = [] } = useQuery({
    queryKey: ["sync-logs"],
    queryFn: () => financeSyncApi.logs(),
  })

  const previewMut = useMutation({
    mutationFn: (content: string) => financeSyncApi.preview(content),
    onSuccess: (data) => {
      setPreview(data)
      // Auto-detect mapping
      const autoMap: Record<string, string> = {}
      for (const header of data.headers) {
        const h = header.toLowerCase()
        if (h.includes("fecha") || h.includes("date")) autoMap["date"] = header
        else if (h.includes("importe") || h.includes("amount") || h.includes("cantidad")) autoMap["amount"] = header
        else if (h.includes("descripcion") || h.includes("concepto") || h.includes("description")) autoMap["description"] = header
      }
      setMapping(autoMap)
      setStep("map")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al procesar CSV")),
  })

  const importMut = useMutation({
    mutationFn: () => financeSyncApi.import({
      content: csvContent,
      target,
      mapping,
      delimiter: preview?.detected_delimiter || ",",
    }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["sync-logs"] })
      toast.success(`Importados: ${data.records_imported} de ${data.records_processed}`)
      if (data.errors.length > 0) {
        toast.warning(`${data.records_skipped} registros con errores`)
      }
      setStep("done")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al importar")),
  })

  function handleFileRead(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      const content = ev.target?.result as string
      setCsvContent(content)
      previewMut.mutate(content)
    }
    reader.readAsText(file)
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Importar CSV</h1>
        <p className="text-muted-foreground">Importa ingresos o gastos desde un archivo CSV</p>
      </div>

      {step === "upload" && (
        <Card className="p-8 text-center space-y-4">
          <FileSpreadsheet className="h-12 w-12 mx-auto text-muted-foreground" />
          <p>Selecciona un archivo CSV para importar</p>
          <div className="flex justify-center gap-4">
            <div>
              <Label>Tipo</Label>
              <Select value={target} onChange={(e) => setTarget(e.target.value as "expenses" | "income")}>
                <option value="expenses">Gastos</option>
                <option value="income">Ingresos</option>
              </Select>
            </div>
          </div>
          <div>
            <label className="inline-flex items-center gap-2 cursor-pointer px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90">
              <Upload className="h-4 w-4" />
              Seleccionar archivo
              <input type="file" accept=".csv,.txt" className="hidden" onChange={handleFileRead} />
            </label>
          </div>
        </Card>
      )}

      {step === "map" && preview && (
        <div className="space-y-4">
          <Card className="p-4">
            <p className="font-medium mb-2">Preview ({preview.total_rows} filas, delimitador: "{preview.detected_delimiter}")</p>
            <div className="overflow-x-auto max-h-60">
              <Table>
                <TableHeader>
                  <TableRow>
                    {preview.headers.map(h => <TableHead key={h}>{h}</TableHead>)}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {preview.rows.slice(0, 5).map((row, i) => (
                    <TableRow key={i}>
                      {row.map((cell, j) => <TableCell key={j}>{cell}</TableCell>)}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>

          <Card className="p-4 space-y-3">
            <p className="font-medium">Mapeo de columnas</p>
            <div className="grid grid-cols-3 gap-4">
              {["date", "amount", "description"].map(field => (
                <div key={field}>
                  <Label>{field === "date" ? "Fecha" : field === "amount" ? "Importe" : "Descripcion"}</Label>
                  <Select value={mapping[field] || ""} onChange={(e) => setMapping(m => ({ ...m, [field]: e.target.value }))}>
                    <option value="">-- Seleccionar --</option>
                    {preview.headers.map(h => <option key={h} value={h}>{h}</option>)}
                  </Select>
                </div>
              ))}
            </div>
          </Card>

          <div className="flex gap-2">
            <Button variant="outline" onClick={() => { setStep("upload"); setPreview(null) }}>Volver</Button>
            <Button onClick={() => importMut.mutate()} disabled={!mapping.date || !mapping.amount || importMut.isPending}>
              Importar {target === "expenses" ? "gastos" : "ingresos"}
            </Button>
          </div>
        </div>
      )}

      {step === "done" && (
        <Card className="p-8 text-center space-y-4">
          <p className="text-lg font-medium text-green-600">Importacion completada</p>
          <Button onClick={() => { setStep("upload"); setPreview(null); setCsvContent("") }}>Nueva importacion</Button>
        </Card>
      )}

      {logs.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3">Historial de importaciones</h2>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Fecha</TableHead>
                <TableHead>Fuente</TableHead>
                <TableHead>Procesados</TableHead>
                <TableHead>Importados</TableHead>
                <TableHead>Omitidos</TableHead>
                <TableHead>Estado</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {logs.map(log => (
                <TableRow key={log.id}>
                  <TableCell>{new Date(log.created_at).toLocaleDateString("es-ES")}</TableCell>
                  <TableCell>{log.source}</TableCell>
                  <TableCell>{log.records_processed}</TableCell>
                  <TableCell>{log.records_imported}</TableCell>
                  <TableCell>{log.records_skipped}</TableCell>
                  <TableCell>{log.status}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
