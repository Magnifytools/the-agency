// Barrel file — re-exports all types from domain-specific files.
// Existing imports like `from "@/lib/types"` continue to work unchanged.

export * from "./types/common"
export * from "./types/client"
export * from "./types/task"
export * from "./types/project"
export * from "./types/finance"
export * from "./types/integration"

// --- Undo: journal de cambios ---
// Una entrada = una acción del usuario (una transacción), no una fila tocada.
// Borrar un proyecto que desvincula 8 tareas es UN "Deshacer".
export interface ChangeEntry {
  id: number
  label: string
  action: "create" | "update" | "delete"
  entity_type: string
  entity_id: number | null
  created_at: string
  operation_count: number
}

export interface UndoResult {
  id: number
  label: string
  restored: number
  // Lo que el undo NO ha tocado porque otra persona lo cambió después.
  warnings: string[]
}
