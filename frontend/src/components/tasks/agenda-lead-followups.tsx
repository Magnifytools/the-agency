import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Target } from "lucide-react"
import { leadsApi } from "@/lib/api"
import { formatCivilDate } from "@/lib/dates"
import { cn } from "@/lib/utils"
import { Card, CardContent } from "@/components/ui/card"

/**
 * Mi agenda: los seguimientos de lead que tocan hasta hoy (los míos; un admin
 * ve también los que no lleva nadie). Se resuelven en la ficha del lead,
 * poniendo el siguiente seguimiento o cerrándolo. Sin ninguno, no se pinta.
 */
export function AgendaLeadFollowups({ today, userId }: { today: string; userId: number | undefined }) {
  const { data: items = [] } = useQuery({
    queryKey: ["leads", "agenda", today, userId],
    queryFn: () => leadsApi.agenda(today),
    enabled: userId !== undefined,
  })
  if (items.length === 0) return null

  return (
    <Card>
      <CardContent className="p-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Target className="h-4 w-4" /> Seguimientos comerciales
          <span className="text-muted-foreground font-normal">({items.length})</span>
        </h2>
        <ul className="mt-2 divide-y divide-border">
          {items.map((lead) => {
            const late = lead.days_until_followup < 0
            return (
              <li key={lead.id} className="flex items-start gap-3 py-2">
                <div className="min-w-0 flex-1">
                  <Link to={`/leads/${lead.id}`} className="text-sm font-medium hover:underline">{lead.company_name}</Link>
                  {lead.next_followup_notes && <p className="text-xs text-muted-foreground line-clamp-2">{lead.next_followup_notes}</p>}
                  {lead.assigned_user_name === null && <p className="text-xs text-muted-foreground">Sin asignar</p>}
                </div>
                {lead.next_followup_date && (
                  <span className={cn("shrink-0 text-xs", late ? "text-destructive font-medium" : "text-muted-foreground")}>
                    {lead.next_followup_date === today ? "Hoy" : formatCivilDate(lead.next_followup_date, { day: "numeric", month: "short" })}
                  </span>
                )}
              </li>
            )
          })}
        </ul>
      </CardContent>
    </Card>
  )
}
