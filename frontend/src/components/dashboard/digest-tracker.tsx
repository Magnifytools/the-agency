import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Newspaper } from "lucide-react"
import { Link } from "react-router-dom"

interface DigestTrackerProps {
  clientsMissing: { id: number; name: string }[]
}

export function DigestTracker({ clientsMissing }: DigestTrackerProps) {
  if (clientsMissing.length === 0) return null

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <Newspaper className="w-4 h-4" />
            Digests pendientes ({clientsMissing.length})
          </CardTitle>
          <Link to="/digests">
            <Button variant="outline" size="sm">Ver digests</Button>
          </Link>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-2">
          {clientsMissing.map((c) => (
            <Badge key={c.id} variant="secondary">{c.name}</Badge>
          ))}
        </div>
        <p className="text-xs text-muted-foreground mt-3">
          Estos clientes no tienen digest generado esta semana.
        </p>
      </CardContent>
    </Card>
  )
}
