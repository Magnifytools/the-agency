import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { useAuth } from "@/context/auth-context"
import { projectsApi } from "@/lib/api"
import { formatCivilDate } from "@/lib/dates"
import { getErrorMessage } from "@/lib/utils"
import {
  localReportApi,
  localReportKeys,
  reportState,
  type LocalReportConfig,
  type LocalReportOverview,
} from "@/lib/local-report"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { ReportEditor } from "./report-editor"

interface Props {
  clientId: number
}

/**
 * Informe mensual SEO local (área Resultados): The Agency calcula Search
 * Console, Analytics y el plan; el equipo sube la ficha de Google y el
 * rastreo, revisa los textos (borrador con IA) y genera el HTML con el PDF.
 */
export function LocalReportTab({ clientId }: Props) {
  const { hasPermission } = useAuth()
  const canWrite = hasPermission("digests", true)
  const qc = useQueryClient()
  const [selected, setSelected] = useState<number | null>(null)

  const overviewQuery = useQuery({
    queryKey: localReportKeys.overview(clientId),
    queryFn: () => localReportApi.overview(clientId),
  })
  const overview = overviewQuery.data

  if (overviewQuery.isLoading) return <p className="text-sm text-muted-foreground">Cargando el informe…</p>
  if (overviewQuery.isError || !overview) {
    return <p className="text-sm text-destructive">{getErrorMessage(overviewQuery.error, "No se pudo cargar el informe")}</p>
  }
  if (!overview.config) return <SetupCard clientId={clientId} overview={overview} canWrite={canWrite} />

  const reportId = selected ?? overview.reports[0]?.id ?? null
  return (
    <div className="space-y-6">
      <ReportsCard
        clientId={clientId}
        overview={overview}
        canWrite={canWrite}
        selected={reportId}
        onSelect={setSelected}
        onCreated={(id) => {
          setSelected(id)
          void qc.invalidateQueries({ queryKey: localReportKeys.overview(clientId) })
        }}
      />
      {reportId !== null && (
        <ReportEditor key={reportId} clientId={clientId} reportId={reportId} canWrite={canWrite}
          onChanged={(id) => {
            if (id !== reportId) setSelected(id)
            void qc.invalidateQueries({ queryKey: localReportKeys.overview(clientId) })
          }} />
      )}
      <ConfigCard clientId={clientId} config={overview.config} canWrite={canWrite} />
    </div>
  )
}

function SetupCard({ clientId, overview, canWrite }: { clientId: number; overview: LocalReportOverview; canWrite: boolean }) {
  const qc = useQueryClient()
  const [template, setTemplate] = useState(overview.templates[0] ?? "")
  const create = useMutation({
    mutationFn: () => localReportApi.createConfig(clientId, template),
    onSuccess: () => {
      toast.success("Informe SEO local activado")
      void qc.invalidateQueries({ queryKey: localReportKeys.overview(clientId) })
    },
    onError: (e) => toast.error(getErrorMessage(e, "No se pudo activar el informe")),
  })
  return (
    <Card>
      <CardHeader><CardTitle as="h2">Informe SEO local</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          Este cliente aún no tiene informe mensual SEO local. Al activarlo se parte de la plantilla elegida
          (página principal, familias de consultas de grupos y plan de trabajo), que luego se ajusta aquí.
        </p>
        {canWrite ? (
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs text-muted-foreground">
              Plantilla
              <Select value={template} onChange={(e) => setTemplate(e.target.value)} className="mt-1 w-48">
                {overview.templates.map((t) => <option key={t} value={t}>{t}</option>)}
              </Select>
            </label>
            <Button onClick={() => create.mutate()} isLoading={create.isPending} disabled={!template}>
              Activar informe
            </Button>
          </div>
        ) : (
          <p className="text-muted-foreground">Pide a quien gestiona los resúmenes que lo active.</p>
        )}
      </CardContent>
    </Card>
  )
}

function ReportsCard({ clientId, overview, canWrite, selected, onSelect, onCreated }: {
  clientId: number
  overview: LocalReportOverview
  canWrite: boolean
  selected: number | null
  onSelect: (id: number) => void
  onCreated: (id: number) => void
}) {
  const [custom, setCustom] = useState(false)
  const [start, setStart] = useState(overview.default_period.start)
  const [end, setEnd] = useState(overview.default_period.end)
  const create = useMutation({
    mutationFn: () => localReportApi.create(clientId, custom ? { period_start: start, period_end: end } : undefined),
    onSuccess: (report) => {
      toast.success(`Informe de ${report.period_label} calculado`)
      onCreated(report.id)
    },
    onError: (e) => toast.error(getErrorMessage(e, "No se pudo calcular el informe")),
  })
  const defaultLabel = formatCivilDate(overview.default_period.start, { month: "long", year: "numeric" })

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
        <CardTitle as="h2">Informe SEO local · versiones</CardTitle>
        {canWrite && (
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input type="checkbox" checked={custom} onChange={(e) => setCustom(e.target.checked)} />
              Otro periodo
            </label>
            {custom && (
              <>
                <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} className="h-8 w-40"
                  aria-label="Inicio del periodo" />
                <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="h-8 w-40"
                  aria-label="Final del periodo" />
              </>
            )}
            <Button size="sm" onClick={() => create.mutate()} isLoading={create.isPending}>
              {custom ? "Calcular informe" : `Calcular el de ${defaultLabel}`}
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent>
        {create.isPending && (
          <p className="mb-3 text-xs text-muted-foreground">
            Consultando Search Console, Analytics y las tareas del plan (puede tardar un minuto)…
          </p>
        )}
        {overview.reports.length === 0 ? (
          <p className="text-sm text-muted-foreground">Todavía no hay ningún informe.</p>
        ) : (
          <ul className="divide-y divide-border">
            {overview.reports.map((r) => {
              const state = reportState(r)
              return (
                <li key={r.id}>
                  <button type="button" onClick={() => onSelect(r.id)}
                    className={`flex w-full flex-wrap items-center justify-between gap-2 px-2 py-2.5 text-left text-sm transition-colors hover:bg-muted/40 ${selected === r.id ? "bg-muted/50" : ""}`}>
                    <span className="font-medium">{r.period_label} <span className="text-xs text-muted-foreground">#{r.id}</span></span>
                    <span className="flex items-center gap-2">
                      {r.ai_status === "running" && <Badge variant="secondary">Redactando con IA…</Badge>}
                      {r.checks_ok === false && <Badge variant="destructive">Comprobaciones con fallos</Badge>}
                      <Badge variant={state.tone}>{state.label}</Badge>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

function ConfigCard({ clientId, config, canWrite }: { clientId: number; config: LocalReportConfig; canWrite: boolean }) {
  const qc = useQueryClient()
  const { hasPermission } = useAuth()
  const [open, setOpen] = useState(false)
  const [landing, setLanding] = useState(config.landing_url)
  const [projectId, setProjectId] = useState<string>(config.project_id ? String(config.project_id) : "")
  const [tabla, setTabla] = useState(config.settings.grupos?.tabla ?? "")
  const [tarjeta, setTarjeta] = useState(config.settings.grupos?.tarjeta ?? "")
  const { data: projects = [] } = useQuery({
    queryKey: ["projects", "by-client", clientId],
    queryFn: () => projectsApi.listAll({ client_id: clientId }),
    // La lista de proyectos sólo se pide con lectura de Proyectos.
    enabled: open && hasPermission("projects"),
    staleTime: 60_000,
  })
  const save = useMutation({
    mutationFn: () => localReportApi.updateConfig(clientId, {
      landing_url: landing.trim(),
      project_id: projectId ? Number(projectId) : null,
      settings: { ...config.settings, grupos: { ...config.settings.grupos, tabla, tarjeta } },
    }),
    onSuccess: () => {
      toast.success("Configuración guardada. Se aplica al próximo cálculo.")
      void qc.invalidateQueries({ queryKey: localReportKeys.overview(clientId) })
    },
    onError: (e) => toast.error(getErrorMessage(e, "No se pudo guardar la configuración")),
  })

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle as="h2">Configuración del informe</CardTitle>
        <Button variant="ghost" size="sm" onClick={() => setOpen((v) => !v)}>{open ? "Ocultar" : "Ver"}</Button>
      </CardHeader>
      {open && (
        <CardContent className="space-y-4 text-sm">
          <p className="text-xs text-muted-foreground">
            Plantilla <strong>{config.template}</strong>. Los términos de marca son los del Control SEO del cliente
            (Ajustes). El plan de trabajo sale de las tareas "E1 - …", "E2 - …" del cliente.
          </p>
          <label className="block text-xs text-muted-foreground">
            Página principal del informe (Search Console, filtro "page equals")
            <Input value={landing} onChange={(e) => setLanding(e.target.value)} disabled={!canWrite} className="mt-1" />
          </label>
          <label className="block text-xs text-muted-foreground">
            Proyecto del plan de trabajo
            <Select value={projectId} onChange={(e) => setProjectId(e.target.value)} disabled={!canWrite} className="mt-1">
              <option value="">Sólo las tareas del cliente</option>
              {config.project_id && !projects.some((p) => p.id === config.project_id) && (
                <option value={config.project_id}>Proyecto #{config.project_id}</option>
              )}
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>
          </label>
          <label className="block text-xs text-muted-foreground">
            Consultas de la tabla de grupos (alternativas separadas por |)
            <Input value={tabla} onChange={(e) => setTabla(e.target.value)} disabled={!canWrite} className="mt-1 font-mono" />
          </label>
          <label className="block text-xs text-muted-foreground">
            Consultas de la tarjeta "Grupos y eventos" (sin marca)
            <Input value={tarjeta} onChange={(e) => setTarjeta(e.target.value)} disabled={!canWrite} className="mt-1 font-mono" />
          </label>
          {canWrite && (
            <Button size="sm" onClick={() => save.mutate()} isLoading={save.isPending}>Guardar configuración</Button>
          )}
        </CardContent>
      )}
    </Card>
  )
}
