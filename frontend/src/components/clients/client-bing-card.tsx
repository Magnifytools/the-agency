import { useState, type CSSProperties } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Search } from "lucide-react"
import { clientBingApi } from "@/lib/api"
import { clientBingKeys } from "@/lib/query-keys"
import type { BingAccountSites, ClientBingConnection } from "@/lib/types"
import { getErrorMessage } from "@/lib/utils"
import { useAuth } from "@/context/auth-context"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { formatInstant } from "@/components/web/uptime-status"

// No es un login: que ni el navegador ni los gestores de contraseñas lo rellenen.
const NOT_A_LOGIN = { autoComplete: "off", "data-1p-ignore": true, "data-lpignore": "true" } as const
const MASKED = { WebkitTextSecurity: "disc" } as CSSProperties

interface Props {
  clientId: number
}

/**
 * Cuenta de Bing Webmaster Tools de la web del cliente (cada web tiene la suya).
 * Sólo un admin conecta, cambia o quita la clave; el resto ve el estado. La
 * clave se guarda cifrada y nunca vuelve del servidor.
 */
export function ClientBingCard({ clientId }: Props) {
  const { isAdmin } = useAuth()
  const qc = useQueryClient()
  const queryKey = clientBingKeys.connection(clientId)
  const { data, isLoading } = useQuery({ queryKey, queryFn: () => clientBingApi.connection(clientId) })
  const [editing, setEditing] = useState(false)
  const [apiKey, setApiKey] = useState("")
  const [account, setAccount] = useState<BingAccountSites | null>(null)
  const [site, setSite] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState(false)

  const reset = () => {
    setEditing(false)
    setApiKey("")
    setAccount(null)
    setSite(null)
  }
  const saved = (next: ClientBingConnection, message: string) => {
    qc.setQueryData(queryKey, next)
    reset()
    toast.success(message)
  }

  const sitesMut = useMutation({
    mutationFn: () => clientBingApi.sites(clientId, apiKey.trim()),
    onSuccess: (result) => {
      setAccount(result)
      setSite(result.suggested ?? (result.sites.length === 1 ? result.sites[0] : null))
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const connectMut = useMutation({
    mutationFn: () => clientBingApi.connect(clientId, apiKey.trim(), site!),
    onSuccess: (next) => saved(next, "Bing conectado"),
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const removeMut = useMutation({
    mutationFn: () => clientBingApi.disconnect(clientId),
    onSuccess: (next) => saved(next, "Bing desconectado"),
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const busy = sitesMut.isPending || connectMut.isPending || removeMut.isPending
  const showForm = isAdmin && data && (!data.connected || editing)

  return (
    <Card id="bing-webmaster" className="scroll-mt-8">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Search className="h-4 w-4" /> Bing Webmaster Tools
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading || !data ? (
          <p className="text-sm text-muted-foreground">Cargando…</p>
        ) : (
          <>
            <ConnectionState data={data} isAdmin={isAdmin} />
            {data.connected && isAdmin && !editing && (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="outline" disabled={busy} onClick={() => setEditing(true)}>Cambiar clave</Button>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => setConfirmRemove(true)}>Desconectar</Button>
              </div>
            )}
            {showForm && (
              <div className="space-y-3 rounded-md border border-border p-3">
                <ol className="list-decimal pl-5 text-xs text-muted-foreground space-y-0.5">
                  <li>Entra en Bing Webmaster Tools con la cuenta de esta web.</li>
                  <li>Ajustes (la rueda, arriba a la derecha) → API access → API Key.</li>
                  <li>Genera la clave si no hay ninguna, cópiala y pégala aquí.</li>
                </ol>
                <form
                  className="space-y-3"
                  onSubmit={(e) => {
                    e.preventDefault()
                    if (account && site) connectMut.mutate()
                    else if (apiKey.trim()) sitesMut.mutate()
                  }}
                >
                  <div className="space-y-1">
                    <Label htmlFor={`bing-key-${clientId}`}>API key de Bing</Label>
                    {/* Enmascarado por CSS y no type="password": no es un login. */}
                    <Input id={`bing-key-${clientId}`} type="text" {...NOT_A_LOGIN} style={MASKED} value={apiKey}
                      onChange={(e) => { setApiKey(e.target.value); setAccount(null); setSite(null) }}
                      placeholder={data.connected ? "Pega la clave nueva" : "Pega la clave de la cuenta de esta web"} />
                  </div>
                  {account && (account.sites.length === 0 ? (
                    <p className="text-sm text-amber-600">Esa cuenta no tiene ningún sitio verificado en Bing.</p>
                  ) : (
                    <fieldset className="space-y-1">
                      <legend className="text-sm font-medium">¿Cuál es la web del cliente?</legend>
                      {account.sites.map((url) => (
                        <label key={url} className="flex items-center gap-2 text-sm">
                          <input type="radio" name={`bing-site-${clientId}`} className="h-4 w-4" value={url}
                            checked={site === url} onChange={() => setSite(url)} />
                          <span className="break-all">{url}</span>
                          {url === account.suggested && <span className="text-xs text-muted-foreground">(coincide con su web)</span>}
                        </label>
                      ))}
                    </fieldset>
                  ))}
                  <div className="flex flex-wrap gap-2">
                    {account && account.sites.length > 0 ? (
                      <Button type="submit" size="sm" disabled={busy || !site}>
                        {connectMut.isPending ? "Conectando…" : "Conectar"}
                      </Button>
                    ) : (
                      <Button type="submit" size="sm" disabled={busy || !apiKey.trim()}>
                        {sitesMut.isPending ? "Comprobando…" : "Comprobar clave"}
                      </Button>
                    )}
                    {editing && <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={reset}>Cancelar</Button>}
                  </div>
                </form>
              </div>
            )}
          </>
        )}
        <ConfirmDialog
          open={confirmRemove}
          onOpenChange={setConfirmRemove}
          title="¿Desconectar Bing?"
          description="The Agency olvida la clave y deja de comprobar esta web en Bing. La clave sigue activa en Bing Webmaster Tools: bórrala allí si quieres cortar el acceso."
          confirmLabel="Desconectar"
          onConfirm={() => removeMut.mutate()}
        />
      </CardContent>
    </Card>
  )
}

function ConnectionState({ data, isAdmin }: { data: ClientBingConnection; isAdmin: boolean }) {
  if (!data.connected) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Sin conectar.{isAdmin ? "" : " Lo conecta un admin con la clave de la cuenta de Bing de esta web."}
      </p>
    )
  }
  const by = [data.connected_by_name, data.connected_at ? formatInstant(data.connected_at) : null].filter(Boolean).join(", ")
  return (
    <div role="status" className="space-y-1 text-sm">
      {data.status === "invalid" ? (
        <p className="text-red-400">
          Bing ya no acepta la clave{data.last_error ? ` (${data.last_error})` : ""}. {isAdmin ? "Pega una nueva." : "Avisa a un admin."}
        </p>
      ) : (
        <p className="text-green-500">Conectado: se puede comprobar en Control SEO.</p>
      )}
      <p className="text-muted-foreground">
        Sitio: <span className="break-all">{data.site_url}</span>{by ? ` · ${by}` : ""}
      </p>
    </div>
  )
}
