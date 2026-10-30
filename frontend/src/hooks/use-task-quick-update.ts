import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { changesApi, tasksApi } from "@/lib/api"
import type { Task, TaskCreate, TaskStatus } from "@/lib/types"
import { getErrorMessage } from "@/lib/utils"
import { invalidateTaskChange, restoreQuerySnapshot, taskKeys, type QuerySnapshot } from "@/lib/query-keys"
import { showUndoResult } from "@/lib/undo-feedback"
import { ranksForMove } from "@/lib/task-rank"

export interface TaskQuickUpdate {
  task: Task
  data: Partial<TaskCreate>
  /** Lo que se pinta mientras responde el servidor (p. ej. el nombre del responsable). */
  display?: Partial<Task>
  /** Aviso al guardar, con "Deshacer". Sin él no hay aviso (arrastres). */
  success?: string
  error?: string
}

type Paginated = { items: Task[] }
type Infinite = { pages: Paginated[] }

function patchItems(items: Task[], taskId: number, patch: Partial<Task>) {
  return items.some((task) => task.id === taskId)
    ? items.map((task) => task.id === taskId ? { ...task, ...patch } : task)
    : items
}

/** Aplica el cambio a la tarea en listas, agenda (paginada o infinita) y ficha. */
export function patchCachedTask(data: unknown, taskId: number, patch: Partial<Task>): unknown {
  if (!data || typeof data !== "object") return data
  if (Array.isArray(data)) return patchItems(data as Task[], taskId, patch)
  if ("pages" in data && Array.isArray((data as Infinite).pages)) {
    const infinite = data as Infinite
    const pages = infinite.pages.map((page) => {
      const items = patchItems(page.items ?? [], taskId, patch)
      return items === page.items ? page : { ...page, items }
    })
    return pages.every((page, index) => page === infinite.pages[index]) ? data : { ...infinite, pages }
  }
  if ("items" in data && Array.isArray((data as Paginated).items)) {
    const items = patchItems((data as Paginated).items, taskId, patch)
    return items === (data as Paginated).items ? data : { ...data, items }
  }
  if ((data as Task).id === taskId && "title" in data) return { ...data, ...patch }
  return data
}

async function optimisticallyPatchTasks(queryClient: QueryClient, patches: Map<number, Partial<Task>>) {
  await queryClient.cancelQueries({ queryKey: taskKeys.all() })
  const snapshots: QuerySnapshot[] = []
  for (const [queryKey, data] of queryClient.getQueriesData({ queryKey: taskKeys.all() })) {
    let next = data
    patches.forEach((patch, taskId) => { next = patchCachedTask(next, taskId, patch) })
    if (next === data) continue
    snapshots.push([queryKey, data])
    queryClient.setQueryData(queryKey, next)
  }
  return snapshots
}

/**
 * Deshace el último cambio de ESTA tarea (no el último cambio a secas, que es lo
 * que hace ⌘Z): el aviso de una celda puede seguir en pantalla tras otro cambio.
 */
async function undoLatestTaskChange(queryClient: QueryClient, taskId: number) {
  try {
    const entry = (await changesApi.recent()).find((item) => item.entity_type === "task" && item.entity_id === taskId)
    if (!entry) {
      toast("Este cambio ya no está entre tus últimos cinco: no se puede deshacer")
      return
    }
    showUndoResult(await changesApi.undo(entry.id))
  } catch (error) {
    toast.error(getErrorMessage(error, "No se ha podido deshacer el cambio"))
  }
  void queryClient.invalidateQueries()
}

/**
 * Cambio rápido de una tarea sin abrir el panel: se ve al momento en todas las
 * listas y, si el servidor dice que no, vuelve atrás y explica por qué.
 */
export function useTaskQuickUpdate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ task, data }: TaskQuickUpdate) => tasksApi.update(task.id, data),
    onMutate: async ({ task, data, display }) => ({
      snapshots: await optimisticallyPatchTasks(queryClient, new Map([[task.id, { ...data, ...display } as Partial<Task>]])),
    }),
    onSuccess: (saved, { task, data, success }) => {
      if (data.status === "in_review" && saved.status === "in_review" && task.status !== "in_review") {
        toast.success("Enviada a revisión: la cierra quien revisa el proyecto")
      } else if (success) {
        toast.success(success, {
          duration: 8000,
          action: { label: "Deshacer", onClick: () => void undoLatestTaskChange(queryClient, task.id) },
        })
      }
    },
    onError: (err, { error }, ctx) => {
      ctx?.snapshots.forEach((snapshot) => restoreQuerySnapshot(queryClient, snapshot))
      toast.error(getErrorMessage(err, error ?? "No se pudo guardar el cambio"))
    },
    onSettled: (saved, _err, { task }) => invalidateTaskChange(queryClient, {
      projectId: saved?.project_id ?? task.project_id,
      previousProjectId: task.project_id,
      clientId: saved?.client_id ?? task.client_id,
      previousClientId: task.client_id,
    }),
  })
}

export interface TaskMove {
  task: Task
  /** La lista donde queda la tarea, en el orden en que se ve tras soltarla. */
  ordered: Task[]
  status?: TaskStatus
  scheduledDate?: string | null
}

/**
 * Arrastrar una tarea (orden manual y, si cambia, columna o día). El nuevo
 * orden se pinta al momento con los mismos rangos que pondrá el servidor.
 */
export function useTaskMove() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ task, ordered, status, scheduledDate }: TaskMove) => tasksApi.move(task.id, {
      ordered_ids: ordered.map((item) => item.id),
      ...(status !== undefined && { status }),
      ...(scheduledDate !== undefined && { scheduled_date: scheduledDate }),
    }),
    onMutate: async ({ task, ordered, status, scheduledDate }) => {
      const ranks = ranksForMove(ordered.map((item) => item.id), task.id, new Map(ordered.map((item) => [item.id, item.sort_rank ?? null])))
      const patches = new Map<number, Partial<Task>>([...ranks].map(([id, sort_rank]) => [id, { sort_rank }]))
      patches.set(task.id, {
        ...patches.get(task.id),
        ...(status !== undefined && { status }),
        ...(scheduledDate !== undefined && { scheduled_date: scheduledDate }),
      })
      return { snapshots: await optimisticallyPatchTasks(queryClient, patches) }
    },
    onSuccess: ({ task: saved }, { task, status }) => {
      if (status === "in_review" && saved.status === "in_review" && task.status !== "in_review") {
        toast.success("Enviada a revisión: la cierra quien revisa el proyecto")
      }
    },
    onError: (err, _vars, ctx) => {
      ctx?.snapshots.forEach((snapshot) => restoreQuerySnapshot(queryClient, snapshot))
      toast.error(getErrorMessage(err, "No se pudo mover la tarea"))
    },
    onSettled: (result, _err, { task }) => invalidateTaskChange(queryClient, {
      projectId: result?.task.project_id ?? task.project_id,
      clientId: result?.task.client_id ?? task.client_id,
    }),
  })
}
