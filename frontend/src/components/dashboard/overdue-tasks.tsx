import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import type { Task } from "@/lib/types"

interface OverdueTasksProps {
  tasks: Task[]
  showAssigned?: boolean
  title?: string
}

export function OverdueTasks({ tasks, showAssigned = false, title }: OverdueTasksProps) {
  // Filter out tasks due today or in the future — only truly overdue
  const todayStr = new Date().toISOString().split("T")[0]
  const trulyOverdue = (tasks || []).filter(
    (t) => t.due_date && t.due_date < todayStr
  )
  // eslint-disable-next-line react-hooks/purity -- Date.now() for computing days overdue is intentional
  const now = Date.now()
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
                ? Math.max(1, Math.floor((now - new Date(t.due_date).getTime()) / 86400000))
                : 1
              return (
                <TableRow key={t.id}>
                  <TableCell className="font-medium">{t.title}</TableCell>
                  <TableCell>{t.client_name || "-"}</TableCell>
                  {showAssigned && <TableCell>{t.assigned_user_name || "-"}</TableCell>}
                  <TableCell className="mono">
                    {t.due_date ? new Date(t.due_date).toLocaleDateString("es-ES") : "-"}
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
