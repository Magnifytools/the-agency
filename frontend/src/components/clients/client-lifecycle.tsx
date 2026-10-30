import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Archive, RotateCcw } from "lucide-react"
import { clientsApi } from "@/lib/api"
import type { Client } from "@/lib/types"
import { invalidateClientChange } from "@/lib/query-keys"
import { getErrorMessage } from "@/lib/utils"
import { useAuth } from "@/context/auth-context"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"

/**
 * Cliente antiguo = estado `finished`: deja de salir en la cartera, las alertas
 * y las importaciones, pero conserva todo su historial y se puede reactivar.
 */
function useClientLifecycle(client: Client) {
  const queryClient = useQueryClient()
  const { hasPermission } = useAuth()
  const canWrite = hasPermission("clients", true)
  const mutation = useMutation({
    mutationFn: (status: "active" | "finished") => clientsApi.update(client.id, { status }),
    onSuccess: (_result, status) => {
      void invalidateClientChange(queryClient, [client.id])
      toast.success(status === "finished" ? `${client.name} pasa a clientes antiguos` : `${client.name} vuelve a estar activo`)
    },
    onError: (err) => toast.error(getErrorMessage(err, "No se pudo cambiar el estado del cliente")),
  })
  return { canWrite, mutation, isFormer: client.status === "finished" }
}

/** Botón de la cabecera de la ficha: "Marcar como antiguo" o "Reactivar". */
export function ClientLifecycleButton({ client }: { client: Client }) {
  const { canWrite, mutation, isFormer } = useClientLifecycle(client)
  const [confirming, setConfirming] = useState(false)
  if (!canWrite) return null
  if (isFormer) {
    return (
      <Button variant="outline" size="sm" disabled={mutation.isPending} onClick={() => mutation.mutate("active")}>
        <RotateCcw className="mr-1 h-4 w-4" /> Reactivar
      </Button>
    )
  }
  return (
    <>
      <Button variant="ghost" size="sm" disabled={mutation.isPending} onClick={() => setConfirming(true)}>
        <Archive className="mr-1 h-4 w-4" /> Marcar como antiguo
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title="Marcar como cliente antiguo"
        description="Dejará de salir en la cartera, las alertas, los resúmenes pendientes y las importaciones. No se borra nada: tareas, horas, resúmenes y contactos se conservan y se puede reactivar cuando quieras."
        confirmLabel="Marcar como antiguo"
        onConfirm={() => { mutation.mutate("finished"); setConfirming(false) }}
      />
    </>
  )
}

/** Aviso bajo la cabecera cuando el cliente es antiguo. */
export function FormerClientNotice({ client }: { client: Client }) {
  if (client.status !== "finished") return null
  return (
    <p role="status" className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
      Cliente antiguo: no sale en la cartera ni en las alertas. Su historial se conserva y se puede reactivar.
    </p>
  )
}
