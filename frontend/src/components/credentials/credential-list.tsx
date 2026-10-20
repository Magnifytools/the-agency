import { useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ExternalLink, History, KeyRound, Pencil, Trash2, Users } from "lucide-react"
import { credentialsApi, type Credential } from "@/lib/credentials-api"
import { useAuth } from "@/context/auth-context"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { CredentialSecret } from "./credential-secret"
import {
  CREDENTIALS_KEY,
  CredentialFormDialog,
  CredentialLogDialog,
  CredentialShareDialog,
} from "./credential-dialogs"

/** Sólo enlaces http(s): una URL guardada no debe poder ejecutar nada al pulsarla. */
function safeHref(url: string | null): string | null {
  if (!url) return null
  try {
    const parsed = new URL(/^[a-z][a-z0-9+.-]*:/i.test(url) ? url : `https://${url}`)
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null
  } catch {
    return null
  }
}

type Dialogs =
  | { kind: "edit"; credential: Credential }
  | { kind: "share"; credential: Credential }
  | { kind: "log"; credential: Credential }
  | { kind: "delete"; credential: Credential }
  | null

/**
 * Lista de accesos que puede ver quien mira. La contraseña nunca viene en la
 * lista: se pide una a una (y queda registrada) con CredentialSecret.
 */
export function CredentialList({ q, clientId, showClient = true }: {
  q?: string
  clientId?: number
  showClient?: boolean
}) {
  const { isAdmin, hasPermission } = useAuth()
  const qc = useQueryClient()
  const [dialog, setDialog] = useState<Dialogs>(null)
  const params = { ...(q?.trim() ? { q: q.trim() } : {}), ...(clientId !== undefined ? { client_id: clientId } : {}) }
  const { data: credentials = [], isLoading, error } = useQuery({
    queryKey: [...CREDENTIALS_KEY, params],
    queryFn: () => credentialsApi.list(params),
  })
  const canWrite = hasPermission("credentials", true)

  const remove = useMutation({
    mutationFn: (id: number) => credentialsApi.remove(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CREDENTIALS_KEY })
      toast.success("Acceso borrado")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const copyUsername = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      toast.success("Usuario copiado")
    } catch {
      toast.error("No se pudo copiar")
    }
  }

  if (isLoading) return <p className="text-sm text-muted-foreground">Cargando…</p>
  if (error) return <p className="text-sm text-destructive">{getErrorMessage(error)}</p>
  if (credentials.length === 0) {
    return (
      <div className="flex flex-col items-center py-10 text-center">
        <KeyRound className="h-8 w-8 text-muted-foreground mb-2" />
        <p className="text-sm text-muted-foreground">
          {q?.trim() ? "Ningún acceso coincide con la búsqueda." : "No hay accesos que puedas ver todavía."}
        </p>
      </div>
    )
  }

  return (
    <>
      <ul className="divide-y divide-border">
        {credentials.map((c) => {
          const href = safeHref(c.url)
          return (
            <li key={c.id} className="py-3 grid grid-cols-1 md:grid-cols-[minmax(0,2fr)_minmax(0,1.5fr)_minmax(0,1.5fr)_auto] gap-2 md:items-center">
              <div className="min-w-0">
                <p className="font-medium truncate">{c.name}</p>
                <p className="text-xs text-muted-foreground truncate">
                  {href ? (
                    <a href={href} target="_blank" rel="noopener noreferrer" className="hover:underline inline-flex items-center gap-1">
                      {c.url} <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : c.url}
                  {showClient && c.client_name && (
                    <>
                      {c.url && " · "}
                      {c.client_id && hasPermission("clients")
                        ? <Link to={`/clients/${c.client_id}`} className="hover:underline">{c.client_name}</Link>
                        : <span>{c.client_name}</span>}
                    </>
                  )}
                </p>
                {c.notes && <p className="text-xs text-muted-foreground whitespace-pre-wrap line-clamp-2">{c.notes}</p>}
              </div>
              <div className="min-w-0 text-sm">
                {c.username ? (
                  <button type="button" className="mono text-xs truncate max-w-full hover:underline" title="Copiar usuario" onClick={() => copyUsername(c.username!)}>
                    {c.username}
                  </button>
                ) : <span className="text-xs text-muted-foreground">Sin usuario</span>}
              </div>
              <CredentialSecret credentialId={c.id} name={c.name} />
              <div className="flex gap-1 md:justify-end">
                {c.can_manage && canWrite && (
                  <>
                    <Button type="button" size="icon" variant="ghost" className="h-7 w-7" aria-label={`Editar ${c.name}`} onClick={() => setDialog({ kind: "edit", credential: c })}>
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button type="button" size="icon" variant="ghost" className="h-7 w-7" aria-label={`Compartir ${c.name}`} title={c.shared_with.length ? `Compartido con ${c.shared_with.map((u) => u.full_name).join(", ")}` : "Sin compartir"} onClick={() => setDialog({ kind: "share", credential: c })}>
                      <Users className="h-3.5 w-3.5" />
                    </Button>
                  </>
                )}
                {isAdmin && (
                  <>
                    <Button type="button" size="icon" variant="ghost" className="h-7 w-7" aria-label={`Registro de ${c.name}`} onClick={() => setDialog({ kind: "log", credential: c })}>
                      <History className="h-3.5 w-3.5" />
                    </Button>
                    <Button type="button" size="icon" variant="ghost" className="h-7 w-7 text-destructive" aria-label={`Borrar ${c.name}`} onClick={() => setDialog({ kind: "delete", credential: c })}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </>
                )}
              </div>
            </li>
          )
        })}
      </ul>

      {dialog?.kind === "edit" && (
        <CredentialFormDialog key={dialog.credential.id} open credential={dialog.credential} onOpenChange={(open) => !open && setDialog(null)} />
      )}
      {dialog?.kind === "share" && (
        <CredentialShareDialog credential={dialog.credential} onOpenChange={(open) => !open && setDialog(null)} />
      )}
      {dialog?.kind === "log" && (
        <CredentialLogDialog credential={dialog.credential} onOpenChange={(open) => !open && setDialog(null)} />
      )}
      <ConfirmDialog
        open={dialog?.kind === "delete"}
        onOpenChange={(open) => !open && setDialog(null)}
        title={`¿Borrar «${dialog?.credential.name ?? ""}»?`}
        description="Se borra para todos y no se puede deshacer. El registro de quién lo usó se conserva."
        confirmLabel="Borrar"
        onConfirm={() => dialog && remove.mutate(dialog.credential.id)}
      />
    </>
  )
}
