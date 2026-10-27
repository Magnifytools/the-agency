import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Copy, ShieldCheck, X } from "lucide-react"
import { credentialsApi } from "@/lib/credentials-api"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"

interface Shown {
  codes: [string, string]
  /** Cuándo caduca el primero (ms). El segundo dura un periodo más. */
  expiresAt: number
  period: number
}

/** "123456" → "123 456", como lo enseñan los autenticadores. */
function formatCode(code: string): string {
  return code.length === 6 ? `${code.slice(0, 3)} ${code.slice(3)}` : code
}

/**
 * Código 2FA de un acceso: se pide al servidor (queda registrado), se enseña con
 * su cuenta atrás y, al caducar, pasa al siguiente sin volver a pedirlo. Cuando
 * caduca también ese, se oculta. Sólo vive en el estado de este componente.
 */
export function CredentialTotp({ credentialId, name }: { credentialId: number; name: string }) {
  const [shown, setShown] = useState<Shown | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!shown) return
    const timer = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(timer)
  }, [shown])

  const second = shown ? now >= shown.expiresAt : false
  const left = shown ? Math.ceil(((second ? shown.expiresAt + shown.period * 1000 : shown.expiresAt) - now) / 1000) : 0
  useEffect(() => {
    if (shown && left <= 0) setShown(null)
  }, [shown, left])
  const code = shown ? shown.codes[second ? 1 : 0] : null

  const show = async () => {
    setBusy(true)
    try {
      const data = await credentialsApi.totp(credentialId)
      const start = Date.now()
      setNow(start)
      setShown({ codes: [data.code, data.next_code], expiresAt: start + data.remaining * 1000, period: data.period })
    } catch (e) {
      toast.error(getErrorMessage(e, "No se pudo obtener el código 2FA"))
    } finally {
      setBusy(false)
    }
  }

  const copy = async () => {
    if (!code) return
    try {
      await navigator.clipboard.writeText(code)
      toast.success("Código 2FA copiado")
    } catch {
      toast.error("No se pudo copiar el código")
    }
  }

  if (!code) {
    return (
      <Button
        type="button" size="sm" variant="ghost" className="h-7 px-2 text-xs gap-1"
        aria-label={`Ver código 2FA de ${name}`} disabled={busy} onClick={show}
      >
        <ShieldCheck className="h-3.5 w-3.5" /> 2FA
      </Button>
    )
  }
  return (
    <div className="flex items-center gap-1">
      <span className="mono text-sm font-semibold tabular-nums" aria-live="polite" data-testid={`totp-${credentialId}`}>
        {formatCode(code)}
      </span>
      <span className={`mono text-[11px] tabular-nums ${left <= 5 ? "text-destructive" : "text-muted-foreground"}`} aria-label={`Caduca en ${left} segundos`}>
        {left}s
      </span>
      <Button type="button" size="icon" variant="ghost" className="h-7 w-7" aria-label={`Copiar código 2FA de ${name}`} onClick={copy}>
        <Copy className="h-3.5 w-3.5" />
      </Button>
      <Button type="button" size="icon" variant="ghost" className="h-7 w-7" aria-label={`Ocultar código 2FA de ${name}`} onClick={() => setShown(null)}>
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}
