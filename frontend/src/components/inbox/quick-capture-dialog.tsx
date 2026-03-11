import { useState, useRef, useEffect } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { inboxApi, projectsApi, clientsApi } from "@/lib/api"
import { inboxKeys } from "@/lib/query-keys"
import { Dialog, DialogHeader, DialogTitle, DialogContent } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { Select } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Inbox, Link2, Loader2, Zap } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function QuickCaptureDialog({ open, onOpenChange }: Props) {
  const [text, setText] = useState("")
  const [linkUrl, setLinkUrl] = useState("")
  const [clientId, setClientId] = useState<string>("")
  const [projectId, setProjectId] = useState<string>("")
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const queryClient = useQueryClient()

  const { data: clients = [] } = useQuery({
    queryKey: ["clients-active-list"],
    queryFn: () => clientsApi.listAll("active"),
    staleTime: 60_000,
    enabled: open,
  })

  const { data: projects = [] } = useQuery({
    queryKey: ["projects-active-list"],
    queryFn: () => projectsApi.listAll({ status: "active" }),
    staleTime: 60_000,
    enabled: open,
  })

  const createMutation = useMutation({
    mutationFn: (data: { raw_text: string; project_id?: number; client_id?: number; link_url?: string }) =>
      inboxApi.create({ raw_text: data.raw_text, source: "quick_capture", project_id: data.project_id, client_id: data.client_id, link_url: data.link_url }),
    onSuccess: () => {
      setText("")
      setLinkUrl("")
      setClientId("")
      setProjectId("")
      onOpenChange(false)
      queryClient.invalidateQueries({ queryKey: inboxKeys.all() })
      queryClient.invalidateQueries({ queryKey: inboxKeys.count() })
      toast.success("Capturado en el Inbox", { icon: "⚡" })
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al capturar")),
  })

  useEffect(() => {
    if (open) {
      setText("")
      setLinkUrl("")
      setClientId("")
      setProjectId("")
      setTimeout(() => textareaRef.current?.focus(), 100)
    }
  }, [open])

  const handleSubmit = () => {
    const trimmed = text.trim()
    if (!trimmed) return
    createMutation.mutate({
      raw_text: trimmed,
      client_id: clientId ? Number(clientId) : undefined,
      project_id: projectId ? Number(projectId) : undefined,
      link_url: linkUrl.trim() || undefined,
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <div className="p-1.5 bg-brand/10 rounded-lg">
            <Inbox className="w-4 h-4 text-brand" />
          </div>
          Captura rápida
          <kbd className="ml-auto text-[10px] font-mono text-muted-foreground/60 bg-muted px-1.5 py-0.5 rounded border border-border">
            ⌘J
          </kbd>
        </DialogTitle>
      </DialogHeader>

      <DialogContent>
        <Textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Escribe lo que necesitas capturar... La IA lo clasificará automáticamente."
          className="min-h-[100px] rounded-xl resize-none text-sm"
          disabled={createMutation.isPending}
        />

        <div className="flex items-center gap-2">
          <Link2 className="w-4 h-4 text-muted-foreground shrink-0" />
          <Input
            value={linkUrl}
            onChange={(e) => setLinkUrl(e.target.value)}
            placeholder="Enlace a Drive, Docs, etc. (opcional)"
            className="text-sm h-8"
            disabled={createMutation.isPending}
            type="url"
          />
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Select
            value={clientId}
            onChange={(e) => { setClientId(e.target.value); setProjectId("") }}
            className="flex-1 min-w-[140px] text-sm"
            disabled={createMutation.isPending}
          >
            <option value="">Cliente (opcional)</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </Select>
          <Select
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className="flex-1 min-w-[140px] text-sm"
            disabled={createMutation.isPending}
          >
            <option value="">Proyecto (opcional)</option>
            {(clientId ? projects.filter((p) => String(p.client_id) === clientId) : projects).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}{!clientId && p.client_name ? ` — ${p.client_name}` : ""}
              </option>
            ))}
          </Select>

          <Button
            onClick={handleSubmit}
            disabled={!text.trim() || createMutation.isPending}
            className="gap-2 px-5"
          >
            {createMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Zap className="h-4 w-4" />
            )}
            Capturar
          </Button>
        </div>

        <div className="flex items-center justify-between text-[11px] text-muted-foreground/60">
          <span className="flex items-center gap-1">
            <Zap className="w-3 h-3" />
            La IA clasificará la nota automáticamente
          </span>
          <kbd className="font-mono bg-muted px-1.5 py-0.5 rounded border border-border">
            ⌘↩ para enviar
          </kbd>
        </div>
      </DialogContent>
    </Dialog>
  )
}
