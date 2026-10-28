import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { usersApi } from "@/lib/api"
import { credentialsApi, type CredentialExposure } from "@/lib/credentials-api"
import { parseApiInstant } from "@/lib/dates"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { CREDENTIALS_KEY } from "./credential-dialogs"

function when(value: string) {
  return parseApiInstant(value).toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" })
}

function status(row: CredentialExposure) {
  if (row.needs_rotation) return { text: `La vio el ${when(row.last_seen_at!)} · cambia la contraseña`, tone: "text-destructive" }
  if (row.last_seen_at) return { text: `La vio el ${when(row.last_seen_at)} · ya cambiada el ${when(row.secret_changed_at)}`, tone: "text-muted-foreground" }
  return { text: "No la llegó a abrir", tone: "text-muted-foreground" }
}

/**
 * Salida de alguien (sólo admin): qué accesos vio o todavía puede ver una
 * persona, cuáles hay que rotar porque la contraseña no ha cambiado desde que
 * la vio, y quitarle de golpe todo lo que tenía compartido.
 */
export function CredentialOffboardingDialog({ onOpenChange, onEdit }: {
  onOpenChange: (open: boolean) => void
  onEdit: (credentialId: number) => void
}) {
  const qc = useQueryClient()
  const [personId, setPersonId] = useState<number | null>(null)
  const [confirming, setConfirming] = useState(false)
  const { data: users = [] } = useQuery({ queryKey: ["users", "all"], queryFn: usersApi.listAll })
  const exposure = useQuery({
    queryKey: [...CREDENTIALS_KEY, "exposure", personId],
    queryFn: () => credentialsApi.exposure(personId!),
    enabled: personId !== null,
  })
  const rows = exposure.data ?? []
  const toRotate = rows.filter((row) => row.needs_rotation).length
  const shared = rows.filter((row) => row.shared_with_them).length
  const person = users.find((u) => u.id === personId)

  const revoke = useMutation({
    mutationFn: () => credentialsApi.revokeShares(personId!),
    onSuccess: ({ removed }) => {
      void qc.invalidateQueries({ queryKey: CREDENTIALS_KEY })
      toast.success(`Quitado de ${removed} ${removed === 1 ? "acceso" : "accesos"}`)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Salida de alguien</DialogTitle>
      </DialogHeader>
      <DialogContent>
        <div className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="offboarding-user">Persona</Label>
            <Select id="offboarding-user" value={personId ?? ""} onChange={(e) => setPersonId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Elige a quién</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.full_name}{u.is_active ? "" : " (desactivado)"}</option>)}
            </Select>
          </div>
          {personId !== null && exposure.isSuccess && (rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">No vio ni tiene ningún acceso.</p>
          ) : (
            <>
              <p className="text-sm">
                <strong>{rows.length}</strong> {rows.length === 1 ? "acceso" : "accesos"} · <strong className={toRotate ? "text-destructive" : undefined}>{toRotate}</strong> por cambiar la contraseña
              </p>
              <ul className="max-h-80 divide-y divide-border overflow-auto rounded-md border border-border">
                {rows.map((row) => {
                  const state = status(row)
                  return (
                    <li key={row.id} className="flex items-center gap-3 p-2 text-sm">
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium">{row.name}{row.client_name ? <span className="font-normal text-muted-foreground"> · {row.client_name}</span> : null}</p>
                        <p className={`text-xs ${state.tone}`}>
                          {state.text}
                          {row.shared_with_them ? " · compartido con esta persona" : ""}
                          {row.created_by_them ? " · lo creó" : ""}
                        </p>
                      </div>
                      {row.needs_rotation && (
                        <Button type="button" size="sm" variant="outline" onClick={() => onEdit(row.id)}>Cambiar</Button>
                      )}
                    </li>
                  )
                })}
              </ul>
            </>
          ))}
        </div>
      </DialogContent>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cerrar</Button>
        {shared > 0 && (
          <Button type="button" variant="destructive" disabled={revoke.isPending} onClick={() => setConfirming(true)}>
            Quitarle los {shared} compartidos
          </Button>
        )}
      </DialogFooter>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={`¿Quitar a ${person?.full_name ?? "esta persona"} de ${shared} ${shared === 1 ? "acceso" : "accesos"}?`}
        description="Deja de verlos en Accesos. Los que creó siguen a su nombre. Cambiar las contraseñas que vio es aparte."
        confirmLabel="Quitar"
        onConfirm={() => revoke.mutate()}
      />
    </Dialog>
  )
}
