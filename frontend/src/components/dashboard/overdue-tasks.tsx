import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import type { Task } from "@/lib/types"

interface OverdueTasksProps {
  tasks: Task[]
  showAssigned?: boolean
  title?: string
}

export function OverdueTasks({ tasks, showAssigned = false, title }: OverdueTasksProps) {
  if (!tasks || tasks.length === 0) return null

  return (
    <Card className="border-red-500/30 bg-red-500/5">
      <CardHeader className="pb-2">
        <CardTitle className="text-red-400 text-sm">
          {title || `Tareas vencidas (${tasks.length})`}
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
            {tasks.map((t) => {
              const daysOverdue = t.due_date
                ? Math.floor((Date.now() - new Date(t.due_date).getTime()) / 86400000)
                : 0
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
