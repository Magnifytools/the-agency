import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

const CLOSE_ITEMS = [
  { key: "reviewed_numbers", label: "Revisar ingresos, gastos y cashflow del mes" },
  { key: "reviewed_margin", label: "Margen claro por cliente y global" },
  { key: "reviewed_cash_buffer", label: "Colchón de caja (≥ 3 meses)" },
  { key: "reviewed_reinvestment", label: "Plan de reinversión con ROI (captación/retención)" },
  { key: "reviewed_debt", label: "Líneas de crédito y deuda bajo control" },
  { key: "reviewed_taxes", label: "Impuestos y obligaciones fiscales al día" },
  { key: "reviewed_personal", label: "Nóminas y pagos personales revisados" },
]

interface MonthlyCloseChecklistProps {
  monthlyClose: Record<string, boolean | string | null>
  onUpdate: (payload: Record<string, boolean | string>) => void
  onExport: () => void
  isPending: boolean
}

export function MonthlyCloseChecklist({
  monthlyClose,
  onUpdate,
  onExport,
  isPending,
}: MonthlyCloseChecklistProps) {
  const doneCount = CLOSE_ITEMS.filter((item) => Boolean(monthlyClose[item.key])).length
  const totalCount = CLOSE_ITEMS.length

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Cierre mensual</span>
          <div className="flex items-center gap-2">
            <Badge variant={doneCount === totalCount ? "success" : "warning"}>
              {doneCount === totalCount ? "OK" : "Pendiente"}
            </Badge>
            <Button variant="outline" size="sm" onClick={onExport}>
              Exportar CSV
            </Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <div className="text-xs text-muted-foreground mb-1">Responsable</div>
            <input
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              type="text"
              defaultValue={String(monthlyClose.responsible_name || "")}
              onBlur={(e) => onUpdate({ responsible_name: e.target.value })}
            />
          </div>
          <div>
            <div className="text-xs text-muted-foreground mb-1">Notas del cierre</div>
            <textarea
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              rows={3}
              defaultValue={String(monthlyClose.notes || "")}
              onBlur={(e) => onUpdate({ notes: e.target.value })}
            />
          </div>
        </div>
        <div className="text-sm text-muted-foreground">
          Marca los checks para evitar las decisiones de riesgo más comunes.
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {CLOSE_ITEMS.map((item) => (
            <label key={item.key} className="flex items-start gap-2 rounded-lg border border-border p-3">
              <input
                type="checkbox"
                checked={Boolean(monthlyClose[item.key])}
                onChange={(e) => onUpdate({ [item.key]: e.target.checked })}
                className="mt-1"
              />
              <span className="text-sm">{item.label}</span>
            </label>
          ))}
        </div>
        <div className="flex items-center justify-between">
          <div className="text-xs text-muted-foreground">
            {doneCount} de {totalCount} completados
          </div>
          <Button
            variant="outline"
            onClick={() =>
              onUpdate({
                reviewed_numbers: true,
                reviewed_margin: true,
                reviewed_cash_buffer: true,
                reviewed_reinvestment: true,
                reviewed_debt: true,
                reviewed_taxes: true,
                reviewed_personal: true,
              })
            }
            disabled={isPending}
          >
            Marcar cierre completo
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
