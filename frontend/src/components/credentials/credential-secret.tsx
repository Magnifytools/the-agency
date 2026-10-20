import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Copy, Eye, EyeOff } from "lucide-react"
import { credentialsApi } from "@/lib/credentials-api"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"

/** Cuánto se queda a la vista una contraseña antes de ocultarse sola. */
export const REVEAL_SECONDS = 30

/**
 * Ver / ocultar / copiar la contraseña de un acceso. Cada "ver" y cada "copiar"
 * piden la contraseña al servidor, que lo apunta. Sólo vive en el estado de
 * este componente (nunca en la caché de TanStack) y se borra al ocultarla.
 */
export function CredentialSecret({ credentialId, name }: { credentialId: number; name: string }) {
  const [secret, setSecret] = useState<string | null>(null)
  const [busy, setBusy] = useState<"reveal" | "copy" | null>(null)

  useEffect(() => {
    if (secret === null) return
    const timer = window.setTimeout(() => setSecret(null), REVEAL_SECONDS * 1000)
    return () => window.clearTimeout(timer)
  }, [secret])

  const reveal = async () => {
    if (secret !== null) {
      setSecret(null)
      return
    }
    setBusy("reveal")
    try {
      setSecret(await credentialsApi.reveal(credentialId, "reveal"))
    } catch (e) {
      toast.error(getErrorMessage(e))
    } finally {
      setBusy(null)
    }
  }

  const copy = async () => {
    setBusy("copy")
    try {
      const value = await credentialsApi.reveal(credentialId, "copy")
      await navigator.clipboard.writeText(value)
      toast.success("Contraseña copiada")
    } catch (e) {
      toast.error(getErrorMessage(e, "No se pudo copiar la contraseña"))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="flex items-center gap-1 min-w-0">
      <span className="mono text-xs truncate select-all" aria-live="polite" data-testid={`secret-${credentialId}`}>
        {secret ?? "••••••••"}
      </span>
      <Button
        type="button" size="icon" variant="ghost" className="h-7 w-7 shrink-0"
        aria-label={secret !== null ? `Ocultar contraseña de ${name}` : `Ver contraseña de ${name}`}
        disabled={busy !== null} onClick={reveal}
      >
        {secret !== null ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
      </Button>
      <Button
        type="button" size="icon" variant="ghost" className="h-7 w-7 shrink-0"
        aria-label={`Copiar contraseña de ${name}`} disabled={busy !== null} onClick={copy}
      >
        <Copy className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}
