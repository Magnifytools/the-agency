import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { clientsApi } from "@/lib/api"
import type { Client } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { BarChart3, Search, Save } from "lucide-react"
import { getErrorMessage } from "@/lib/utils"

interface Props {
  client: Client
}

export function ClientSettingsTab({ client }: Props) {
  const qc = useQueryClient()
  const [ga4, setGa4] = useState(client.ga4_property_id ?? "")
  const [gsc, setGsc] = useState(client.gsc_url ?? "")

  const isDirty = ga4 !== (client.ga4_property_id ?? "") || gsc !== (client.gsc_url ?? "")

  const updateMut = useMutation({
    mutationFn: () =>
      clientsApi.update(client.id, {
        ga4_property_id: ga4.trim() || null,
        gsc_url: gsc.trim() || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client-summary", client.id] })
      toast.success("Ajustes guardados")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    updateMut.mutate()
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BarChart3 className="h-4 w-4" /> Analytics y Search Console
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label className="flex items-center gap-1.5">
                  <BarChart3 className="h-3.5 w-3.5 text-muted-foreground" />
                  GA4 Property ID
                </Label>
                <Input
                  value={ga4}
                  onChange={(e) => setGa4(e.target.value)}
                  placeholder="123456789"
                  className="mt-1"
                />
                <p className="text-[11px] text-muted-foreground mt-1">
                  ID numerico de la propiedad de Google Analytics 4
                </p>
              </div>
              <div>
                <Label className="flex items-center gap-1.5">
                  <Search className="h-3.5 w-3.5 text-muted-foreground" />
                  Google Search Console URL
                </Label>
                <Input
                  value={gsc}
                  onChange={(e) => setGsc(e.target.value)}
                  placeholder="https://ejemplo.com"
                  className="mt-1"
                />
                <p className="text-[11px] text-muted-foreground mt-1">
                  URL de la propiedad en Search Console
                </p>
              </div>
            </div>
            <div className="flex justify-end">
              <Button type="submit" disabled={!isDirty || updateMut.isPending} size="sm">
                <Save className="h-4 w-4 mr-1" />
                {updateMut.isPending ? "Guardando..." : "Guardar"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
