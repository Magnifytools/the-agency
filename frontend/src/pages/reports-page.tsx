import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { FileText, Plus, Trash2, Copy, Building2, FolderKanban, Calendar } from "lucide-react"
import { toast } from "sonner"
import { reportsApi, clientsApi, projectsApi } from "@/lib/api"
import type { Report, ReportType, ReportPeriod } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Select } from "@/components/ui/select"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"

const REPORT_TYPES: { value: ReportType; label: string; icon: typeof FileText }[] = [
  { value: "client_status", label: "Estado de cliente", icon: Building2 },
  { value: "weekly_summary", label: "Resumen semanal", icon: Calendar },
  { value: "project_status", label: "Estado de proyecto", icon: FolderKanban },
]

export default function ReportsPage() {
  const queryClient = useQueryClient()
  const [generateOpen, setGenerateOpen] = useState(false)
  const [viewReport, setViewReport] = useState<Report | null>(null)

  const { data: reports = [], isLoading } = useQuery({
    queryKey: ["reports"],
    queryFn: () => reportsApi.list(20),
  })

  const deleteMutation = useMutation({
    mutationFn: reportsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reports"] })
      toast.success("Informe eliminado")
    },
    onError: () => toast.error("Error al eliminar"),
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

  const copyToClipboard = (report: Report) => {
    const text = report.sections.map((s) => `## ${s.title}\n${s.content}`).join("\n\n")
    navigator.clipboard.writeText(text)
    toast.success("Copiado al portapapeles")
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold uppercase tracking-wide">Informes</h2>
        <Button onClick={() => setGenerateOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Generar informe
        </Button>
      </div>

      {isLoading ? (
        <div className="py-12 text-center text-muted-foreground">Cargando...</div>
      ) : reports.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <FileText className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
            <p className="text-muted-foreground mb-4">No hay informes generados</p>
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
                onClick={() => setViewReport(report)}
              >
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-2">
                      <Icon className="h-4 w-4 text-muted-foreground" />
                      <Badge variant="outline" className="text-xs">
                        {typeInfo.label}
                      </Badge>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
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
        <Dialog open={!!viewReport} onOpenChange={() => setViewReport(null)}>
          <DialogHeader>
            <DialogTitle>{viewReport.title}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 mt-4 max-h-[60vh] overflow-y-auto">
            {viewReport.sections.map((section, i) => (
              <div key={i}>
                <h4 className="font-medium mb-2">{section.title}</h4>
                <div className="text-sm text-muted-foreground whitespace-pre-line">
                  {section.content}
                </div>
              </div>
            ))}
          </div>
          <div className="flex justify-end gap-2 mt-6">
            <Button variant="outline" onClick={() => copyToClipboard(viewReport)}>
              <Copy className="h-4 w-4 mr-2" />
              Copiar
            </Button>
            <Button onClick={() => setViewReport(null)}>Cerrar</Button>
          </div>
        </Dialog>
      )}
    </div>
  )
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

  const { data: clients = [] } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list("active"),
    enabled: open && type === "client_status",
  })

  const { data: projects = [] } = useQuery({
    queryKey: ["projects"],
    queryFn: () => projectsApi.list({ status: "active" }),
    enabled: open && type === "project_status",
  })

  const generateMutation = useMutation({
    mutationFn: reportsApi.generate,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reports"] })
      toast.success("Informe generado")
      onOpenChange(false)
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || "Error al generar informe")
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    generateMutation.mutate({
      type,
      client_id: type === "client_status" ? clientId : null,
      project_id: type === "project_status" ? projectId : null,
      period,
    })
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

        {type === "client_status" && (
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

        {(type === "client_status" || type === "weekly_summary") && (
          <div className="space-y-2">
            <Label>Período</Label>
            <Select
              value={period}
              onChange={(e) => setPeriod(e.target.value as ReportPeriod)}
            >
              <option value="week">Última semana</option>
              <option value="month">Último mes</option>
            </Select>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-4">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button type="submit" disabled={generateMutation.isPending}>
            {generateMutation.isPending ? "Generando..." : "Generar"}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
