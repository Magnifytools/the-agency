import { useEffect } from "react"

/** Pide confirmación al cerrar o recargar la pestaña mientras haya cambios sin guardar. */
export function useUnsavedChangesWarning(unsaved: boolean) {
  useEffect(() => {
    if (!unsaved) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      // Chrome todavía exige returnValue para enseñar el aviso.
      event.returnValue = ""
    }
    window.addEventListener("beforeunload", warn)
    return () => window.removeEventListener("beforeunload", warn)
  }, [unsaved])
}
