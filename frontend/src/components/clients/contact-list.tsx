import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Plus, Pencil, Trash2, Star, Mail, Phone, User, Linkedin, Building2 } from "lucide-react"
import { toast } from "sonner"
import { contactsApi } from "@/lib/api"
import type { ClientContact, ClientContactCreate } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { getErrorMessage } from "@/lib/utils"

interface Props {
  clientId: number
}

export function ContactList({ clientId }: Props) {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<ClientContact | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ClientContact | null>(null)

  const { data: contacts = [], isLoading } = useQuery({
    queryKey: ["client-contacts", clientId],
    queryFn: () => contactsApi.list(clientId),
  })

  const createMut = useMutation({
    mutationFn: (data: ClientContactCreate) => contactsApi.create(clientId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client-contacts", clientId] })
      setShowForm(false)
      toast.success("Contacto creado")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ClientContactCreate> }) =>
      contactsApi.update(clientId, id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client-contacts", clientId] })
      setEditing(null)
      toast.success("Contacto actualizado")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => contactsApi.delete(clientId, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["client-contacts", clientId] })
      setDeleteTarget(null)
      toast.success("Contacto eliminado")
    },
    onError: (e) => toast.error(getErrorMessage(e)),
  })

  if (isLoading) return <p className="text-muted-foreground text-sm">Cargando contactos...</p>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Contactos</h3>
        <Button size="sm" onClick={() => { setEditing(null); setShowForm(true) }}>
          <Plus className="h-4 w-4 mr-1" /> Nuevo contacto
        </Button>
      </div>

      {contacts.length === 0 ? (
        <p className="text-muted-foreground text-sm py-8 text-center">
          No hay contactos registrados para este cliente
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {contacts.map((c) => (
            <Card key={c.id} className="relative">
              <CardContent className="p-4">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2 min-w-0">
                    <div className="h-9 w-9 rounded-full bg-muted flex items-center justify-center shrink-0">
                      <User className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium truncate">{c.name}</span>
                        {c.is_primary && (
                          <Badge variant="warning" className="text-[10px] px-1.5 py-0">
                            <Star className="h-3 w-3 mr-0.5" />Principal
                          </Badge>
                        )}
                      </div>
                      {c.position && (
                        <p className="text-xs text-muted-foreground">{c.position}</p>
                      )}
                    </div>
                  </div>
                  <div className="flex gap-1 shrink-0">
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => { setEditing(c); setShowForm(true) }}>
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => setDeleteTarget(c)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
                {(c.department || c.preferred_channel) && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {c.department && (
                      <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                        <Building2 className="h-3 w-3 mr-0.5" />{c.department}
                      </Badge>
                    )}
                    {c.preferred_channel && (
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                        {c.preferred_channel}
                      </Badge>
                    )}
                    {c.language && (
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0">
                        {c.language}
                      </Badge>
                    )}
                  </div>
                )}
                <div className="mt-2 space-y-1">
                  {c.email && (
                    <a href={`mailto:${c.email}`} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
                      <Mail className="h-3 w-3" />{c.email}
                    </a>
                  )}
                  {c.phone && (
                    <a href={`tel:${c.phone}`} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
                      <Phone className="h-3 w-3" />{c.phone}
                    </a>
                  )}
                  {c.linkedin_url && (
                    <a href={c.linkedin_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
                      <Linkedin className="h-3 w-3" />LinkedIn
                    </a>
                  )}
                </div>
                {c.notes && (
                  <p className="mt-2 text-xs text-muted-foreground border-t pt-2">{c.notes}</p>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Create/Edit Dialog */}
      <Dialog open={showForm} onOpenChange={setShowForm}>
        <DialogHeader>
          <DialogTitle>{editing ? "Editar contacto" : "Nuevo contacto"}</DialogTitle>
        </DialogHeader>
        <ContactForm
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
        title="Eliminar contacto"
        description={`Se eliminara el contacto "${deleteTarget?.name}". Esta accion no se puede deshacer.`}
        onConfirm={() => deleteTarget && deleteMut.mutate(deleteTarget.id)}
      />
    </div>
  )
}

function ContactForm({
  initial,
  onSubmit,
  loading,
  onCancel,
}: {
  initial: ClientContact | null
  onSubmit: (data: ClientContactCreate) => void
  loading: boolean
  onCancel: () => void
}) {
  const [name, setName] = useState(initial?.name ?? "")
  const [email, setEmail] = useState(initial?.email ?? "")
  const [phone, setPhone] = useState(initial?.phone ?? "")
  const [position, setPosition] = useState(initial?.position ?? "")
  const [department, setDepartment] = useState(initial?.department ?? "")
  const [preferredChannel, setPreferredChannel] = useState(initial?.preferred_channel ?? "")
  const [language, setLanguage] = useState(initial?.language ?? "")
  const [linkedinUrl, setLinkedinUrl] = useState(initial?.linkedin_url ?? "")
  const [isPrimary, setIsPrimary] = useState(initial?.is_primary ?? false)
  const [notes, setNotes] = useState(initial?.notes ?? "")

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    onSubmit({
      name: name.trim(),
      email: email.trim() || null,
      phone: phone.trim() || null,
      position: position.trim() || null,
      department: department.trim() || null,
      preferred_channel: preferredChannel.trim() || null,
      language: language.trim() || null,
      linkedin_url: linkedinUrl.trim() || null,
      is_primary: isPrimary,
      notes: notes.trim() || null,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 p-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label>Nombre *</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ana Garcia" required />
        </div>
        <div>
          <Label>Cargo</Label>
          <Input value={position} onChange={(e) => setPosition(e.target.value)} placeholder="Marketing Manager" />
        </div>
        <div>
          <Label>Email</Label>
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="ana@empresa.com" />
        </div>
        <div>
          <Label>Telefono</Label>
          <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+34 600 000 000" />
        </div>
        <div>
          <Label>Departamento</Label>
          <Input value={department} onChange={(e) => setDepartment(e.target.value)} placeholder="Marketing" />
        </div>
        <div>
          <Label>Canal preferido</Label>
          <Input value={preferredChannel} onChange={(e) => setPreferredChannel(e.target.value)} placeholder="Email, WhatsApp, Slack..." />
        </div>
        <div>
          <Label>Idioma</Label>
          <Input value={language} onChange={(e) => setLanguage(e.target.value)} placeholder="Espanol, Ingles..." />
        </div>
        <div>
          <Label>LinkedIn</Label>
          <Input value={linkedinUrl} onChange={(e) => setLinkedinUrl(e.target.value)} placeholder="https://linkedin.com/in/..." />
        </div>
      </div>
      <div>
        <Label>Notas</Label>
        <Input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notas sobre este contacto..." />
      </div>
      <label className="flex items-center gap-2 text-sm cursor-pointer">
        <input type="checkbox" checked={isPrimary} onChange={(e) => setIsPrimary(e.target.checked)} className="rounded" />
        Contacto principal
      </label>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>Cancelar</Button>
        <Button type="submit" disabled={loading || !name.trim()}>
          {loading ? "Guardando..." : initial ? "Guardar" : "Crear"}
        </Button>
      </div>
    </form>
  )
}
