import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { dailysApi } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ClipboardCheck, Check, X } from "lucide-react"
import { cn } from "@/lib/utils"

export function DeberesWidget({ userId }: { userId: number }) {
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10)
  const [dismissed, setDismissed] = useState<Set<number>>(new Set())
  const [completed, setCompleted] = useState<Set<number>>(new Set())

  const { data: yesterdayDailys } = useQuery({
    queryKey: ["daily-yesterday", userId, yesterday],
    queryFn: () => dailysApi.list({ user_id: userId, date_from: yesterday, date_to: yesterday, limit: 1 }),
  })
  const deberes = yesterdayDailys?.[0]?.parsed_data?.tomorrow ?? []

  const visible = deberes.filter((_, i) => !dismissed.has(i))
  if (visible.length === 0) return null

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
          {deberes.map((item, i) => {
            if (dismissed.has(i)) return null
            const done = completed.has(i)
            return (
              <li key={i} className="flex items-center gap-2 text-sm group">
                <button
                  onClick={() => setCompleted(prev => {
                    const next = new Set(prev)
                    done ? next.delete(i) : next.add(i)
                    return next
                  })}
                  className={cn(
                    "shrink-0 w-5 h-5 rounded border flex items-center justify-center transition-colors",
                    done
                      ? "bg-green-600 border-green-500 text-white"
                      : "border-amber-500/40 hover:border-amber-400 text-transparent hover:text-amber-400"
                  )}
                >
                  <Check className="h-3 w-3" />
                </button>
                <span className={cn("flex-1", done && "line-through text-muted-foreground")}>{item}</span>
                <button
                  onClick={() => setDismissed(prev => new Set(prev).add(i))}
                  className="shrink-0 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-opacity"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </li>
            )
          })}
        </ul>
      </CardContent>
    </Card>
  )
}
