import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { clientsApi } from "@/lib/api"
import {
  credentialsApi,
  type Credential,
  type CredentialInput,
  type CredentialLogAction,
} from "@/lib/credentials-api"
import { getAgencyTimezone, parseApiInstant } from "@/lib/dates"
import { useAuth } from "@/context/auth-context"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"

export const CREDENTIALS_KEY = ["credentials"] as const

const empty = (value: string) => (value.trim() ? value.trim() : null)

/** Alta o edición. Al editar, la contraseña sólo se cambia si se escribe una nueva. */
export function CredentialFormDialog({ open, onOpenChange, credential, fixedClientId }: {
  open: boolean
  onOpenChange: (open: boolean) => void
  credential?: Credential | null
  /** Desde la ficha de un cliente: el acceso queda ligado a él. */
  fixedClientId?: number
}) {
  const qc = useQueryClient()
  const { hasPermission } = useAuth()
  const editing = !!credential
  const [name, setName] = useState(credential?.name ?? "")
  const [url, setUrl] = useState(credential?.url ?? "")
  const [username, setUsername] = useState(credential?.username ?? "")
  const [secret, setSecret] = useState("")
  const [notes, setNotes] = useState(credential?.notes ?? "")
  const [clientId, setClientId] = useState<number | null>(fixedClientId ?? credential?.client_id ?? null)
  const canPickClient = fixedClientId === undefined && hasPermission("clients")

  const { data: clients = [] } = useQuery({
    queryKey: ["clients-all", "active"],
    queryFn: () => clientsApi.listAll("active"),
    enabled: open && canPickClient,
  })

  const save = useMutation({
    mutationFn: () => {
      const data: CredentialInput = { name: name.trim(), url: empty(url), username: empty(username), notes: empty(notes), client_id: clientId }
      if (secret) data.secret = secret
      return editing ? credentialsApi.update(credential.id, data) : credentialsApi.create(data)
    },
    onSuccess: () => {
      setSecret("")
      void qc.invalidateQueries({ queryKey: CREDENTIALS_KEY })
      toast.success(editing ? "Acceso guardado" : "Acceso creado")
      onOpenChange(false)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!name.trim() || (!editing && !secret)) return
    save.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>{editing ? "Editar acceso" : "Nuevo acceso"}</DialogTitle>
      </DialogHeader>
      <form onSubmit={submit} autoComplete="off">
        <DialogContent>
          <div className="space-y-1">
            <Label htmlFor="credential-name">Nombre</Label>
            <Input id="credential-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="WordPress de Fit Generation" required maxLength={200} />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="credential-url">URL</Label>
              <Input id="credential-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/wp-admin" maxLength={500} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="credential-username">Usuario</Label>
              <Input id="credential-username" value={username} onChange={(e) => setUsername(e.target.value)} maxLength={255} autoComplete="off" />
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor="credential-secret">{editing ? "Nueva contraseña" : "Contraseña"}</Label>
            <Input
              id="credential-secret" type="password" value={secret} onChange={(e) => setSecret(e.target.value)}
              required={!editing} maxLength={2000} autoComplete="new-password"
              placeholder={editing ? "Déjala vacía para no cambiarla" : undefined}
            />
          </div>
          {canPickClient && (
            <div className="space-y-1">
              <Label htmlFor="credential-client">Cliente</Label>
              <Select id="credential-client" value={clientId ?? ""} onChange={(e) => setClientId(e.target.value ? Number(e.target.value) : null)}>
                <option value="">Sin cliente (herramienta de la agencia)</option>
                {credential?.client_id && !clients.some((c) => c.id === credential.client_id) && (
                  <option value={credential.client_id}>{credential.client_name ?? "Cliente actual"}</option>
                )}
                {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </div>
          )}
          <div className="space-y-1">
            <Label htmlFor="credential-notes">Notas</Label>
            <Textarea id="credential-notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} maxLength={5000} />
            <p className="text-[11px] text-muted-foreground">Las notas no se cifran: no pongas aquí contraseñas ni códigos.</p>
          </div>
        </DialogContent>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
          <Button type="submit" disabled={save.isPending || !name.trim() || (!editing && !secret)}>
            {save.isPending ? "Guardando…" : "Guardar"}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  )
}

/** Con quién se comparte. Sólo salen usuarios activos que pueden abrir Accesos. */
export function CredentialShareDialog({ credential, onOpenChange }: {
  credential: Credential
  onOpenChange: (open: boolean) => void
}) {
  const qc = useQueryClient()
  const { user } = useAuth()
  const [selected, setSelected] = useState<Set<number>>(() => new Set(credential.shared_with.map((u) => u.id)))
  const { data: users = [], isLoading } = useQuery({
    queryKey: ["credentials", "shareable-users"],
    queryFn: credentialsApi.shareableUsers,
  })
  const save = useMutation({
    mutationFn: () => credentialsApi.setShares(credential.id, [...selected]),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: CREDENTIALS_KEY })
      toast.success("Accesos compartidos actualizados")
      onOpenChange(false)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })
  const toggle = (id: number) => setSelected((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })
  const candidates = users.filter((u) => u.id !== user?.id && u.id !== credential.created_by)

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Compartir «{credential.name}»</DialogTitle>
      </DialogHeader>
      <DialogContent>
        <p className="text-sm text-muted-foreground">Los admins ven todos los accesos. Aquí eliges qué otras personas pueden ver y copiar esta contraseña.</p>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Cargando…</p>
        ) : candidates.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nadie más tiene el módulo Accesos. Dáselo en Equipo y permisos.</p>
        ) : (
          <ul className="space-y-1 max-h-72 overflow-y-auto">
            {candidates.map((u) => (
              <li key={u.id}>
                <label className="flex items-center gap-2 text-sm py-1 cursor-pointer">
                  <input type="checkbox" checked={selected.has(u.id)} onChange={() => toggle(u.id)} />
                  {u.full_name}
                </label>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
        <Button type="button" disabled={save.isPending || isLoading} onClick={() => save.mutate()}>
          {save.isPending ? "Guardando…" : "Guardar"}
        </Button>
      </DialogFooter>
    </Dialog>
  )
}

const ACTION_LABELS: Record<CredentialLogAction, string> = {
  reveal: "Vio la contraseña",
  copy: "Copió la contraseña",
  create: "Lo creó",
  update: "Lo editó",
  share: "Cambió con quién se comparte",
  delete: "Lo borró",
}

function formatInstant(value: string) {
  return parseApiInstant(value).toLocaleString("es-ES", {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
    timeZone: getAgencyTimezone(),
  })
}

/** Registro de quién vio, copió o cambió el acceso (sólo admins). */
export function CredentialLogDialog({ credential, onOpenChange }: {
  credential: Credential
  onOpenChange: (open: boolean) => void
}) {
  const { data: entries = [], isLoading, error } = useQuery({
    queryKey: ["credentials", credential.id, "log"],
    queryFn: () => credentialsApi.log(credential.id),
  })
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Registro de «{credential.name}»</DialogTitle>
      </DialogHeader>
      <DialogContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Cargando…</p>
        ) : error ? (
          <p className="text-sm text-destructive">{getErrorMessage(error)}</p>
        ) : entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">Sin movimientos.</p>
        ) : (
          <ul className="divide-y divide-border max-h-96 overflow-y-auto text-sm">
            {entries.map((entry) => (
              <li key={entry.id} className="py-2">
                <div className="flex flex-wrap justify-between gap-x-3">
                  <span><strong>{entry.user_name ?? "Usuario borrado"}</strong> · {ACTION_LABELS[entry.action]}</span>
                  <span className="mono text-xs text-muted-foreground">{formatInstant(entry.at)}</span>
                </div>
                {entry.detail && <p className="text-xs text-muted-foreground">{entry.detail}</p>}
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cerrar</Button>
      </DialogFooter>
    </Dialog>
  )
}
