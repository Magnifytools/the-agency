import { toast } from "sonner"
import type { UndoResult } from "@/lib/types"

/** Report the actual inverse result, including protected later edits. */
export function showUndoResult(result: UndoResult) {
  if (result.restored === 0) {
    toast.warning("No se ha restaurado ningún cambio", {
      description: result.warnings.join(" ") || "El estado actual se ha conservado.",
      duration: 8000,
    })
  } else if (result.warnings.length > 0) {
    toast.warning(`Deshecho parcialmente: ${result.label}`, {
      description: result.warnings.join(" "),
      duration: 8000,
    })
  } else {
    toast.success(`Deshecho: ${result.label}`)
  }
}
