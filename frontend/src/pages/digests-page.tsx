import { useEffect, useRef, useState } from "react"
import DOMPurify from "dompurify"
import { useQuery, useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { format } from "date-fns"
import { es } from "date-fns/locale"
import { FileText, Sparkles, Send, Eye, Copy, Pencil, Loader2, MessageCircle, Trash2, ClipboardCopy } from "lucide-react"
import { DeliveryReceipts, deliveryToast } from "@/components/delivery-receipts"
import { useAuth } from "@/context/auth-context"
import { DigestCohort } from "@/components/digests/digest-cohort"
import { reportPolicyKeys } from "@/lib/report-policy-api"
import { digestsApi, clientsApi, discordApi } from "@/lib/api"
import type { Digest, DigestStatus, DigestTone } from "@/lib/types"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import { useNavigate, useSearchParams } from "react-router-dom"

const toneLabels: Record<DigestTone, string> = {
  formal: "Formal",
  cercano: "Cercano",
  equipo: "Equipo",
}

function validPeriodDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const date = new Date(`${value}T12:00:00Z`)
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value
}

export default function DigestsPage() {
  const { user, hasPermission } = useAuth()
  const [searchParams] = useSearchParams()
  if (!user || !hasPermission("digests")) return null
  const linkedPeriodStart = searchParams.get("period_start") || ""
  const linkedPeriodEnd = searchParams.get("period_end") || ""
  return <DigestList key={`${user.id}:${hasPermission("digests", true)}:${linkedPeriodStart}:${linkedPeriodEnd}`} />
}

function DigestList() {
  const { user, hasPermission } = useAuth()
  const canWrite = hasPermission("digests", true)
  const canViewClients = hasPermission("clients")
  const active = useRef(true)
  useEffect(() => { active.current = true; return () => { active.current = false } }, [])
  const previewRequest = useRef({ id: 0, epoch: 0 })
  const discordRequest = useRef({ id: 0, epoch: 0 })
  const copyEpoch = useRef(0)
  const [previewReady, setPreviewReady] = useState(false)
  const [previewError, setPreviewError] = useState("")
  const [discordReady, setDiscordReady] = useState(false)
  const [discordError, setDiscordError] = useState("")
  const isLivePreview = (request: { id: number; epoch: number }, ref: typeof previewRequest) => active.current && request.id === ref.current.id && request.epoch === ref.current.epoch
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [generateOpen, setGenerateOpen] = useState(false)
  const [selectedClientId, setSelectedClientId] = useState<number | "">("")
  const [selectedTone, setSelectedTone] = useState<DigestTone>("cercano")
  const [genPeriodStart, setGenPeriodStart] = useState("")
  const [genPeriodEnd, setGenPeriodEnd] = useState("")
  const [filterStatus, setFilterStatus] = useState<DigestStatus | "">("")
  const filterClientId = Number(searchParams.get("client_id"))
  const filterClient: number | "" = Number.isInteger(filterClientId) && filterClientId > 0 ? filterClientId : ""
  const setFilterClient = (value: number | "") => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set("client_id", String(value))
    else next.delete("client_id")
    setSearchParams(next, { replace: true })
  }
  const linkedPeriodStart = searchParams.get("period_start") || ""
  const linkedPeriodEnd = searchParams.get("period_end") || ""
  const linkedPeriodIsValid = validPeriodDate(linkedPeriodStart) && validPeriodDate(linkedPeriodEnd) && linkedPeriodStart <= linkedPeriodEnd
  const [filterPeriodFrom, setFilterPeriodFrom] = useState(() => validPeriodDate(linkedPeriodStart) && (linkedPeriodStart <= linkedPeriodEnd || !linkedPeriodEnd) ? linkedPeriodStart : "")
  const [filterPeriodTo, setFilterPeriodTo] = useState(() => validPeriodDate(linkedPeriodEnd) && (linkedPeriodStart <= linkedPeriodEnd || !linkedPeriodStart) ? linkedPeriodEnd : "")
  const expectedPeriod = filterClient && linkedPeriodIsValid
    ? { start: linkedPeriodStart, end: linkedPeriodEnd }
    : undefined
  const [previewDigest, setPreviewDigest] = useState<Digest | null>(null)
  const [previewFormat, setPreviewFormat] = useState<"slack" | "email">("slack")
  const [previewContent, setPreviewContent] = useState("")
  // Discord preview/edit state (internal only)
  const [discordPreviewDigest, setDiscordPreviewDigest] = useState<Digest | null>(null)
  const [discordPreviewContent, setDiscordPreviewContent] = useState("")
  const [discordIsEditing, setDiscordIsEditing] = useState(false)
  const [digestToDelete, setDigestToDelete] = useState<Digest | null>(null)

  const { data: digestPages, isLoading, isError, refetch, fetchNextPage, hasNextPage, isFetchingNextPage, isFetchNextPageError } = useInfiniteQuery({
    queryKey: ["digests", user?.id, filterStatus, filterClient, filterPeriodFrom, filterPeriodTo],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => digestsApi.list({
      limit: 20,
      offset: pageParam,
      status: filterStatus || undefined,
      client_id: filterClient || undefined,
      period_from: filterPeriodFrom || undefined,
      period_to: filterPeriodTo || undefined,
    }),
    getNextPageParam: (lastPage, pages) => lastPage.length === 20 ? pages.length * 20 : undefined,
  })
  const digests = Array.from(new Map((digestPages?.pages.flat() ?? []).map(digest => [digest.id, digest])).values())

  const { data: clients = [] } = useQuery({
    queryKey: ["clients-all", user?.id],
    enabled: canViewClients,
    queryFn: () => clientsApi.listAll(),
  })

  const generateMutation = useMutation({
    mutationFn: (data: { client_id: number; tone: DigestTone; period_start?: string; period_end?: string }) =>
      digestsApi.generate({ client_id: data.client_id, tone: data.tone, period_start: data.period_start, period_end: data.period_end }),
    onSuccess: () => {
      if (!active.current) return
      queryClient.invalidateQueries({ queryKey: reportPolicyKeys.preview })
      queryClient.invalidateQueries({ queryKey: reportPolicyKeys.external })
      queryClient.invalidateQueries({ queryKey: ["digests"] })
      queryClient.invalidateQueries({ queryKey: ["incidents"] })
      setGenerateOpen(false)
      toast.success("Resumen generado. Revisa su nueva versión.")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al generar el resumen")),
  })

  const statusMutation = useMutation({
    mutationFn: ({ id, status }: { id: number; status: DigestStatus }) =>
      digestsApi.updateStatus(id, status),
    onSuccess: () => {
      if (!active.current) return
      queryClient.invalidateQueries({ queryKey: reportPolicyKeys.preview })
      queryClient.invalidateQueries({ queryKey: reportPolicyKeys.external })
      queryClient.invalidateQueries({ queryKey: ["digests"] })
      queryClient.invalidateQueries({ queryKey: ["incidents"] })
      toast.success("Estado actualizado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar estado")),
  })

  const renderMutation = useMutation({
    mutationFn: ({ id, format }: { id: number; epoch: number; format: "slack" | "email" }) => digestsApi.render(id, format),
    onSuccess: (data, request) => {
      if (!isLivePreview(request, previewRequest)) return
      setPreviewContent(data.rendered)
      setPreviewReady(true)
    },
    onError: (error, request) => { if (isLivePreview(request, previewRequest)) setPreviewError(getErrorMessage(error, "No se pudo cargar esta versión. Vuelve a intentarlo.")) },
  })

  const discordPreviewMutation = useMutation({
    mutationFn: ({ id }: { id: number; epoch: number }) => digestsApi.render(id, "slack"),
    onSuccess: (data, request) => {
      if (!isLivePreview(request, discordRequest)) return
      setDiscordPreviewContent(data.rendered)
      setDiscordIsEditing(false)
      setDiscordReady(true)
    },
    onError: (error, request) => { if (isLivePreview(request, discordRequest)) setDiscordError(getErrorMessage(error, "No se pudo cargar esta versión para Discord.")) },
  })

  const discordSendCustomMutation = useMutation({
    mutationFn: ({ id, content }: { id: number; epoch: number; content: string }) => discordApi.sendDigest(id, content),
    onSuccess: (data, request) => {
      if (!active.current) return
      queryClient.invalidateQueries({ queryKey: ["deliveries"] })
      queryClient.invalidateQueries({ queryKey: reportPolicyKeys.preview })
      queryClient.invalidateQueries({ queryKey: reportPolicyKeys.external })
      if (isLivePreview(request, discordRequest)) deliveryToast(data)
    },
    onError: (error, request) => { if (isLivePreview(request, discordRequest)) toast.error(getErrorMessage(error, "No se pudo confirmar el envío. Comprueba los recibos antes de reintentarlo.")) },
  })

  const handleDiscordPreview = (digest: Digest) => {
    const request = { id: digest.id, epoch: discordRequest.current.epoch + 1 }
    discordRequest.current = request
    setDiscordPreviewDigest(digest)
    setDiscordPreviewContent("")
    setDiscordIsEditing(false)
    setDiscordReady(false)
    setDiscordError("")
    discordPreviewMutation.mutate(request)
  }
  const closeDiscordPreview = () => {
    discordRequest.current = { id: 0, epoch: discordRequest.current.epoch + 1 }
    setDiscordPreviewDigest(null)
    setDiscordPreviewContent("")
    setDiscordReady(false)
  }
  const closePreview = () => {
    previewRequest.current = { id: 0, epoch: previewRequest.current.epoch + 1 }
    setPreviewDigest(null)
    setPreviewContent("")
    setPreviewReady(false)
  }

  const deleteMutation = useMutation({
    mutationFn: (id: number) => digestsApi.delete(id),
    onSuccess: () => {
      if (!active.current) return
      queryClient.invalidateQueries({ queryKey: reportPolicyKeys.preview })
      queryClient.invalidateQueries({ queryKey: reportPolicyKeys.external })
      queryClient.invalidateQueries({ queryKey: ["digests"] })
      queryClient.invalidateQueries({ queryKey: ["incidents"] })
      toast.success("Resumen eliminado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar el resumen")),
  })

  const handleDelete = (digest: Digest) => {
    setDigestToDelete(digest)
  }

  const handleGenerate = () => {
    if (!selectedClientId || !canWrite || generateMutation.isPending) return
    if (Boolean(genPeriodStart) !== Boolean(genPeriodEnd) || (genPeriodStart && genPeriodEnd < genPeriodStart)) {
      toast.error("Indica las dos fechas en orden, o deja ambas vacías para usar la última semana cerrada.")
      return
    }
    generateMutation.mutate({
      client_id: selectedClientId as number,
      tone: selectedTone,
      period_start: genPeriodStart || undefined,
      period_end: genPeriodEnd || undefined,
    })
  }

  const handlePreview = (digest: Digest, fmt: "slack" | "email") => {
    const request = { id: digest.id, epoch: previewRequest.current.epoch + 1, format: fmt }
    previewRequest.current = request
    setPreviewReady(false)
    setPreviewError("")
    setPreviewDigest(digest)
    setPreviewFormat(fmt)
    setPreviewContent("")
    renderMutation.mutate(request)
  }

  const handleCopyToClipboard = async () => {
    const content = previewContent
    if (!content || !previewReady || !previewDigest || previewRequest.current.id !== previewDigest.id) return
    try {
      await navigator.clipboard.writeText(content)
      toast.success("Copiado al portapapeles")
    } catch {
      toast.error("Error al copiar")
    }
  }

  const handleQuickCopy = async (digest: Digest, format: "slack" | "email" | "email_plain") => {
    const epoch = ++copyEpoch.current
    try {
      const data = await digestsApi.render(digest.id, format)
      if (!active.current || copyEpoch.current !== epoch) return
      await navigator.clipboard.writeText(data.rendered)
      const labels: Record<string, string> = { slack: "Slack", email: "Email HTML", email_plain: "Texto plano" }
      toast.success(`${labels[format] || format} copiado`)
    } catch (err) {
      if (active.current && copyEpoch.current === epoch) toast.error(getErrorMessage(err, "Error al copiar"))
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Resúmenes de clientes</h1>
          <p className="text-muted-foreground">Resúmenes semanales o mensuales según cada cliente</p>
        </div>
        {canWrite && <Button onClick={() => setGenerateOpen(true)} disabled={!canViewClients} title={!canViewClients ? "Necesitas acceso a clientes para elegir una generación individual" : undefined}>
          <Sparkles className="w-4 h-4 mr-2" />Preparar uno
        </Button>}
      </div>

      <DigestCohort clientId={filterClient || undefined} expectedPeriod={expectedPeriod} />

      <div><h2 className="text-lg font-semibold">Historial de versiones</h2><p className="text-sm text-muted-foreground">Abre una versión para revisar su texto y confirmar la entrega al cliente. Discord es distribución interna.</p></div>
      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="w-48">
          <Select aria-label="Filtrar por cliente" value={String(filterClient)} onChange={(e) => setFilterClient(e.target.value ? Number(e.target.value) : "")}>
            <option value="">Todos los clientes</option>
            {filterClient && !clients.some(client => client.id === filterClient) && <option value={filterClient}>Cliente #{filterClient}</option>}
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </Select>
        </div>
        <div className="w-40">
          <Select aria-label="Filtrar por estado" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value as DigestStatus | "")}>
            <option value="">Todos los estados</option>
            <option value="draft">Borrador</option>
            <option value="reviewed">Revisado</option>
            <option value="sent">Marcado como enviado (histórico)</option>
          </Select>
        </div>
        <div className="flex items-center gap-1.5">
          <Input
            type="date"
            value={filterPeriodFrom}
            onChange={(e) => setFilterPeriodFrom(e.target.value)}
            className="w-36 h-9"
            title="Periodo desde"
          />
          <span className="text-muted-foreground text-sm">—</span>
          <Input
            type="date"
            value={filterPeriodTo}
            onChange={(e) => setFilterPeriodTo(e.target.value)}
            className="w-36 h-9"
            title="Periodo hasta"
          />
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
              ) : isError && !digestPages ? (
                <TableRow><TableCell colSpan={6}><div role="alert" className="py-4 text-center">No se pudo cargar el historial. <Button variant="outline" size="sm" onClick={() => void refetch()}>Reintentar historial</Button></div></TableCell></TableRow>
              ) : digests.length === 0 ? (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={6} className="py-12">
                    <div className="flex flex-col items-center">
                      <FileText className="h-8 w-8 text-muted-foreground/30 mb-3" />
                      <p className="text-sm font-medium text-foreground mb-1">Sin resúmenes</p>
                      <p className="text-xs text-muted-foreground">Prepara una selección de clientes o un resumen individual.</p>
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                digests.map((digest) => (
                  <TableRow key={digest.id}>
                    <TableCell className="font-medium">{digest.client_name || "—"}</TableCell>
                    <TableCell>
                      {digest.period_start && digest.period_end
                        ? `${format(new Date(digest.period_start + "T12:00:00"), "d MMM yyyy", { locale: es })} — ${format(new Date(digest.period_end + "T12:00:00"), "d MMM yyyy", { locale: es })}`
                        : "—"}
                    </TableCell>
                    <TableCell>{toneLabels[digest.tone]}</TableCell>
                    <TableCell>
                      <Select
                        value={digest.status}
                        aria-label={`Estado histórico de versión #${digest.id}`}
                        disabled={!canWrite || statusMutation.isPending}
                        onChange={(e) => statusMutation.mutate({ id: digest.id, status: e.target.value as DigestStatus })}
                        className="w-48 h-8 text-sm"
                      >
                        <option value="draft">Borrador</option>
                        <option value="reviewed">Revisado</option>
                        <option value="sent" disabled>Marcado como enviado (histórico)</option>
                      </Select>
                    </TableCell>
                    <TableCell>
                      {digest.generated_at
                        ? format(new Date(digest.generated_at), "d MMM HH:mm", { locale: es })
                        : "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end items-center gap-1">
                        {/* Edición */}
                        <Button
                          variant="ghost"
                          size="sm"
                          title={canWrite ? "Editar y revisar entrega" : "Consultar versión"}
                          onClick={() => navigate(`/digests/${digest.id}/edit`)}
                        >
                          <Pencil className="w-4 h-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          title="Vista previa"
                          onClick={() => handlePreview(digest, "slack")}
                        >
                          <Eye className="w-4 h-4" />
                        </Button>
                        <span className="w-px h-5 bg-border mx-0.5" />
                        {/* Copiar para pegar en Slack / email */}
                        <Button
                          variant="ghost"
                          size="sm"
                          title="Copiar Slack"
                          onClick={() => handleQuickCopy(digest, "slack")}
                        >
                          <ClipboardCopy className="w-4 h-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          title="Copiar Email (texto plano)"
                          onClick={() => handleQuickCopy(digest, "email_plain")}
                        >
                          <FileText className="w-3.5 h-3.5" />
                        </Button>
                        <span className="w-px h-5 bg-border mx-0.5" />
                        {/* Discord (interno) */}
                        <Button
                          variant="ghost"
                          size="sm"
                          title="Discord (interno)"
                          onClick={() => handleDiscordPreview(digest)}
                          disabled={!canWrite}
                        >
                          <MessageCircle className="w-4 h-4" />
                        </Button>
                        {canWrite && digest.status !== "sent" && (
                          <>
                            <span className="w-px h-5 bg-border mx-0.5" />
                            <Button
                              variant="ghost"
                              size="sm"
                              title="Eliminar"
                              className="text-destructive hover:text-destructive"
                              onClick={() => handleDelete(digest)}
                              disabled={deleteMutation.isPending}
                            >
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          </>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {digestPages && <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">Mostrando {digests.length} {digests.length === 1 ? "versión" : "versiones"}.</p>
        {isFetchNextPageError && <p role="alert" className="text-sm">No se pudieron cargar las versiones anteriores. Las que ya ves se conservan.</p>}
        {hasNextPage && <Button variant="outline" disabled={isFetchingNextPage} onClick={() => void fetchNextPage()}>{isFetchingNextPage ? <><Loader2 className="size-4 mr-2 animate-spin" />Cargando versiones…</> : isFetchNextPageError ? "Reintentar versiones anteriores" : "Cargar versiones anteriores"}</Button>}
      </div>}

      {/* Generate Dialog */}
      <Dialog open={generateOpen} onOpenChange={setGenerateOpen}>
        <DialogHeader>
          <DialogTitle>Preparar un resumen</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label htmlFor="individual-client">Cliente</Label>
            <Select id="individual-client" disabled={generateMutation.isPending} value={String(selectedClientId)} onChange={(e) => setSelectedClientId(e.target.value ? Number(e.target.value) : "")}>
              <option value="">Selecciona cliente...</option>
              {clients.filter(client => client.status === "active" && !client.is_internal).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="individual-tone">Tono</Label>
            <Select id="individual-tone" disabled={generateMutation.isPending} value={selectedTone} onChange={(e) => setSelectedTone(e.target.value as DigestTone)}>
              <option value="cercano">Cercano</option>
              <option value="formal">Formal</option>
              <option value="equipo">Equipo</option>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Período (opcional; por defecto, última semana cerrada)</Label>
            <div className="flex items-center gap-2">
              <Input
                type="date"
                value={genPeriodStart}
                onChange={(e) => setGenPeriodStart(e.target.value)}
                className="flex-1"
                aria-label="Inicio del período"
                placeholder="Desde"
              />
              <span className="text-muted-foreground text-sm">—</span>
              <Input
                type="date"
                value={genPeriodEnd}
                onChange={(e) => setGenPeriodEnd(e.target.value)}
                className="flex-1"
                aria-label="Fin del período"
                placeholder="Hasta"
              />
            </div>
          </div>
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
      <Dialog open={!!previewDigest} onOpenChange={(open) => { if (!open) closePreview() }}>
        <DialogHeader>
          <DialogTitle>
            Vista previa — {previewDigest?.client_name} · Versión #{previewDigest?.id} ({previewFormat === "slack" ? "Slack" : "Email"})
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

          {previewError ? <div role="alert" className="text-sm">{previewError} <Button variant="outline" size="sm" onClick={() => previewDigest && handlePreview(previewDigest, previewFormat)}>Reintentar vista previa</Button></div> : !previewReady ? (
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
              dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(previewContent) }}
            />
          )}

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={closePreview}>Cerrar</Button>
            <Button onClick={handleCopyToClipboard} disabled={!previewReady || !previewContent}>
              <Copy className="w-4 h-4 mr-2" />
              Copiar
            </Button>
          </div>
        </div>
      </Dialog>

      {/* Discord preview/edit dialog */}
      <Dialog open={!!discordPreviewDigest} onOpenChange={(open) => { if (!open) closeDiscordPreview() }}>
        <DialogHeader>
          <DialogTitle>
            Compartir en Discord interno — {discordPreviewDigest?.client_name} · Versión #{discordPreviewDigest?.id}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4 pt-4">
          <p className="text-sm text-muted-foreground">Compartir aquí no envía el resumen al cliente ni confirma su recepción.</p>
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              {discordIsEditing ? "Edita el contenido antes de enviar" : "Revisa el contenido antes de enviar a Discord"}
            </p>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setDiscordIsEditing(!discordIsEditing)}
              disabled={!discordReady || discordSendCustomMutation.isPending}
            >
              <Pencil className="w-4 h-4 mr-1" />
              {discordIsEditing ? "Vista previa" : "Editar"}
            </Button>
          </div>

          {discordError ? <div role="alert" className="text-sm">{discordError} <Button variant="outline" size="sm" onClick={() => discordPreviewDigest && handleDiscordPreview(discordPreviewDigest)}>Reintentar vista previa de Discord</Button></div> : !discordReady ? (
            <div className="flex justify-center py-12">
              <Loader2 className="w-6 h-6 animate-spin opacity-40" />
            </div>
          ) : discordIsEditing ? (
            <textarea
              className="w-full min-h-[300px] rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono"
              aria-label="Texto para Discord interno"
              disabled={discordSendCustomMutation.isPending}
              value={discordPreviewContent}
              onChange={(e) => setDiscordPreviewContent(e.target.value)}
            />
          ) : (
            <pre className="bg-muted p-4 rounded-lg text-sm whitespace-pre-wrap max-h-[60vh] overflow-auto">
              {discordPreviewContent}
            </pre>
          )}

          {discordPreviewDigest && <DeliveryReceipts sourceKind="digest" sourceId={discordPreviewDigest.id} />}

          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={closeDiscordPreview}>
              Cancelar
            </Button>
            <Button
              onClick={() => { if (discordPreviewDigest && canWrite && discordReady && discordRequest.current.id === discordPreviewDigest.id && !discordSendCustomMutation.isPending) discordSendCustomMutation.mutate({ ...discordRequest.current, content: discordPreviewContent }) }}
              disabled={!discordPreviewDigest || !canWrite || !discordReady || !discordPreviewContent.trim() || discordSendCustomMutation.isPending}
            >
              {discordSendCustomMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Send className="w-4 h-4 mr-2" />
              )}
              Compartir en Discord interno
            </Button>
          </div>
        </div>
      </Dialog>

      <ConfirmDialog
        open={digestToDelete !== null}
        onOpenChange={(open) => !open && setDigestToDelete(null)}
        title="Eliminar resumen"
        description={`¿Eliminar el resumen de ${digestToDelete?.client_name || "este cliente"}? Esta acción no se puede deshacer.`}
        confirmLabel="Eliminar"
        onConfirm={() => {
          if (digestToDelete) deleteMutation.mutate(digestToDelete.id)
        }}
      />

    </div>
  )
}
