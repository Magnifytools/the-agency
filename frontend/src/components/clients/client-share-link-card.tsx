import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Copy, Link2 } from "lucide-react"
import { clientShareLinkApi, type ShareLinkStatus } from "@/lib/client-share-link-api"
import { getAgencyTimezone, parseApiInstant } from "@/lib/dates"
import { useAuth } from "@/context/auth-context"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"

interface Props {
  clientId: number
}

function formatInstant(value: string) {
  return parseApiInstant(value).toLocaleString("es-ES", {
    day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit",
    timeZone: getAgencyTimezone(),
  })
}

/**
 * Enlace de sólo lectura para el cliente: sus resúmenes entregados y su tráfico
 * de Google. El enlace completo sólo se conoce al crearlo (el servidor guarda
 * su hash), así que se enseña una vez y luego sólo "activo desde…".
 */
export function ClientShareLinkCard({ clientId }: Props) {
  const { hasPermission } = useAuth()
  // El enlace enseña resúmenes: para publicarlo hace falta poder leerlos.
  const canManage = hasPermission("clients", true) && hasPermission("digests")
  const qc = useQueryClient()
  const queryKey = ["client-share-link", clientId]
  const [freshUrl, setFreshUrl] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<"regenerate" | "revoke" | null>(null)

  const { data: status, isLoading } = useQuery({ queryKey, queryFn: () => clientShareLinkApi.status(clientId) })

  const createMut = useMutation({
    mutationFn: () => clientShareLinkApi.create(clientId),
    onSuccess: ({ path, ...next }) => {
      qc.setQueryData<ShareLinkStatus>(queryKey, next)
      setFreshUrl(`${window.location.origin}${path}`)
      toast.success("Enlace creado. Cópialo ahora: no se vuelve a mostrar.")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const revokeMut = useMutation({
    mutationFn: () => clientShareLinkApi.revoke(clientId),
    onSuccess: () => {
      setFreshUrl(null)
      void qc.invalidateQueries({ queryKey })
      toast.success("Enlace revocado. Ya no funciona.")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const copy = async () => {
    if (!freshUrl) return
    try {
      await navigator.clipboard.writeText(freshUrl)
      toast.success("Enlace copiado")
    } catch {
      toast.error("No se pudo copiar. Selecciónalo y cópialo a mano.")
    }
  }

  const busy = createMut.isPending || revokeMut.isPending

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Link2 className="h-4 w-4" /> Enlace para el cliente
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">
          Una página sin login con los resúmenes ya entregados y la evolución de su tráfico en Google.
          Nada de tareas ni notas internas.
        </p>

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Cargando…</p>
        ) : status?.active ? (
          <p role="status" className="text-sm">
            Activo desde el {formatInstant(status.created_at!)}
            {status.created_by_name && <> · lo creó {status.created_by_name}</>}
            <span className="block text-muted-foreground">
              {status.last_viewed_at ? `Última visita: ${formatInstant(status.last_viewed_at)}` : "Todavía no lo ha abierto nadie."}
            </span>
          </p>
        ) : (
          <p role="status" className="text-sm text-muted-foreground">No hay ningún enlace activo.</p>
        )}

        {freshUrl && (
          <div className="space-y-1">
            <div className="flex gap-2">
              <Input readOnly value={freshUrl} aria-label="Enlace para el cliente" onFocus={(e) => e.currentTarget.select()} className="mono text-xs" />
              <Button type="button" size="sm" variant="outline" onClick={copy}>
                <Copy className="h-4 w-4 mr-1" /> Copiar
              </Button>
            </div>
            <p className="text-[11px] text-amber-600">Cópialo ahora: por seguridad no se vuelve a mostrar. Si lo pierdes, regenera uno nuevo.</p>
          </div>
        )}

        {canManage && !isLoading && (
          <div className="flex flex-wrap gap-2">
            {status?.active ? (
              <>
                <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setConfirm("regenerate")}>Regenerar enlace</Button>
                <Button type="button" size="sm" variant="destructive" disabled={busy} onClick={() => setConfirm("revoke")}>Revocar</Button>
              </>
            ) : (
              <Button type="button" size="sm" disabled={busy} onClick={() => createMut.mutate()}>
                {createMut.isPending ? "Creando…" : "Crear enlace"}
              </Button>
            )}
          </div>
        )}
        {!canManage && (
          <p className="text-[11px] text-muted-foreground">Para crearlo o revocarlo hace falta poder editar clientes y leer resúmenes.</p>
        )}

        <ConfirmDialog
          open={confirm === "regenerate"}
          onOpenChange={(open) => !open && setConfirm(null)}
          title="¿Regenerar el enlace?"
          description="El enlace actual dejará de funcionar al momento. Tendrás que enviarle el nuevo al cliente."
          confirmLabel="Regenerar"
          onConfirm={() => createMut.mutate()}
        />
        <ConfirmDialog
          open={confirm === "revoke"}
          onOpenChange={(open) => !open && setConfirm(null)}
          title="¿Revocar el enlace?"
          description="El cliente dejará de poder abrirlo. No se puede deshacer: si hace falta, crea uno nuevo."
          confirmLabel="Revocar"
          onConfirm={() => revokeMut.mutate()}
        />
      </CardContent>
    </Card>
  )
}
