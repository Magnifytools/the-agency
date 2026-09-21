import { Badge } from "@/components/ui/badge"

export function InvoiceStatusBadge({ status }: { status: string | null }) {
  const states: Record<string, { label: string; variant: "success" | "warning" | "destructive" | "secondary" }> = {
    paid: { label: "Pagada", variant: "success" },
    pending: { label: "Pendiente", variant: "warning" },
    overdue: { label: "Vencida", variant: "destructive" },
    unknown: { label: "Sin confirmar", variant: "secondary" },
  }
  const { label, variant } = states[status ?? ""] ?? { label: "Sin confirmar", variant: "secondary" as const }
  return <Badge variant={variant}>{label}</Badge>
}
