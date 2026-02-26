import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { InfoTooltip } from "@/components/ui/tooltip"

interface TeamMember {
  user_id: number
  full_name: string
  hourly_rate: number | null
  hours_this_month: number
  cost: number
  task_count: number
  clients_touched: number
}

interface TeamSummaryTableProps {
  team: TeamMember[]
}

export function TeamSummaryTable({ team }: TeamSummaryTableProps) {
  if (!team || team.length === 0) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Resumen del equipo</CardTitle>
      </CardHeader>
      <CardContent className="pt-4">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Miembro</TableHead>
              <TableHead>
                <span className="inline-flex items-center gap-1">
                  Tarifa/h <InfoTooltip content="Tarifa por hora configurada para este miembro." />
                </span>
              </TableHead>
              <TableHead>
                <span className="inline-flex items-center gap-1">
                  Horas mes <InfoTooltip content="Total horas registradas este mes." />
                </span>
              </TableHead>
              <TableHead>
                <span className="inline-flex items-center gap-1">
                  Coste <InfoTooltip content="Horas x Tarifa/h." />
                </span>
              </TableHead>
              <TableHead>Tareas</TableHead>
              <TableHead>
                <span className="inline-flex items-center gap-1">
                  Clientes <InfoTooltip content="Nº clientes distintos en los que ha trabajado este mes." />
                </span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {team.map((m) => (
              <TableRow key={m.user_id}>
                <TableCell className="font-medium">{m.full_name}</TableCell>
                <TableCell className="mono">{m.hourly_rate != null ? `${m.hourly_rate}€` : "-"}</TableCell>
                <TableCell className="mono">{m.hours_this_month}h</TableCell>
                <TableCell className="mono">{m.cost.toLocaleString("es-ES")}€</TableCell>
                <TableCell className="mono">{m.task_count}</TableCell>
                <TableCell className="mono">{m.clients_touched}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
