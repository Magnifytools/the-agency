import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { format } from "date-fns"
import { es } from "date-fns/locale"
import { FileText, Sparkles, Send, Eye, Copy, Pencil, Loader2 } from "lucide-react"
import { digestsApi, clientsApi } from "@/lib/api"
import type { Digest, DigestStatus, DigestTone } from "@/lib/types"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import { useNavigate } from "react-router-dom"

const toneLabels: Record<DigestTone, string> = {
  formal: "Formal",
  cercano: "Cercano",
  equipo: "Equipo",
}

export default function DigestsPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [generateOpen, setGenerateOpen] = useState(false)
  const [selectedClientId, setSelectedClientId] = useState<number | "">("")
  const [selectedTone, setSelectedTone] = useState<DigestTone>("cercano")
  const [filterStatus, setFilterStatus] = useState<DigestStatus | "">("")
  const [filterClient, setFilterClient] = useState<number | "">("")
  const [previewDigest, setPreviewDigest] = useState<Digest | null>(null)
  const [previewFormat, setPreviewFormat] = useState<"slack" | "email">("slack")
  const [previewContent, setPreviewContent] = useState("")

  const { data: digests = [], isLoading } = useQuery({
    queryKey: ["digests", filterStatus, filterClient],
    queryFn: () => digestsApi.list({
      status: filterStatus || undefined,
      client_id: filterClient || undefined,
    }),
  })

  const { data: clients = [] } = useQuery({
    queryKey: ["clients-all-active"],
    queryFn: () => clientsApi.listAll("active"),
  })

  const generateMutation = useMutation({
    mutationFn: (data: { client_id: number; tone: DigestTone }) =>
      digestsApi.generate({ client_id: data.client_id, tone: data.tone }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["digests"] })
      setGenerateOpen(false)
      toast.success("Digest generado correctamente")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al generar digest")),
  })

  const batchMutation = useMutation({
    mutationFn: (tone: DigestTone) => digestsApi.generateBatch({ tone }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["digests"] })
      toast.success(`${data.length} digests generados`)
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al generar batch")),
  })

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: DigestStatus }) =>
      digestsApi.updateStatus(id, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["digests"] })
      toast.success("Estado actualizado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar estado")),
  })

  const renderMutation = useMutation({
    mutationFn: ({ id, format }: { id: number; format: "slack" | "email" }) =>
      digestsApi.render(id, format),
    onSuccess: (data) => {
      setPreviewContent(data.rendered)
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al renderizar")),
  })

  const handleGenerate = () => {
    if (!selectedClientId) return
    generateMutation.mutate({ client_id: selectedClientId as number, tone: selectedTone })
  }

  const handlePreview = async (digest: Digest, fmt: "slack" | "email") => {
    setPreviewDigest(digest)
    setPreviewFormat(fmt)
    setPreviewContent("")
    renderMutation.mutate({ id: digest.id, format: fmt })
  }

  const handleCopyToClipboard = async () => {
    if (!previewContent) return
    try {
      await navigator.clipboard.writeText(previewContent)
      toast.success("Copiado al portapapeles")
    } catch {
      toast.error("Error al copiar")
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Digests Semanales</h1>
          <p className="text-muted-foreground">Resúmenes semanales generados con IA para clientes</p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => batchMutation.mutate(selectedTone)}
            disabled={batchMutation.isPending}
          >
            {batchMutation.isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Sparkles className="w-4 h-4 mr-2" />}
            Generar todos
          </Button>
          <Button onClick={() => setGenerateOpen(true)}>
            <Sparkles className="w-4 h-4 mr-2" />
            Generar digest
          </Button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-4">
        <div className="w-48">
          <Select value={String(filterClient)} onChange={(e) => setFilterClient(e.target.value ? Number(e.target.value) : "")}>
            <option value="">Todos los clientes</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </Select>
        </div>
        <div className="w-40">
          <Select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value as DigestStatus | "")}>
            <option value="">Todos los estados</option>
            <option value="draft">Borrador</option>
            <option value="reviewed">Revisado</option>
            <option value="sent">Enviado</option>
          </Select>
        </div>
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Cliente</TableHead>
                <TableHead>Periodo</TableHead>
                <TableHead>Tono</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Generado</TableHead>
                <TableHead className="text-right">Acciones</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8">
                    <Loader2 className="w-6 h-6 mx-auto animate-spin opacity-40" />
                  </TableCell>
                </TableRow>
              ) : digests.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8">
                    <FileText className="w-8 h-8 mx-auto mb-3 opacity-20" />
                    <p className="text-muted-foreground">No hay digests. Genera el primero.</p>
                  </TableCell>
                </TableRow>
              ) : (
                digests.map((digest) => (
                  <TableRow key={digest.id}>
                    <TableCell className="font-medium">{digest.client_name || "—"}</TableCell>
                    <TableCell>
                      {digest.period_start && digest.period_end
                        ? `${format(new Date(digest.period_start), "d MMM", { locale: es })} — ${format(new Date(digest.period_end), "d MMM", { locale: es })}`
                        : "—"}
                    </TableCell>
                    <TableCell>{toneLabels[digest.tone]}</TableCell>
                    <TableCell>
                      <Select
                        value={digest.status}
                        onChange={(e) => statusMutation.mutate({ id: digest.id, status: e.target.value as DigestStatus })}
                        className="w-32 h-8 text-sm"
                      >
                        <option value="draft">Borrador</option>
                        <option value="reviewed">Revisado</option>
                        <option value="sent">Enviado</option>
                      </Select>
                    </TableCell>
                    <TableCell>
                      {digest.generated_at
                        ? format(new Date(digest.generated_at), "d MMM HH:mm", { locale: es })
                        : "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          title="Editar"
                          onClick={() => navigate(`/digests/${digest.id}/edit`)}
                        >
                          <Pencil className="w-4 h-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          title="Preview Slack"
                          onClick={() => handlePreview(digest, "slack")}
                        >
                          <Eye className="w-4 h-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          title="Preview Email"
                          onClick={() => handlePreview(digest, "email")}
                        >
                          <Send className="w-4 h-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Generate Dialog */}
      <Dialog open={generateOpen} onOpenChange={setGenerateOpen}>
        <DialogHeader>
          <DialogTitle>Generar Digest</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label>Cliente</Label>
            <Select value={String(selectedClientId)} onChange={(e) => setSelectedClientId(e.target.value ? Number(e.target.value) : "")}>
              <option value="">Selecciona cliente...</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Tono</Label>
            <Select value={selectedTone} onChange={(e) => setSelectedTone(e.target.value as DigestTone)}>
              <option value="cercano">Cercano</option>
              <option value="formal">Formal</option>
              <option value="equipo">Equipo</option>
            </Select>
          </div>
          <p className="text-sm text-muted-foreground">
            Se generará el digest de la semana anterior automáticamente.
          </p>
          <div className="flex justify-end gap-2 pt-4">
            <Button variant="outline" onClick={() => setGenerateOpen(false)}>Cancelar</Button>
            <Button onClick={handleGenerate} disabled={!selectedClientId || generateMutation.isPending}>
              {generateMutation.isPending ? (
                <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Generando...</>
              ) : (
                <><Sparkles className="w-4 h-4 mr-2" />Generar</>
              )}
            </Button>
          </div>
        </div>
      </Dialog>

      {/* Preview Dialog */}
      <Dialog open={!!previewDigest} onOpenChange={() => setPreviewDigest(null)}>
        <DialogHeader>
          <DialogTitle>
            Preview — {previewDigest?.client_name} ({previewFormat === "slack" ? "Slack" : "Email"})
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4 pt-4">
          <div className="flex gap-2 mb-2">
            <Button
              variant={previewFormat === "slack" ? "default" : "outline"}
              size="sm"
              onClick={() => previewDigest && handlePreview(previewDigest, "slack")}
            >
              Slack
            </Button>
            <Button
              variant={previewFormat === "email" ? "default" : "outline"}
              size="sm"
              onClick={() => previewDigest && handlePreview(previewDigest, "email")}
            >
              Email
            </Button>
          </div>

          {renderMutation.isPending ? (
            <div className="flex justify-center py-12">
              <Loader2 className="w-6 h-6 animate-spin opacity-40" />
            </div>
          ) : previewFormat === "slack" ? (
            <pre className="bg-muted p-4 rounded-lg text-sm whitespace-pre-wrap max-h-[60vh] overflow-auto">
              {previewContent}
            </pre>
          ) : (
            <div
              className="border rounded-lg max-h-[60vh] overflow-auto"
              dangerouslySetInnerHTML={{ __html: previewContent }}
            />
          )}

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setPreviewDigest(null)}>Cerrar</Button>
            <Button onClick={handleCopyToClipboard} disabled={!previewContent}>
              <Copy className="w-4 h-4 mr-2" />
              Copiar
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  )
}
