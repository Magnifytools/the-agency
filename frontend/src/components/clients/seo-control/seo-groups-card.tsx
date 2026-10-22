import type { ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { FolderTree } from "lucide-react"
import { clientSeoApi } from "@/lib/api"
import { clientSeoKeys } from "@/lib/query-keys"
import type { SeoWindowDays } from "@/lib/types"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { SeoSectionsTable } from "./seo-sections-table"

interface Props {
  clientId: number
  days: SeoWindowDays
  selected: string | null
  onSelect: (group: string | null) => void
  actions?: ReactNode
  canEdit: boolean
  /** Abre la Configuración del cliente, donde se editan los grupos. */
  onOpenSettings?: () => void
}

/**
 * Grupos de URL propios del cliente (Configuración → Grupos de URL). Cada
 * página cuenta en el primer grupo que la acepta; el resto, "Sin grupo".
 */
export function SeoGroupsCard({ clientId, days, selected, onSelect, actions, canEdit, onOpenSettings }: Props) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: clientSeoKeys.groups(clientId, days),
    queryFn: () => clientSeoApi.groups(clientId, days),
    staleTime: 10 * 60_000,
  })

  if (data && data.status === "ok" && data.configured > 0) {
    return (
      <SeoSectionsTable
        sections={data.groups}
        selected={selected}
        onSelect={onSelect}
        title="Grupos de URL"
        hint="Cada página cuenta en el primer grupo que la acepta. Pulsa un grupo para ver sus páginas abajo."
        emptyText="Sin páginas con impresiones en la ventana."
        columnLabel="Grupo"
        actions={actions}
      />
    )
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base"><FolderTree className="h-4 w-4" /> Grupos de URL</CardTitle>
          {actions}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Cargando…</p>
        ) : isError || !data ? (
          <p className="text-sm text-muted-foreground">{getErrorMessage(error, "No se pudieron cargar los grupos.")}</p>
        ) : (
          <>
            <p className="text-sm text-muted-foreground">
              Este cliente no tiene grupos de URL. Agrupa sus páginas con reglas propias (empieza por, contiene o regex).
            </p>
            {canEdit && onOpenSettings ? (
              <Button size="sm" onClick={onOpenSettings}>Crear grupos en Configuración</Button>
            ) : (
              <p className="text-xs text-muted-foreground">Quien puede editar el cliente los crea en su Configuración.</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
