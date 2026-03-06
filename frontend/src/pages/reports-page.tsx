import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { FileText, Plus, Trash2, Copy, Building2, FolderKanban, Calendar, Sparkles, Loader2, FileDown } from "lucide-react"
import { toast } from "sonner"
import { reportsApi, clientsApi, projectsApi } from "@/lib/api"
import type { Report, ReportType, ReportPeriod, ReportAudience, ReportNarrative } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Select } from "@/components/ui/select"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { getErrorMessage } from "@/lib/utils"
import { SkeletonCard } from "@/components/ui/skeleton"

const REPORT_TYPES: { value: ReportType; label: string; icon: typeof FileText }[] = [
  { value: "client_status", label: "Estado de cliente", icon: Building2 },
  { value: "weekly_summary", label: "Resumen semanal", icon: Calendar },
  { value: "project_status", label: "Estado de proyecto", icon: FolderKanban },
  { value: "client_monthly", label: "Informe mensual", icon: FileText },
]

const AUDIENCE_LABELS: Record<string, string> = {
  executive: "Ejecutivo",
  marketing: "Marketing",
  operational: "Operativo",
}

type ViewMode = "structured" | "scqa" | "fulltext"

export default function ReportsPage() {
  const queryClient = useQueryClient()
  const [generateOpen, setGenerateOpen] = useState(false)
  const [viewReport, setViewReport] = useState<Report | null>(null)
  const [narrative, setNarrative] = useState<ReportNarrative | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>("structured")

  const { data: reports = [], isLoading } = useQuery({
    queryKey: ["reports"],
    queryFn: () => reportsApi.list({ limit: 20 }),
  })

  const narrativeMutation = useMutation({
    mutationFn: (id: number) => reportsApi.aiNarrative(id),
    onSuccess: (data) => {
      setNarrative(data)
      setViewMode("scqa")
      toast.success("Narrativa IA generada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al generar narrativa")),
  })

  const deleteMutation = useMutation({
    mutationFn: reportsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reports"] })
      toast.success("Informe eliminado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar")),
  })

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString("es-ES", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })
  }

  const getTypeInfo = (type: string) => {
    return REPORT_TYPES.find((t) => t.value === type) || REPORT_TYPES[0]
  }

  const handleRequestNarrative = () => {
    if (!viewReport) return
    if (!narrative && !narrativeMutation.isPending) {
      narrativeMutation.mutate(viewReport.id)
    } else if (narrative) {
      setViewMode("scqa")
    }
  }

  const handleExportPdf = () => {
    if (!viewReport) return
    window.open(reportsApi.pdfUrl(viewReport.id), "_blank")
  }

  const handleExportNarrativePdf = () => {
    if (!viewReport || !narrative) return
    reportsApi.narrativePdf(viewReport.id, {
      narrative: narrative.narrative,
      executive_summary: narrative.executive_summary,
      scqa_sections: narrative.scqa_sections || [],
    })
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold uppercase tracking-wide">Informes</h2>
          <p className="text-sm text-muted-foreground mt-1">{reports.length} informes generados</p>
        </div>
        <Button onClick={() => setGenerateOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Generar informe
        </Button>
      </div>

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : reports.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <div className="p-4 rounded-2xl bg-brand/5 inline-block mb-4">
              <FileText className="h-10 w-10 text-muted-foreground" />
            </div>
            <h3 className="text-lg font-semibold text-foreground mb-1">Sin informes</h3>
            <p className="text-sm text-muted-foreground mb-6">Genera informes de estado por cliente o proyecto con IA.</p>
            <Button onClick={() => setGenerateOpen(true)}>
              <Plus className="h-4 w-4 mr-2" />
              Generar primer informe
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {reports.map((report) => {
            const typeInfo = getTypeInfo(report.type)
            const Icon = typeInfo.icon
            return (
              <Card
                key={report.id}
                className="cursor-pointer hover:border-brand/50 transition-colors"
                onClick={() => {
                  setViewReport(report)
                  setViewMode("structured")
                  setNarrative(null)
                }}
              >
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Icon className="h-4 w-4 text-muted-foreground" />
                      <Badge variant="outline" className="text-xs">
                        {typeInfo.label}
                      </Badge>
                      {report.audience && (
                        <Badge variant="outline" className="text-xs">
                          {AUDIENCE_LABELS[report.audience] || report.audience}
                        </Badge>
                      )}
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={deleteMutation.isPending}
                      onClick={(e) => {
                        e.stopPropagation()
                        deleteMutation.mutate(report.id)
                      }}
                    >
                      <Trash2 className="h-4 w-4 text-muted-foreground hover:text-destructive" />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent>
                  <h3 className="font-medium mb-1 line-clamp-2">{report.title}</h3>
                  <p className="text-sm text-muted-foreground line-clamp-2 mb-2">
                    {report.summary}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {formatDate(report.generated_at)}
                  </p>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* Generate Dialog */}
      <GenerateReportDialog open={generateOpen} onOpenChange={setGenerateOpen} />

      {/* View Report Dialog */}
      {viewReport && (
        <Dialog open={!!viewReport} onOpenChange={() => { setViewReport(null); setViewMode("structured"); setNarrative(null) }}>
          <DialogHeader>
            <DialogTitle>{viewReport.title}</DialogTitle>
          </DialogHeader>

          {/* 3 View Mode Tabs */}
          <div className="flex gap-2 mt-4 mb-2 flex-wrap">
            <Button
              variant={viewMode === "structured" ? "default" : "outline"}
              size="sm"
              onClick={() => setViewMode("structured")}
            >
              Estructurado
            </Button>
            <Button
              variant={viewMode === "scqa" ? "default" : "outline"}
              size="sm"
              onClick={handleRequestNarrative}
              disabled={narrativeMutation.isPending}
            >
              {narrativeMutation.isPending ? (
                <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Generando...</>
              ) : (
                <><Sparkles className="h-4 w-4 mr-2" />Narrativa SCQA</>
              )}
            </Button>
            {narrative && (
              <Button
                variant={viewMode === "fulltext" ? "default" : "outline"}
                size="sm"
                onClick={() => setViewMode("fulltext")}
              >
                Texto completo
              </Button>
            )}
          </div>

          <div className="space-y-4 max-h-[60vh] overflow-y-auto">
            {viewMode === "scqa" && narrative?.scqa_sections?.length ? (
              <div>
                <div className="bg-brand/5 rounded-lg p-4 mb-4">
                  <h4 className="text-sm font-semibold mb-1">Resumen ejecutivo</h4>
                  <p className="text-sm text-muted-foreground">{narrative.executive_summary}</p>
                </div>
                <div className="space-y-3">
                  {narrative.scqa_sections.map((section, i) => (
                    <div key={i} className="border rounded-lg p-4">
                      <h4 className="font-medium text-brand mb-2">{section.title}</h4>
                      <div className="text-sm text-muted-foreground whitespace-pre-line">
                        {section.content}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : viewMode === "fulltext" && narrative ? (
              <div>
                <div className="bg-brand/5 rounded-lg p-4 mb-4">
                  <h4 className="text-sm font-semibold mb-1">Resumen ejecutivo</h4>
                  <p className="text-sm text-muted-foreground">{narrative.executive_summary}</p>
                </div>
                <div className="text-sm whitespace-pre-line prose prose-sm max-w-none">
                  {narrative.narrative}
                </div>
              </div>
            ) : (
              viewReport.sections.map((section, i) => (
                <div key={i}>
                  <h4 className="font-medium mb-2">{section.title}</h4>
                  <div className="text-sm text-muted-foreground whitespace-pre-line">
                    {section.content}
                  </div>
                </div>
              ))
            )}
          </div>

          <div className="flex justify-between gap-2 mt-6 flex-wrap">
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={handleExportPdf}>
                <FileDown className="h-4 w-4 mr-2" />
                PDF
              </Button>
              {narrative && (
                <Button variant="outline" size="sm" onClick={handleExportNarrativePdf}>
                  <FileDown className="h-4 w-4 mr-2" />
                  PDF Narrativa
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => {
                let text: string
                if (viewMode === "fulltext" && narrative) {
                  text = narrative.narrative
                } else if (viewMode === "scqa" && narrative?.scqa_sections?.length) {
                  text = narrative.scqa_sections.map((s) => `## ${s.title}\n${s.content}`).join("\n\n")
                } else {
                  text = viewReport.sections.map((s) => `## ${s.title}\n${s.content}`).join("\n\n")
                }
                navigator.clipboard.writeText(text)
                toast.success("Copiado al portapapeles")
              }}>
                <Copy className="h-4 w-4 mr-2" />
                Copiar
              </Button>
              <Button onClick={() => { setViewReport(null); setViewMode("structured"); setNarrative(null) }}>Cerrar</Button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  )
}

const AUDIENCE_DESCRIPTIONS: Record<string, string> = {
  executive: "Alto nivel, ROI, progreso general. Sin detalles operativos.",
  marketing: "Métricas detalladas, tendencias, comparativas.",
  operational: "Tareas, timelines, blockers, asignaciones. Máximo detalle.",
}

function GenerateReportDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [type, setType] = useState<ReportType>("client_status")
  const [clientId, setClientId] = useState<number | null>(null)
  const [projectId, setProjectId] = useState<number | null>(null)
  const [period, setPeriod] = useState<ReportPeriod>("month")
  const [audience, setAudience] = useState<ReportAudience | "">("")
  const now = new Date()
  const [monthlyMonth, setMonthlyMonth] = useState(now.getMonth() + 1)
  const [monthlyYear, setMonthlyYear] = useState(now.getFullYear())

  const { data: clients = [] } = useQuery({
    queryKey: ["clients-all-active"],
    queryFn: () => clientsApi.listAll("active"),
    enabled: open && (type === "client_status" || type === "client_monthly"),
  })

  const { data: projects = [] } = useQuery({
    queryKey: ["projects-all-active"],
    queryFn: () => projectsApi.listAll({ status: "active" }),
    enabled: open && type === "project_status",
  })

  const generateMutation = useMutation({
    mutationFn: (params: Parameters<typeof reportsApi.generate>[0]) => reportsApi.generate(params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reports"] })
      toast.success("Informe generado")
      onOpenChange(false)
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al generar informe")),
  })

  const monthlyMutation = useMutation({
    mutationFn: reportsApi.generateClientMonthly,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reports"] })
      toast.success("Informe mensual SEO generado")
      onOpenChange(false)
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al generar informe mensual")),
  })

  const isPending = generateMutation.isPending || monthlyMutation.isPending

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (type === "client_monthly") {
      if (!clientId) return
      monthlyMutation.mutate({ client_id: clientId, year: monthlyYear, month: monthlyMonth })
    } else {
      generateMutation.mutate({
        type,
        client_id: type === "client_status" ? clientId : null,
        project_id: type === "project_status" ? projectId : null,
        period,
        audience: audience || null,
      })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Generar informe</DialogTitle>
      </DialogHeader>
      <form onSubmit={handleSubmit} className="space-y-4 mt-4">
        <div className="space-y-2">
          <Label>Tipo de informe</Label>
          <Select
            value={type}
            onChange={(e) => setType(e.target.value as ReportType)}
          >
            {REPORT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </Select>
        </div>

        {(type === "client_status" || type === "client_monthly") && (
          <div className="space-y-2">
            <Label>Cliente</Label>
            <Select
              value={clientId ?? ""}
              onChange={(e) => setClientId(Number(e.target.value) || null)}
              required
            >
              <option value="">Seleccionar cliente...</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </div>
        )}

        {type === "project_status" && (
          <div className="space-y-2">
            <Label>Proyecto</Label>
            <Select
              value={projectId ?? ""}
              onChange={(e) => setProjectId(Number(e.target.value) || null)}
              required
            >
              <option value="">Seleccionar proyecto...</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.client_name})
                </option>
              ))}
            </Select>
          </div>
        )}

        {type === "client_monthly" && (
          <div className="space-y-2">
            <Label>Periodo</Label>
            <div className="flex gap-2">
              <Select value={monthlyMonth.toString()} onChange={(e) => setMonthlyMonth(Number(e.target.value))}>
                {["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"].map((m, i) => (
                  <option key={i} value={i + 1}>{m}</option>
                ))}
              </Select>
              <Select value={monthlyYear.toString()} onChange={(e) => setMonthlyYear(Number(e.target.value))}>
                {[now.getFullYear() - 1, now.getFullYear()].map((y) => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </Select>
            </div>
          </div>
        )}

        {(type === "client_status" || type === "weekly_summary") && (
          <div className="space-y-2">
            <Label>Periodo</Label>
            <Select
              value={period}
              onChange={(e) => setPeriod(e.target.value as ReportPeriod)}
            >
              <option value="week">Última semana</option>
              <option value="month">Último mes</option>
            </Select>
          </div>
        )}

        {type !== "client_monthly" && (
          <div className="space-y-2">
            <Label>Audiencia <span className="text-muted-foreground font-normal">(opcional)</span></Label>
            <Select
              value={audience}
              onChange={(e) => setAudience(e.target.value as ReportAudience | "")}
            >
              <option value="">General (sin audiencia especifica)</option>
              <option value="executive">Ejecutivo</option>
              <option value="marketing">Marketing</option>
              <option value="operational">Operativo</option>
            </Select>
            {audience && (
              <p className="text-xs text-muted-foreground">{AUDIENCE_DESCRIPTIONS[audience]}</p>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-4">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button type="submit" disabled={isPending}>
            {isPending ? "Generando..." : "Generar"}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
