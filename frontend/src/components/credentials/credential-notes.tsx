import { useEffect, useState } from "react"
import { toast } from "sonner"
import { StickyNote } from "lucide-react"
import { credentialsApi } from "@/lib/credentials-api"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { REVEAL_SECONDS } from "./credential-secret"

/**
 * Notas de un acceso: van cifradas y se piden al servidor (queda en el registro),
 * como la contraseña. Se ocultan solas a los 30 s y no pasan por la caché.
 */
export function CredentialNotes({ credentialId, name }: { credentialId: number; name: string }) {
  const [notes, setNotes] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (notes === null) return
    const timer = window.setTimeout(() => setNotes(null), REVEAL_SECONDS * 1000)
    return () => window.clearTimeout(timer)
  }, [notes])

  const toggle = async () => {
    if (notes !== null) {
      setNotes(null)
      return
    }
    setBusy(true)
    try {
      setNotes(await credentialsApi.notes(credentialId))
    } catch (e) {
      toast.error(getErrorMessage(e, "No se pudieron abrir las notas"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-w-0">
      <Button
        type="button" size="sm" variant="ghost" className="h-6 px-1.5 text-xs gap-1 text-muted-foreground"
        aria-label={notes !== null ? `Ocultar notas de ${name}` : `Ver notas de ${name}`}
        aria-expanded={notes !== null} disabled={busy} onClick={toggle}
      >
        <StickyNote className="h-3 w-3" /> {notes !== null ? "Ocultar notas" : "Notas"}
      </Button>
      {notes !== null && <p className="text-xs whitespace-pre-wrap break-words select-all">{notes}</p>}
    </div>
  )
}
