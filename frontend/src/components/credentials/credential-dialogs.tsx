import { useState, type ClipboardEvent, type FormEvent } from "react"
import { Eye, EyeOff, QrCode, Wand2 } from "lucide-react"
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
import { DEFAULT_LENGTH, generatePassword } from "@/lib/password-generator"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"

export const CREDENTIALS_KEY = ["credentials"] as const

const empty = (value: string) => (value.trim() ? value.trim() : null)

type BarcodeDetectorLike = { detect: (image: ImageBitmap) => Promise<{ rawValue: string }[]> }
type BarcodeDetectorCtor = new (options: { formats: string[] }) => BarcodeDetectorLike

/** Lector de QR del propio navegador (Chrome en Mac y Android). Si no lo hay, no se ofrece. */
function qrDetector(): BarcodeDetectorLike | null {
  const Ctor = (window as unknown as { BarcodeDetector?: BarcodeDetectorCtor }).BarcodeDetector
  return Ctor ? new Ctor({ formats: ["qr_code"] }) : null
}

/** El enlace otpauth:// de una captura del QR que enseña la web al activar el 2FA. */
async function readOtpauthQr(file: File): Promise<string> {
  const detector = qrDetector()
  if (!detector) throw new Error("Este navegador no lee códigos QR: copia la clave que aparece debajo del QR.")
  const found = await detector.detect(await createImageBitmap(file))
  const link = found.map((code) => code.rawValue).find((value) => value.toLowerCase().startsWith("otpauth://"))
  if (!link) throw new Error("No hay un QR de autenticador en la imagen.")
  return link
}

const GENERATOR_LENGTHS = [16, DEFAULT_LENGTH, 24, 32]

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
  const [showSecret, setShowSecret] = useState(false)
  const [length, setLength] = useState(DEFAULT_LENGTH)
  const [symbols, setSymbols] = useState(true)
  // Al editar uno que ya tiene 2FA: se queda igual salvo que se pida cambiar o quitar.
  const [totpMode, setTotpMode] = useState<"keep" | "change" | "remove">(credential?.has_totp ? "keep" : "change")
  const [totp, setTotp] = useState("")
  const canReadQr = typeof window !== "undefined" && "BarcodeDetector" in window
  // Las notas guardadas no vienen en la lista: al editar se piden (queda en el
  // registro) sólo si se quieren ver o cambiar; si no, no se envían.
  const [notes, setNotes] = useState("")
  const [notesLoaded, setNotesLoaded] = useState(!credential?.has_notes)
  const [loadingNotes, setLoadingNotes] = useState(false)
  const [clientId, setClientId] = useState<number | null>(fixedClientId ?? credential?.client_id ?? null)
  const canPickClient = fixedClientId === undefined && hasPermission("clients")

  const { data: clients = [] } = useQuery({
    queryKey: ["clients-all", "active"],
    queryFn: () => clientsApi.listAll("active"),
    enabled: open && canPickClient,
  })

  const save = useMutation({
    mutationFn: () => {
      const data: CredentialInput = { name: name.trim(), url: empty(url), username: empty(username), client_id: clientId }
      if (notesLoaded) data.notes = editing ? notes.trim() : empty(notes)
      if (secret) data.secret = secret
      if (totpMode === "remove") data.totp = ""
      else if (totpMode === "change" && totp.trim()) data.totp = totp.trim()
      return editing ? credentialsApi.update(credential.id, data) : credentialsApi.create(data)
    },
    onSuccess: () => {
      setSecret("")
      setTotp("")
      void qc.invalidateQueries({ queryKey: CREDENTIALS_KEY })
      toast.success(editing ? "Acceso guardado" : "Acceso creado")
      onOpenChange(false)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const loadNotes = async () => {
    if (!credential) return
    setLoadingNotes(true)
    try {
      setNotes(await credentialsApi.notes(credential.id))
      setNotesLoaded(true)
    } catch (e) {
      toast.error(getErrorMessage(e, "No se pudieron abrir las notas"))
    } finally {
      setLoadingNotes(false)
    }
  }

  const generate = (next: { length?: number; symbols?: boolean } = {}) => {
    const options = { length: next.length ?? length, symbols: next.symbols ?? symbols }
    setLength(options.length)
    setSymbols(options.symbols)
    setSecret(generatePassword(options))
    setShowSecret(true)
  }

  const readQr = async (file: File | undefined) => {
    if (!file) return
    try {
      setTotp(await readOtpauthQr(file))
      toast.success("Clave 2FA leída del QR")
    } catch (e) {
      toast.error(getErrorMessage(e, "No se pudo leer el QR"))
    }
  }

  const pasteQr = (event: ClipboardEvent<HTMLInputElement>) => {
    const image = [...event.clipboardData.files].find((file) => file.type.startsWith("image/"))
    if (!image) return
    event.preventDefault()
    void readQr(image)
  }

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
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Input
                  id="credential-secret" type={showSecret ? "text" : "password"} value={secret} onChange={(e) => setSecret(e.target.value)}
                  required={!editing} maxLength={2000} autoComplete="new-password" className="pr-9 mono"
                  placeholder={editing ? "Déjala vacía para no cambiarla" : undefined}
                />
                <button
                  type="button" className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  aria-label={showSecret ? "Ocultar contraseña" : "Ver contraseña"} onClick={() => setShowSecret((v) => !v)}
                >
                  {showSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <Button type="button" variant="outline" onClick={() => generate()}>
                <Wand2 className="h-4 w-4 mr-1" /> Generar
              </Button>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              <label className="flex items-center gap-1">
                Longitud
                <select
                  className="rounded border border-input bg-background px-1 py-0.5" value={length} aria-label="Longitud de la contraseña generada"
                  onChange={(e) => generate({ length: Number(e.target.value) })}
                >
                  {GENERATOR_LENGTHS.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </label>
              <label className="flex items-center gap-1">
                <input type="checkbox" checked={symbols} onChange={(e) => generate({ symbols: e.target.checked })} />
                Con símbolos
              </label>
              <span>Se genera en tu navegador; sin parecidas (l, I, O, 0, 1).</span>
            </div>
          </div>
          <div className="space-y-1">
            <Label htmlFor="credential-totp">Código 2FA (opcional)</Label>
            {totpMode === "keep" ? (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground">Tiene la clave del autenticador guardada.</span>
                <Button type="button" size="sm" variant="outline" onClick={() => setTotpMode("change")}>Cambiar</Button>
                <Button type="button" size="sm" variant="ghost" className="text-destructive" onClick={() => setTotpMode("remove")}>Quitar</Button>
              </div>
            ) : totpMode === "remove" ? (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-destructive">Se quitará el código 2FA al guardar.</span>
                <Button type="button" size="sm" variant="ghost" onClick={() => setTotpMode("keep")}>Deshacer</Button>
              </div>
            ) : (
              <>
                <div className="flex gap-2">
                  <Input
                    id="credential-totp" type="password" value={totp} onChange={(e) => setTotp(e.target.value)} onPaste={pasteQr}
                    maxLength={2000} autoComplete="off" className="mono flex-1"
                    placeholder={canReadQr ? "Clave, enlace otpauth:// o pega una captura del QR" : "Clave o enlace otpauth://"}
                  />
                  {canReadQr && (
                    <label className="inline-flex items-center gap-1 rounded-md border border-input px-3 text-sm cursor-pointer hover:bg-accent">
                      <QrCode className="h-4 w-4" /> QR
                      <input type="file" accept="image/*" className="sr-only" aria-label="Leer el QR desde una imagen"
                        onChange={(e) => { void readQr(e.target.files?.[0]); e.target.value = "" }} />
                    </label>
                  )}
                </div>
                <p className="text-[11px] text-muted-foreground">
                  La que da la web al activar la verificación en dos pasos (debajo del QR, "¿no puedes escanearlo?"). Se guarda cifrada y desde aquí cualquiera con este acceso podrá ver el código.
                  {editing && credential?.has_totp && (
                    <> <button type="button" className="underline" onClick={() => { setTotp(""); setTotpMode("keep") }}>Mantener la actual</button></>
                  )}
                </p>
              </>
            )}
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
            {notesLoaded ? (
              <Textarea id="credential-notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} maxLength={5000} />
            ) : (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-muted-foreground">Tiene notas guardadas.</span>
                <Button type="button" size="sm" variant="outline" disabled={loadingNotes} onClick={() => void loadNotes()}>
                  Ver y editar
                </Button>
              </div>
            )}
            <p className="text-[11px] text-muted-foreground">Se guardan cifradas, como la contraseña. Abrirlas queda en el registro.</p>
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
  totp: "Pidió el código 2FA",
  notes: "Abrió las notas",
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
