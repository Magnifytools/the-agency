import { useQuery } from "@tanstack/react-query"
import { dailysApi } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ClipboardCheck } from "lucide-react"

export function DeberesWidget({ userId }: { userId: number }) {
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10)

  const { data: yesterdayDailys } = useQuery({
    queryKey: ["daily-yesterday", userId, yesterday],
    queryFn: () => dailysApi.list({ user_id: userId, date_from: yesterday, date_to: yesterday, limit: 1 }),
  })
  const deberes = yesterdayDailys?.[0]?.parsed_data?.tomorrow ?? []

  if (deberes.length === 0) return null

  return (
    <Card className="border-amber-500/20 bg-amber-500/5">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <ClipboardCheck className="h-4 w-4 text-amber-400" />
          Deberes de hoy
          <span className="text-xs text-muted-foreground font-normal">(del daily de ayer)</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-1.5">
          {deberes.map((item, i) => (
            <li key={i} className="flex items-start gap-2 text-sm">
              <span className="text-amber-400 mt-0.5 shrink-0">→</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
