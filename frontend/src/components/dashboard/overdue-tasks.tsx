import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import type { Task } from "@/lib/types"
import { civilDayDifference, formatCivilDate } from "@/lib/dates"
import { useBusinessDate } from "@/hooks/use-business-date"

interface OverdueTasksProps {
  tasks: Task[]
  showAssigned?: boolean
  title?: string
}

export function OverdueTasks({ tasks, showAssigned = false, title }: OverdueTasksProps) {
  // Filter out tasks due today or in the future — only truly overdue
  const todayStr = useBusinessDate()
  const trulyOverdue = (tasks || []).filter(
    (t) => t.due_date && t.due_date < todayStr
  )
  if (trulyOverdue.length === 0) return null

  return (
    <Card className="border-red-500/30 bg-red-500/5">
      <CardHeader className="pb-2">
        <CardTitle className="text-red-400 text-sm">
          {title || `Tareas vencidas (${trulyOverdue.length})`}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tarea</TableHead>
              <TableHead>Cliente</TableHead>
              {showAssigned && <TableHead>Asignado</TableHead>}
              <TableHead>Fecha limite</TableHead>
              <TableHead>Dias atrasada</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {trulyOverdue.map((t) => {
              const daysOverdue = t.due_date
                ? Math.max(1, civilDayDifference(t.due_date, todayStr))
                : 1
              return (
                <TableRow key={t.id}>
                  <TableCell className="font-medium">{t.title}</TableCell>
                  <TableCell>{t.client_name || "-"}</TableCell>
                  {showAssigned && <TableCell>{t.assigned_user_name || "-"}</TableCell>}
                  <TableCell className="mono">
                    {t.due_date ? formatCivilDate(t.due_date) : "-"}
                  </TableCell>
                  <TableCell className="text-red-400 font-bold">{daysOverdue}d</TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
