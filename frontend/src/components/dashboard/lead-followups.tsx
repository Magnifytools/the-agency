import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Target } from "lucide-react"
import { Link } from "react-router-dom"

interface LeadReminder {
  id: number
  company_name: string
  contact_name: string | null
  days_until_followup: number
  status: string
  next_followup_notes: string | null
}

interface LeadFollowupsProps {
  reminders: LeadReminder[]
}

export function LeadFollowups({ reminders }: LeadFollowupsProps) {
  if (!reminders || reminders.length === 0) return null

  return (
    <Card className="border-brand/20">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <Target className="w-4 h-4 text-brand" />
            Seguimientos de leads ({reminders.length})
          </CardTitle>
          <Link to="/leads">
            <Button variant="outline" size="sm">Ver pipeline</Button>
          </Link>
        </div>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Empresa</TableHead>
              <TableHead>Contacto</TableHead>
              <TableHead>Followup</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead>Notas</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {reminders.map((r) => (
              <TableRow key={r.id}>
                <TableCell>
                  <Link to={`/leads/${r.id}`} className="font-medium text-brand hover:underline">
                    {r.company_name}
                  </Link>
                </TableCell>
                <TableCell>{r.contact_name || "-"}</TableCell>
                <TableCell>
                  <span
                    className={
                      r.days_until_followup < 0
                        ? "text-red-400 font-bold"
                        : r.days_until_followup === 0
                          ? "text-yellow-400 font-bold"
                          : ""
                    }
                  >
                    {r.days_until_followup < 0
                      ? `${Math.abs(r.days_until_followup)}d atrasado`
                      : r.days_until_followup === 0
                        ? "Hoy"
                        : `En ${r.days_until_followup}d`}
                  </span>
                </TableCell>
                <TableCell>
                  <Badge variant="secondary" className="text-xs">{r.status}</Badge>
                </TableCell>
                <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">
                  {r.next_followup_notes || "-"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
