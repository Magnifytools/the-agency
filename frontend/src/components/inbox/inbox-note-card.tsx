import { useState, useRef } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { inboxApi, projectsApi, clientsApi, usersApi } from "@/lib/api"
import { inboxKeys } from "@/lib/query-keys"
import type { InboxNote, AISuggestion } from "@/lib/types"
import { Dialog, DialogHeader, DialogTitle, DialogContent, DialogFooter } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import {
  CheckSquare, X, RefreshCw, Loader2, FolderKanban,
  Users, Clock, Sparkles, ExternalLink, Paperclip, FileText, Image, Trash2,
} from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage, formatTimeAgo } from "@/lib/utils"


const priorityColors: Record<string, string> = {
  urgent: "bg-red-500/10 text-red-500 border-red-500/20",
  high: "bg-orange-500/10 text-orange-500 border-orange-500/20",
  medium: "bg-yellow-500/10 text-yellow-500 border-yellow-500/20",
  low: "bg-green-500/10 text-green-500 border-green-500/20",
}

const priorityLabels: Record<string, string> = {
  urgent: "Urgente",
  high: "Alta",
  medium: "Media",
  low: "Baja",
}

interface Props {
  note: InboxNote
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function InboxNoteCard({ note }: Props) {
  const [convertOpen, setConvertOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()
  const ai = note.ai_suggestion as AISuggestion | null

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: inboxKeys.all() })
    queryClient.invalidateQueries({ queryKey: inboxKeys.count() })
  }

  const uploadMutation = useMutation({
    mutationFn: (file: File) => inboxApi.uploadAttachment(note.id, file),
    onSuccess: () => {
      invalidateAll()
      toast.success("Adjunto subido")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al subir adjunto")),
  })

  const deleteAttachmentMutation = useMutation({
    mutationFn: (attachmentId: number) => inboxApi.deleteAttachment(note.id, attachmentId),
    onSuccess: () => {
      invalidateAll()
      toast.success("Adjunto eliminado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar")),
  })

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) uploadMutation.mutate(file)
    e.target.value = ""
  }

  const { data: projects = [] } = useQuery({
    queryKey: ["projects-active-list"],
    queryFn: () => projectsApi.listAll({ status: "active" }),
    staleTime: 60_000,
  })

  const { data: clients = [] } = useQuery({
    queryKey: ["clients-active-list"],
    queryFn: () => clientsApi.listAll("active"),
    staleTime: 60_000,
  })

  const updateMutation = useMutation({
    mutationFn: (data: { project_id?: number | null; client_id?: number | null }) =>
      inboxApi.update(note.id, data),
    onSuccess: () => invalidateAll(),
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar")),
  })

  const classifyMutation = useMutation({
    mutationFn: () => inboxApi.classify(note.id),
    onSuccess: () => {
      invalidateAll()
      toast.success("Reclasificado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al clasificar")),
  })

  const dismissMutation = useMutation({
    mutationFn: () => inboxApi.dismiss(note.id),
    onSuccess: () => {
      invalidateAll()
      toast.success("Descartado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al descartar")),
  })

  const deleteMutation = useMutation({
    mutationFn: () => inboxApi.delete(note.id),
    onSuccess: () => {
      invalidateAll()
      toast.success("Nota eliminada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar")),
  })

  return (
    <>
      <div className="group p-4 rounded-xl border border-border/50 hover:border-border bg-card/40 hover:bg-card/80 transition-all">
        {/* Header: text + time */}
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap">{note.raw_text}</p>
            {note.link_url && (
              <a href={note.link_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-brand hover:underline mt-1">
                <ExternalLink className="w-3 h-3" />
                {note.link_url.replace(/^https?:\/\//, "").slice(0, 50)}{note.link_url.replace(/^https?:\/\//, "").length > 50 ? "…" : ""}
              </a>
            )}

            {/* Attachments */}
            {note.attachments && note.attachments.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {note.attachments.map((att) => {
                  const isImage = att.mime_type.startsWith("image/")
                  const previewUrl = `/api/inbox/${note.id}/attachments/${att.id}`
                  return (
                    <div key={att.id} className="group/att relative flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-lg bg-muted/50 border border-border/50 hover:border-border transition-colors">
                      {isImage ? (
                        <a href={previewUrl} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-foreground hover:text-brand">
                          <Image className="w-3 h-3 shrink-0" />
                          <span className="truncate max-w-[120px]">{att.name}</span>
                        </a>
                      ) : (
                        <a href={previewUrl} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 text-foreground hover:text-brand">
                          <FileText className="w-3 h-3 shrink-0" />
                          <span className="truncate max-w-[120px]">{att.name}</span>
                        </a>
                      )}
                      <span className="text-muted-foreground">{formatFileSize(att.size_bytes)}</span>
                      <button
                        type="button"
                        className="opacity-0 group-hover/att:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                        onClick={() => deleteAttachmentMutation.mutate(att.id)}
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  )
                })}
              </div>
            )}

            <div className="flex items-center gap-2 mt-2 flex-wrap">
              <span className="text-[10px] text-muted-foreground flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {formatTimeAgo(note.created_at)}
              </span>
              {note.status === "pending" && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground border border-border/50">
                  Pendiente IA...
                </span>
              )}
              {note.status === "processed" && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-green-500/10 text-green-500 border border-green-500/20">
                  Procesado
                </span>
              )}
              {note.status === "dismissed" && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground border border-border/50 line-through">
                  Descartado
                </span>
              )}
            </div>
            {/* Delete button — always visible for any state */}
            <button
              className="shrink-0 mt-1 p-1 rounded text-muted-foreground/40 hover:text-destructive hover:bg-destructive/10 transition-colors"
              title="Eliminar nota"
              onClick={() => {
                if (confirm("¿Eliminar esta nota del inbox?")) {
                  deleteMutation.mutate()
                }
              }}
              disabled={deleteMutation.isPending}
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* AI Suggestion chips */}
        {ai && note.status === "classified" && (
          <div className="mt-3 pt-3 border-t border-border/30">
            <div className="flex items-center gap-1.5 mb-2">
              <Sparkles className="w-3 h-3 text-brand" />
              <span className="text-[10px] font-semibold uppercase tracking-wider text-brand">Sugerencia IA</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {ai.suggested_project?.id && (
                <span className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-lg bg-blue-500/10 text-blue-500 border border-blue-500/20">
                  <FolderKanban className="w-3 h-3" />
                  {ai.suggested_project.name}
                  <span className="opacity-60">{Math.round(ai.suggested_project.confidence * 100)}%</span>
                </span>
              )}
              {ai.suggested_client?.id && (
                <span className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-lg bg-purple-500/10 text-purple-500 border border-purple-500/20">
                  <Users className="w-3 h-3" />
                  {ai.suggested_client.name}
                  <span className="opacity-60">{Math.round(ai.suggested_client.confidence * 100)}%</span>
                </span>
              )}
              {ai.suggested_priority && (
                <span className={`inline-flex items-center text-[11px] px-2 py-1 rounded-lg border ${priorityColors[ai.suggested_priority] ?? priorityColors.medium}`}>
                  {priorityLabels[ai.suggested_priority] ?? ai.suggested_priority}
                </span>
              )}
            </div>
            {ai.suggested_title && (
              <p className="mt-1.5 text-xs text-muted-foreground italic">
                &quot;{ai.suggested_title}&quot;
              </p>
            )}
          </div>
        )}

        {/* Assignment + Actions */}
        {(note.status === "classified" || note.status === "pending") && (
          <div className="mt-3 pt-3 border-t border-border/30 space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] font-medium text-muted-foreground mb-1 block">Cliente</label>
                <Select
                  value={String(note.client_id ?? "")}
                  onChange={(e) => {
                    const val = e.target.value
                    updateMutation.mutate({ client_id: val ? Number(val) : null })
                  }}
                  className="text-xs"
                >
                  <option value="">Sin cliente</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </Select>
              </div>
              <div>
                <label className="text-[10px] font-medium text-muted-foreground mb-1 block">Proyecto</label>
                <Select
                  value={String(note.project_id ?? "")}
                  onChange={(e) => {
                    const val = e.target.value
                    updateMutation.mutate({ project_id: val ? Number(val) : null })
                  }}
                  className="text-xs"
                >
                  <option value="">Sin proyecto</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </Select>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="default"
                className="h-7 text-xs gap-1.5 px-3"
                onClick={() => setConvertOpen(true)}
              >
                <CheckSquare className="w-3 h-3" />
                Crear tarea
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-xs gap-1.5 px-3"
                onClick={() => classifyMutation.mutate()}
                disabled={classifyMutation.isPending}
              >
                {classifyMutation.isPending ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <RefreshCw className="w-3 h-3" />
                )}
                {note.status === "pending" ? "Clasificar IA" : "Reclasificar IA"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-xs gap-1.5 px-3 text-muted-foreground hover:text-destructive"
                onClick={() => dismissMutation.mutate()}
                disabled={dismissMutation.isPending}
              >
                {dismissMutation.isPending ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <X className="w-3 h-3" />
                )}
                Descartar
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-xs gap-1.5 px-3 ml-auto"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploadMutation.isPending}
              >
                {uploadMutation.isPending ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Paperclip className="w-3 h-3" />
                )}
                Adjuntar
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                onChange={handleFileChange}
              />
            </div>
          </div>
        )}
      </div>

      {/* Convert to task dialog */}
      {convertOpen && (
        <ConvertToTaskDialog
          note={note}
          open={convertOpen}
          onOpenChange={setConvertOpen}
          onConverted={invalidateAll}
        />
      )}
    </>
  )
}


// --- Convert to Task Dialog ---

function ConvertToTaskDialog({
  note,
  open,
  onOpenChange,
  onConverted,
}: {
  note: InboxNote
  open: boolean
  onOpenChange: (open: boolean) => void
  onConverted: () => void
}) {
  const ai = note.ai_suggestion as AISuggestion | null
  const [title, setTitle] = useState(ai?.suggested_title ?? note.raw_text.slice(0, 200))
  const [projectId, setProjectId] = useState<string>(
    String(note.project_id ?? ai?.suggested_project?.id ?? "")
  )
  const [clientId, setClientId] = useState<string>(
    String(note.client_id ?? ai?.suggested_client?.id ?? "")
  )
  const [priority, setPriority] = useState(ai?.suggested_priority ?? "medium")

  const { data: projects = [] } = useQuery({
    queryKey: ["projects-active-list"],
    queryFn: () => projectsApi.listAll({ status: "active" }),
    staleTime: 60_000,
  })

  const { data: clients = [] } = useQuery({
    queryKey: ["clients-active-list"],
    queryFn: () => clientsApi.listAll("active"),
    staleTime: 60_000,
  })

  const { data: users = [] } = useQuery({
    queryKey: ["users-list-all"],
    queryFn: () => usersApi.listAll(),
    staleTime: 60_000,
  })

  const [assignedTo, setAssignedTo] = useState<string>("")

  const convertMutation = useMutation({
    mutationFn: () =>
      inboxApi.convertToTask(note.id, {
        title: title.trim() || undefined,
        project_id: projectId ? Number(projectId) : undefined,
        client_id: clientId ? Number(clientId) : undefined,
        priority,
        assigned_to: assignedTo ? Number(assignedTo) : undefined,
      }),
    onSuccess: (data) => {
      onOpenChange(false)
      onConverted()
      toast.success(`Tarea #${data.task_id} creada`, { icon: "✅" })
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear tarea")),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <div className="p-1.5 bg-brand/10 rounded-lg">
            <CheckSquare className="w-4 h-4 text-brand" />
          </div>
          Crear tarea desde nota
        </DialogTitle>
      </DialogHeader>

      <DialogContent>
        <div className="p-3 rounded-lg bg-muted/50 border border-border/50 text-xs text-muted-foreground">
          {note.raw_text}
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">Título</label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Título de la tarea"
              className="text-sm"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">Cliente</label>
              <Select value={clientId} onChange={(e) => setClientId(e.target.value)} className="text-sm">
                <option value="">Sin cliente</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </Select>
            </div>

            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">Proyecto</label>
              <Select value={projectId} onChange={(e) => setProjectId(e.target.value)} className="text-sm">
                <option value="">Sin proyecto</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </Select>
            </div>

            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">Prioridad</label>
              <Select value={priority} onChange={(e) => setPriority(e.target.value as typeof priority)} className="text-sm">
                <option value="low">Baja</option>
                <option value="medium">Media</option>
                <option value="high">Alta</option>
                <option value="urgent">Urgente</option>
              </Select>
            </div>

            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">Asignar a</label>
              <Select value={assignedTo} onChange={(e) => setAssignedTo(e.target.value)} className="text-sm">
                <option value="">Yo</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>{u.full_name}</option>
                ))}
              </Select>
            </div>
          </div>
        </div>
      </DialogContent>

      <DialogFooter>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>
          Cancelar
        </Button>
        <Button
          onClick={() => {
            if (!clientId) {
              toast.error("Selecciona un cliente antes de crear la tarea")
              return
            }
            convertMutation.mutate()
          }}
          disabled={convertMutation.isPending || !clientId}
          className="gap-2"
        >
          {convertMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <CheckSquare className="h-4 w-4" />
          )}
          Crear tarea
        </Button>
      </DialogFooter>
    </Dialog>
  )
}
