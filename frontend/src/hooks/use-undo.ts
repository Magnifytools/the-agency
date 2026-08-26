import { useCallback } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { changesApi } from "@/lib/api"
import type { ChangeEntry } from "@/lib/types"

export const undoKeys = {
  recent: () => ["changes", "recent"] as const,
}

/**
 * Historial de los últimos cambios del usuario y cómo deshacerlos.
 *
 * Lo comparten el panel de la barra lateral y el atajo de teclado, así que el
 * estado (y el toast) sale de un solo sitio. Tras deshacer se invalida TODA la
 * caché a propósito: un cambio puede haber tocado tareas, proyectos y cliente a
 * la vez, y adivinar qué claves refrescar sería adivinar mal tarde o temprano.
 */
export function useUndo() {
  const queryClient = useQueryClient()

  const { data: entries = [], isLoading } = useQuery({
    queryKey: undoKeys.recent(),
    queryFn: () => changesApi.recent(),
    staleTime: 15_000,
  })

  const mutation = useMutation({
    mutationFn: (id: number) => changesApi.undo(id),
    onSuccess: (result) => {
      if (result.warnings.length > 0) {
        toast.warning(`Deshecho: ${result.label}`, {
          description: result.warnings.join(" "),
          duration: 8000,
        })
      } else {
        toast.success(`Deshecho: ${result.label}`)
      }
      void queryClient.invalidateQueries()
    },
    onError: (error: unknown) => {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(detail ?? "No se ha podido deshacer el cambio")
      // El motivo suele ser que el estado ya cambió: refresca el historial.
      void queryClient.invalidateQueries({ queryKey: undoKeys.recent() })
    },
  })

  const undo = useCallback((entry: ChangeEntry) => mutation.mutate(entry.id), [mutation])

  const refresh = useCallback(
    () => queryClient.invalidateQueries({ queryKey: undoKeys.recent() }),
    [queryClient],
  )

  // Relee el historial antes de deshacer en vez de fiarse de la caché: el cambio
  // que el usuario quiere deshacer suele ser el que acaba de hacer, y con datos
  // rancios el atajo desharía el ANTERIOR — justo lo que nadie espera.
  const undoLast = useCallback(async () => {
    const fresh = await queryClient.fetchQuery({
      queryKey: undoKeys.recent(),
      queryFn: () => changesApi.recent(),
      staleTime: 0,
    })
    const last = fresh[0]
    if (!last) {
      toast("No hay nada que deshacer")
      return
    }
    mutation.mutate(last.id)
  }, [queryClient, mutation])

  return {
    entries,
    isLoading,
    undo,
    undoLast,
    refresh,
    isUndoing: mutation.isPending,
    pendingId: mutation.variables,
  }
}
