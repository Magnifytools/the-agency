import { useState, useEffect, useRef } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { BookOpen, User, Mail, Phone, FileText, Download, Trash2, Upload, File as FileIcon } from "lucide-react"
import { clientsApi, contactsApi } from "@/lib/api"
import type { Client, ClientDocument } from "@/lib/types"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatRelativeDate(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  if (diffDays === 0) return "Hoy"
  if (diffDays === 1) return "Ayer"
  if (diffDays < 7) return `Hace ${diffDays} días`
  if (diffDays < 30) return `Hace ${Math.floor(diffDays / 7)} semanas`
  return date.toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric" })
}

function getMimeIcon(mimeType: string): string {
  if (mimeType.startsWith("image/")) return "🖼️"
  if (mimeType === "application/pdf") return "📄"
  if (mimeType.includes("spreadsheet") || mimeType.includes("excel") || mimeType.includes("csv")) return "📊"
  if (mimeType.includes("word") || mimeType.includes("document")) return "📝"
  if (mimeType.includes("presentation") || mimeType.includes("powerpoint")) return "📊"
  return "📎"
}

interface FichaTabProps {
  client: Client
  onNavigateToContacts?: () => void
}

export function FichaTab({ client, onNavigateToContacts }: FichaTabProps) {
  const queryClient = useQueryClient()
  const [contextValue, setContextValue] = useState(client.context ?? "")
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved">("idle")
  const [deleteDocId, setDeleteDocId] = useState<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    setContextValue(client.context ?? "")
  }, [client.context])

  const updateMut = useMutation({
    mutationFn: (ctx: string) => clientsApi.update(client.id, { context: ctx }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["client-summary", client.id] })
      setSaveStatus("saved")
      setTimeout(() => setSaveStatus("idle"), 2000)
    },
  })

  const handleContextChange = (v: string) => {
    setContextValue(v)
    setSaveStatus("saving")
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      updateMut.mutate(v)
    }, 1500)
  }

  const { data: contacts = [] } = useQuery({
    queryKey: ["client-contacts", client.id],
    queryFn: () => contactsApi.list(client.id),
  })

  const { data: documents = [], isLoading: docsLoading } = useQuery({
    queryKey: ["client-documents", client.id],
    queryFn: () => clientsApi.documents.list(client.id),
  })

  const uploadMut = useMutation({
    mutationFn: ({ file, description }: { file: File; description?: string }) =>
      clientsApi.documents.upload(client.id, file, description),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["client-documents", client.id] })
    },
  })

  const deleteMut = useMutation({
    mutationFn: (docId: number) => clientsApi.documents.delete(client.id, docId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["client-documents", client.id] })
    },
  })

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const description = window.prompt("Descripción del documento (opcional):")
    await uploadMut.mutateAsync({ file, description: description || undefined })
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  const primaryContact = contacts.find((c) => c.is_primary) ?? null

  return (
    <div className="space-y-6">
      {/* Sección 1: Historia y contexto */}
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 pb-3">
          <BookOpen className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-base">Historia y contexto</CardTitle>
          <span className="ml-auto text-xs text-muted-foreground">
            {saveStatus === "saving" ? "Guardando..." : saveStatus === "saved" ? "Guardado ✓" : ""}
          </span>
        </CardHeader>
        <CardContent>
          <textarea
            className="w-full min-h-[220px] text-sm bg-background border border-input rounded-md p-3 resize-y focus:outline-none focus:ring-2 focus:ring-ring"
            value={contextValue}
            onChange={(e) => handleContextChange(e.target.value)}
            placeholder="Cómo llegó el cliente, quién tomó la decisión, qué problemas tenía, qué se ha prometido, hitos importantes, acuerdos especiales, historial de facturación relevante..."
          />
        </CardContent>
      </Card>

      {/* Sección 2: Interlocutor principal */}
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 pb-3">
          <User className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-base">Interlocutor principal</CardTitle>
        </CardHeader>
        <CardContent>
          {primaryContact ? (
            <div className="space-y-2 text-sm">
              <p className="font-semibold text-base">{primaryContact.name}</p>
              {primaryContact.position && (
                <p className="text-muted-foreground">{primaryContact.position}</p>
              )}
              <div className="flex flex-col gap-1 mt-2">
                {primaryContact.email && (
                  <div className="flex items-center gap-2">
                    <Mail className="h-3.5 w-3.5 text-muted-foreground" />
                    <a href={`mailto:${primaryContact.email}`} className="text-brand hover:underline">
                      {primaryContact.email}
                    </a>
                  </div>
                )}
                {primaryContact.phone && (
                  <div className="flex items-center gap-2">
                    <Phone className="h-3.5 w-3.5 text-muted-foreground" />
                    <span>{primaryContact.phone}</span>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <p className="text-sm text-muted-foreground">No hay contacto principal definido.</p>
              {onNavigateToContacts && (
                <Button variant="outline" size="sm" onClick={onNavigateToContacts}>
                  Ir a Contactos
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Sección 3: Documentos */}
      <Card>
        <CardHeader className="flex flex-row items-center gap-2 pb-3">
          <FileText className="h-4 w-4 text-muted-foreground" />
          <CardTitle className="text-base">Documentos</CardTitle>
          <div className="ml-auto">
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              onChange={handleFileSelect}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadMut.isPending}
            >
              <Upload className="h-3.5 w-3.5 mr-1.5" />
              {uploadMut.isPending ? "Subiendo..." : "Subir documento"}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {docsLoading ? (
            <p className="text-sm text-muted-foreground">Cargando...</p>
          ) : documents.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground text-sm">
              <FileIcon className="h-8 w-8 mx-auto mb-2 opacity-40" />
              <p>No hay documentos adjuntos.</p>
              <p className="text-xs mt-1">Sube propuestas, contratos, briefs o cualquier archivo relevante.</p>
            </div>
          ) : (
            <ul className="space-y-2">
              {documents.map((doc: ClientDocument) => (
                <li key={doc.id} className="flex items-center gap-3 p-2 rounded-md border hover:bg-muted/30 group">
                  <span className="text-lg">{getMimeIcon(doc.mime_type)}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{doc.name}</p>
                    {doc.description && (
                      <p className="text-xs text-muted-foreground truncate">{doc.description}</p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {formatBytes(doc.size_bytes)} · {formatRelativeDate(doc.created_at)}
                    </p>
                  </div>
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <a
                      href={clientsApi.documents.downloadUrl(client.id, doc.id)}
                      download={doc.name}
                      title="Descargar"
                    >
                      <Button variant="ghost" size="icon" className="h-7 w-7">
                        <Download className="h-3.5 w-3.5" />
                      </Button>
                    </a>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-destructive hover:text-destructive"
                      onClick={() => setDeleteDocId(doc.id)}
                      title="Eliminar"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Confirm Delete Dialog */}
      <ConfirmDialog
        open={deleteDocId !== null}
        onOpenChange={(open) => !open && setDeleteDocId(null)}
        title="Eliminar documento"
        description="¿Seguro que quieres eliminar este documento? Esta acción no se puede deshacer."
        confirmLabel="Eliminar"
        onConfirm={() => {
          if (deleteDocId !== null) deleteMut.mutate(deleteDocId)
        }}
      />
    </div>
  )
}
