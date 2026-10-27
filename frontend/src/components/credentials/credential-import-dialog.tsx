import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ShieldCheck, Upload } from "lucide-react"
import { clientsApi } from "@/lib/api"
import { credentialsApi, type ImportSource } from "@/lib/credentials-api"
import {
  MAX_IMPORT_ROWS,
  readExport,
  selectedByDefault,
  toImportItem,
  type ParsedExport,
} from "@/lib/credential-import"
import { useAuth } from "@/context/auth-context"
import { getErrorMessage } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { CREDENTIALS_KEY } from "./credential-dialogs"

const SOURCE_LABELS: Record<ImportSource, string> = {
  "1password": "1Password", bitwarden: "Bitwarden", chrome: "Chrome", csv: "CSV",
}

function host(url: string | null): string {
  if (!url) return ""
  try {
    return new URL(/^[a-z][a-z0-9+.-]*:/i.test(url) ? url : `https://${url}`).host
  } catch {
    return url
  }
}

/**
 * Importar desde el CSV de 1Password, Bitwarden o Chrome. El fichero se lee
 * aquí; al servidor sólo van las filas marcadas, de una vez y todo o nada.
 */
export function CredentialImportDialog({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
  const qc = useQueryClient()
  const { user, hasPermission } = useAuth()
  const [parsed, setParsed] = useState<ParsedExport | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [clientId, setClientId] = useState<number | null>(null)
  const [shareWith, setShareWith] = useState<Set<number>>(new Set())
  const canPickClient = hasPermission("clients")

  // Hace falta la lista para marcar los repetidos: hasta tenerla no se elige fichero.
  const { data: existing = [], isSuccess: existingLoaded } = useQuery({
    queryKey: [...CREDENTIALS_KEY, {}], queryFn: () => credentialsApi.list({}),
  })
  const { data: clients = [] } = useQuery({
    queryKey: ["clients-all", "active"], queryFn: () => clientsApi.listAll("active"), enabled: canPickClient,
  })
  const { data: users = [] } = useQuery({ queryKey: ["credentials", "shareable-users"], queryFn: credentialsApi.shareableUsers })
  const others = users.filter((u) => u.id !== user?.id)

  const rows = useMemo(() => parsed?.rows ?? [], [parsed])
  const chosen = rows.filter((row) => selected.has(row.line))
  const tooMany = chosen.length > MAX_IMPORT_ROWS

  const readFile = async (file: File | undefined) => {
    if (!file) return
    setFileError(null)
    try {
      const result = readExport(await file.text(), existing)
      setParsed(result)
      setSelected(new Set(result.rows.filter(selectedByDefault).map((row) => row.line)))
    } catch (e) {
      setParsed(null)
      setFileError(getErrorMessage(e, "No se pudo leer el fichero"))
    }
  }

  const save = useMutation({
    mutationFn: () => credentialsApi.importMany(
      parsed!.source, chosen.map((row) => toImportItem(row, clientId)), [...shareWith],
    ),
    onSuccess: ({ created }) => {
      void qc.invalidateQueries({ queryKey: CREDENTIALS_KEY })
      toast.success(`${created} ${created === 1 ? "acceso importado" : "accesos importados"}. Borra el CSV: lleva las contraseñas sin cifrar.`)
      setParsed(null)
      onOpenChange(false)
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const toggle = (line: number) => setSelected((prev) => {
    const next = new Set(prev)
    if (next.has(line)) next.delete(line)
    else next.add(line)
    return next
  })
  const importable = rows.filter((row) => !row.problem)
  const allChosen = importable.length > 0 && importable.every((row) => selected.has(row.line))

  return (
    <Dialog open onOpenChange={(open) => { if (!open) setParsed(null); onOpenChange(open) }}>
      <DialogHeader>
        <DialogTitle>Importar accesos</DialogTitle>
      </DialogHeader>
      <DialogContent>
        {!parsed ? (
          <div className="space-y-3 text-sm">
            <p>
              Exporta tus contraseñas a CSV y elige el fichero. En <strong>1Password</strong>: Archivo → Exportar →
              tu cuenta → formato CSV. También sirven las exportaciones de <strong>Bitwarden</strong> y de <strong>Chrome</strong>.
            </p>
            <p className="text-muted-foreground">
              El fichero se lee en tu navegador: sólo se envían los accesos que marques, y se guardan cifrados. Los códigos 2FA
              de 1Password vienen incluidos. Cuando termines, borra el CSV.
            </p>
            <label className={`flex w-fit items-center gap-2 rounded-md border border-input px-3 py-2 ${existingLoaded ? "cursor-pointer hover:bg-accent" : "opacity-50"}`}>
              <Upload className="h-4 w-4" /> {existingLoaded ? "Elegir fichero CSV" : "Cargando tus accesos…"}
              <input type="file" accept=".csv,text/csv" className="sr-only" aria-label="Fichero CSV de contraseñas"
                disabled={!existingLoaded} onChange={(e) => { void readFile(e.target.files?.[0]); e.target.value = "" }} />
            </label>
            {fileError && <p role="alert" className="text-destructive">{fileError}</p>}
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm">
              <strong>{rows.length}</strong> filas de {SOURCE_LABELS[parsed.source]} · <strong>{chosen.length}</strong> marcadas.
              {" "}Las repetidas, archivadas o sin contraseña salen sin marcar.
            </p>
            <div className="max-h-72 overflow-auto rounded-md border border-border">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-background text-xs text-muted-foreground">
                  <tr>
                    <th className="p-2 text-left">
                      <input type="checkbox" aria-label="Marcar todas" checked={allChosen}
                        onChange={(e) => setSelected(new Set(e.target.checked ? importable.map((row) => row.line) : []))} />
                    </th>
                    <th className="p-2 text-left font-medium">Acceso</th>
                    <th className="p-2 text-left font-medium"><span className="sr-only">Estado</span></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {rows.map((row) => (
                    <tr key={row.line} className={row.problem ? "text-muted-foreground" : undefined}>
                      <td className="p-2">
                        <input type="checkbox" aria-label={`Importar ${row.name}`} disabled={!!row.problem}
                          checked={selected.has(row.line)} onChange={() => toggle(row.line)} />
                      </td>
                      <td className="p-2 max-w-0 w-full">
                        <p className="truncate" title={row.name}>{row.name}</p>
                        <p className="truncate text-xs text-muted-foreground">
                          {[row.username, host(row.url)].filter(Boolean).join(" · ")}
                        </p>
                      </td>
                      <td className="p-2 whitespace-nowrap text-xs text-right">
                        {row.totp && <span className="inline-flex items-center gap-0.5 mr-2"><ShieldCheck className="h-3 w-3" /> 2FA</span>}
                        {row.problem ?? (row.duplicate ? "Ya existe" : row.archived ? "Archivado" : "")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {tooMany && <p role="alert" className="text-sm text-destructive">Como mucho {MAX_IMPORT_ROWS} de una vez: desmarca algunas e importa el resto después.</p>}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {canPickClient && (
                <div className="space-y-1">
                  <Label htmlFor="import-client">Cliente (para todas)</Label>
                  <Select id="import-client" value={clientId ?? ""} onChange={(e) => setClientId(e.target.value ? Number(e.target.value) : null)}>
                    <option value="">Sin cliente</option>
                    {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </Select>
                </div>
              )}
              {others.length > 0 && (
                <fieldset className="space-y-1">
                  <legend className="text-sm font-medium">Compartir con</legend>
                  {others.map((u) => (
                    <label key={u.id} className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={shareWith.has(u.id)} onChange={() => setShareWith((prev) => {
                        const next = new Set(prev)
                        if (next.has(u.id)) next.delete(u.id)
                        else next.add(u.id)
                        return next
                      })} />
                      {u.full_name}
                    </label>
                  ))}
                </fieldset>
              )}
            </div>
          </div>
        )}
      </DialogContent>
      <DialogFooter>
        {parsed && <Button type="button" variant="ghost" onClick={() => setParsed(null)}>Otro fichero</Button>}
        <Button type="button" variant="outline" onClick={() => { setParsed(null); onOpenChange(false) }}>Cancelar</Button>
        {parsed && (
          <Button type="button" disabled={save.isPending || chosen.length === 0 || tooMany} onClick={() => save.mutate()}>
            {save.isPending ? "Importando…" : `Importar ${chosen.length}`}
          </Button>
        )}
      </DialogFooter>
    </Dialog>
  )
}
