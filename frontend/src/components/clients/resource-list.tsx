import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus, Pencil, Trash2, ExternalLink, Sheet, FileText, Mail, UserCircle, BarChart2, Link2 } from "lucide-react"
import { toast } from "sonner"
import { resourcesApi } from "@/lib/api"
import type { ClientResource, ClientResourceCreate, ResourceType } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { getErrorMessage } from "@/lib/utils"

const RESOURCE_TYPES: { value: ResourceType; label: string; icon: typeof Sheet }[] = [
  { value: "spreadsheet", label: "Hoja de calculo", icon: Sheet },
  { value: "document", label: "Documento", icon: FileText },
  { value: "email", label: "Email", icon: Mail },
  { value: "account", label: "Cuenta", icon: UserCircle },
  { value: "dashboard", label: "Dashboard", icon: BarChart2 },
  { value: "other", label: "Otro", icon: Link2 },
]

function getResourceIcon(type: ResourceType) {
  const found = RESOURCE_TYPES.find((t) => t.value === type)
  return found?.icon ?? Link2
}

function getResourceLabel(type: ResourceType) {
  return RESOURCE_TYPES.find((t) => t.value === type)?.label ?? type
}

interface Props {
  clientId: number
}

export function ResourceList({ clientId }: Props) {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<ClientResource | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ClientResource | null>(null)

  const { data: resources = [], isLoading } = useQuery({
    queryKey: ["client-resources", clientId],
    queryFn: () => resourcesApi.list(clientId),
  })

  const createMut = useMutation({
    mutationFn: (data: ClientResourceCreate) => resourcesApi.create(clientId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client-resources", clientId] })
      setShowForm(false)
      toast.success("Recurso creado")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ClientResourceCreate> }) =>
      resourcesApi.update(clientId, id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client-resources", clientId] })
      setEditing(null)
      setShowForm(false)
      toast.success("Recurso actualizado")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => resourcesApi.delete(clientId, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client-resources", clientId] })
      setDeleteTarget(null)
      toast.success("Recurso eliminado")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  if (isLoading) return <p className="text-muted-foreground text-sm">Cargando recursos...</p>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Recursos y enlaces</h3>
        <Button size="sm" onClick={() => { setEditing(null); setShowForm(true) }}>
          <Plus className="h-4 w-4 mr-1" /> Nuevo recurso
        </Button>
      </div>

      {resources.length === 0 ? (
        <p className="text-muted-foreground text-sm py-8 text-center">
          No hay recursos registrados. Anade enlaces a sheets, cuentas, dashboards, etc.
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {resources.map((r) => {
            const Icon = getResourceIcon(r.resource_type)
            return (
              <Card key={r.id} className="relative">
                <CardContent className="p-4">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="h-9 w-9 rounded-lg bg-muted flex items-center justify-center shrink-0">
                        <Icon className="h-4 w-4 text-muted-foreground" />
                      </div>
                      <div className="min-w-0">
                        <span className="font-medium truncate block">{r.label}</span>
                        <Badge variant="secondary" className="text-[10px] mt-0.5">
                          {getResourceLabel(r.resource_type)}
                        </Badge>
                      </div>
                    </div>
                    <div className="flex gap-1 shrink-0">
                      <a href={r.url} target="_blank" rel="noopener noreferrer">
                        <Button variant="ghost" size="icon" className="h-7 w-7">
                          <ExternalLink className="h-3.5 w-3.5" />
                        </Button>
                      </a>
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => { setEditing(r); setShowForm(true) }}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => setDeleteTarget(r)}>
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                  <a
                    href={r.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-2 text-xs text-brand hover:underline truncate block"
                  >
                    {r.url}
                  </a>
                  {r.notes && (
                    <p className="mt-2 text-xs text-muted-foreground border-t pt-2">{r.notes}</p>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* Create/Edit Dialog */}
      <Dialog open={showForm} onOpenChange={setShowForm}>
        <DialogHeader>
          <DialogTitle>{editing ? "Editar recurso" : "Nuevo recurso"}</DialogTitle>
        </DialogHeader>
        <ResourceForm
          initial={editing}
          onSubmit={(data) => {
            if (editing) {
              updateMut.mutate({ id: editing.id, data })
            } else {
              createMut.mutate(data)
            }
          }}
          loading={createMut.isPending || updateMut.isPending}
          onCancel={() => setShowForm(false)}
        />
      </Dialog>

      {/* Delete Confirm */}
      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(o) => !o && setDeleteTarget(null)}
        title="Eliminar recurso"
        description={`Se eliminara el recurso "${deleteTarget?.label}". Esta accion no se puede deshacer.`}
        onConfirm={() => deleteTarget && deleteMut.mutate(deleteTarget.id)}
      />
    </div>
  )
}

function ResourceForm({
  initial,
  onSubmit,
  loading,
  onCancel,
}: {
  initial: ClientResource | null
  onSubmit: (data: ClientResourceCreate) => void
  loading: boolean
  onCancel: () => void
}) {
  const [label, setLabel] = useState(initial?.label ?? "")
  const [url, setUrl] = useState(initial?.url ?? "")
  const [resourceType, setResourceType] = useState<ResourceType>(initial?.resource_type ?? "other")
  const [notes, setNotes] = useState(initial?.notes ?? "")

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!label.trim() || !url.trim()) return
    onSubmit({
      label: label.trim(),
      url: url.trim(),
      resource_type: resourceType,
      notes: notes.trim() || null,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 p-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label>Nombre *</Label>
          <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Reporting Sheet" required />
        </div>
        <div>
          <Label>Tipo</Label>
          <select
            value={resourceType}
            onChange={(e) => setResourceType(e.target.value as ResourceType)}
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            {RESOURCE_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>
      </div>
      <div>
        <Label>URL *</Label>
        <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://docs.google.com/spreadsheets/..." required />
      </div>
      <div>
        <Label>Notas</Label>
        <Input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Descripcion o contexto del recurso..." />
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>Cancelar</Button>
        <Button type="submit" disabled={loading || !label.trim() || !url.trim()}>
          {loading ? "Guardando..." : initial ? "Guardar" : "Crear"}
        </Button>
      </div>
    </form>
  )
}
