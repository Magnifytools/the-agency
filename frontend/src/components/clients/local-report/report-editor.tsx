import { useEffect, useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { AlertTriangle, CheckCircle2, Download, Trash2, XCircle } from "lucide-react"
import { saveFile, type PdfFile } from "@/lib/pdf-download"
import { getErrorMessage } from "@/lib/utils"
import {
  EDITORIAL_LABELS,
  SOURCE_LABELS,
  formatTerms,
  localReportApi,
  localReportKeys,
  parseTerms,
  reportState,
  type LocalReportDetail,
  type SourceKind,
  type TechRow,
  type TextsPatch,
} from "@/lib/local-report"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"

interface Props {
  clientId: number
  reportId: number
  canWrite: boolean
  onChanged: (reportId: number) => void
}

const nf = new Intl.NumberFormat("es-ES", { useGrouping: true })
const num = (v: number | null | undefined) => (v === null || v === undefined ? "Sin dato" : nf.format(v))
function pct(a: number | null | undefined, b: number | null | undefined) {
  if (a === null || a === undefined || !b) return "sin comparativa"
  const value = ((a - b) / b) * 100
  return `${value >= 0 ? "+" : ""}${value.toFixed(1).replace(".", ",")} %`
}

/** Una versión del informe: cifras, lo que sube el equipo, textos, plan, comprobaciones y archivos. */
export function ReportEditor({ clientId, reportId, canWrite, onChanged }: Props) {
  const qc = useQueryClient()
  const key = localReportKeys.report(clientId, reportId)
  const query = useQuery({
    queryKey: key,
    queryFn: () => localReportApi.get(clientId, reportId),
    // Mientras la IA redacta, se consulta cada pocos segundos.
    refetchInterval: (q) => (q.state.data?.ai_status === "running" ? 4000 : false),
  })
  const report = query.data
  const [confirmDeliver, setConfirmDeliver] = useState(false)

  const update = (data: LocalReportDetail) => {
    qc.setQueryData(key, data)
    onChanged(data.id)
  }
  const onError = (fallback: string) => (e: unknown) => toast.error(getErrorMessage(e, fallback))

  const recompute = useMutation({
    mutationFn: () => localReportApi.recompute(clientId, reportId),
    onSuccess: (d) => { update(d); toast.success("Cifras actualizadas. Los textos se conservan.") },
    onError: onError("No se pudieron recalcular las cifras"),
  })
  const draft = useMutation({
    mutationFn: () => localReportApi.draft(clientId, reportId),
    onSuccess: () => {
      toast.success("La IA está redactando los textos. Tarda un par de minutos.")
      void query.refetch()
      onChanged(reportId)
    },
    onError: onError("No se pudo pedir el borrador"),
  })
  const generate = useMutation({
    mutationFn: () => localReportApi.generate(clientId, reportId),
    onSuccess: (d) => {
      update(d)
      if (d.checks?.ok) toast.success("Informe generado y comprobado")
      else toast.warning("Informe generado, pero alguna comprobación falla: revísala antes de entregarlo")
    },
    onError: onError("No se pudo generar el informe"),
  })
  const deliver = useMutation({
    mutationFn: () => localReportApi.deliver(clientId, reportId),
    onSuccess: (d) => { update(d); toast.success("Marcado como entregado al cliente") },
    onError: onError("No se pudo marcar como entregado"),
  })
  const newVersion = useMutation({
    mutationFn: () => localReportApi.newVersion(clientId, reportId),
    onSuccess: (d) => { qc.setQueryData(localReportKeys.report(clientId, d.id), d); onChanged(d.id) },
    onError: onError("No se pudo crear la versión nueva"),
  })

  // Al terminar la IA, aviso.
  const aiStatus = report?.ai_status
  const aiError = report?.ai_error
  const lastAi = useRef(aiStatus)
  useEffect(() => {
    if (lastAi.current === "running" && aiStatus === "done") toast.success("Borrador de textos listo: revísalo antes de generar")
    if (lastAi.current === "running" && aiStatus === "failed") toast.error(aiError || "La IA no pudo redactar")
    // La lista de versiones también enseña el estado: se refresca al terminar.
    if (lastAi.current === "running" && aiStatus !== "running") onChanged(reportId)
    lastAi.current = aiStatus
  }, [aiStatus, aiError, onChanged, reportId])

  if (query.isLoading) return <p className="text-sm text-muted-foreground">Cargando la versión…</p>
  if (!report) return <p className="text-sm text-destructive">{getErrorMessage(query.error, "No se pudo cargar la versión")}</p>

  const editable = canWrite && !report.delivered_at && report.ai_status !== "running"
  const state = reportState(report)
  const download = (fn: () => Promise<PdfFile>) => fn().then(saveFile).catch(onError("No se pudo descargar"))

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
          <div>
            <CardTitle as="h2" className="text-base text-foreground">Informe de {report.period_label}</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              {report.datos.informe.modo} · versión #{report.id}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={state.tone}>{state.label}</Badge>
            {report.ai_status === "running" && <Badge variant="secondary">Redactando con IA…</Badge>}
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {editable && (
              <>
                <Button size="sm" variant="outline" onClick={() => recompute.mutate()} isLoading={recompute.isPending}>
                  Recalcular cifras
                </Button>
                <Button size="sm" variant="outline" onClick={() => draft.mutate()} isLoading={draft.isPending}>
                  Redactar textos con IA
                </Button>
                <Button size="sm" onClick={() => generate.mutate()} isLoading={generate.isPending}>
                  Generar HTML y PDF
                </Button>
              </>
            )}
            {report.generated_at && (
              <>
                <Button size="sm" variant="outline" onClick={() => download(() => localReportApi.html(clientId, reportId))}>
                  <Download className="mr-1.5 h-3.5 w-3.5" /> HTML
                </Button>
                <Button size="sm" variant="outline" onClick={() => download(() => localReportApi.pdf(clientId, reportId))}>
                  <Download className="mr-1.5 h-3.5 w-3.5" /> PDF
                </Button>
              </>
            )}
            <Button size="sm" variant="ghost" onClick={() => download(() => localReportApi.datos(clientId, reportId))}>
              datos.json
            </Button>
            {canWrite && report.generated_at && !report.delivered_at && (
              <Button size="sm" variant="secondary" onClick={() => setConfirmDeliver(true)} disabled={!report.checks?.ok}>
                Marcar como entregado
              </Button>
            )}
            {canWrite && report.delivered_at && (
              <Button size="sm" variant="outline" onClick={() => newVersion.mutate()} isLoading={newVersion.isPending}>
                Nueva versión
              </Button>
            )}
          </div>
          {report.ai_status === "failed" && report.ai_error && (
            <p className="text-xs text-destructive">IA: {report.ai_error}</p>
          )}
          {report.ai_status === "done" && report.ai_error && (
            <p className="text-xs text-amber-600">{report.ai_error}</p>
          )}
          {report.delivered_at && (
            <p className="text-xs text-muted-foreground">
              Entregada: queda tal cual la recibió el cliente. Para cambiar algo, crea una versión nueva.
            </p>
          )}
          {report.warnings.length > 0 && (
            <ul className="space-y-1 rounded-[10px] border border-amber-500/30 bg-amber-500/5 p-3 text-xs">
              {report.warnings.map((w) => (
                <li key={w} className="flex gap-2"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />{w}</li>
              ))}
            </ul>
          )}
          {report.checks && <Checks checks={report.checks} />}
        </CardContent>
      </Card>

      <Figures report={report} />
      <Sources clientId={clientId} report={report} editable={editable} onUpdate={update} />
      {/* Se monta de nuevo cuando la IA o un recálculo cambian los textos de fondo. */}
      <Texts key={`${report.id}-${report.ai_drafted_at}-${report.computed_at}`} clientId={clientId} report={report}
        editable={editable} onUpdate={update} />

      <ConfirmDialog
        open={confirmDeliver}
        onOpenChange={setConfirmDeliver}
        title="¿Marcar como entregado al cliente?"
        description="La versión queda congelada tal cual (HTML, PDF y datos). Para corregirla después habrá que crear una versión nueva."
        confirmLabel="Marcar como entregado"
        onConfirm={() => { setConfirmDeliver(false); deliver.mutate() }}
      />
    </div>
  )
}

function Checks({ checks }: { checks: NonNullable<LocalReportDetail["checks"]> }) {
  return (
    <div className="rounded-[10px] border border-border p-3 text-xs">
      <p className="mb-2 font-semibold">{checks.ok ? "Comprobaciones superadas" : "Hay comprobaciones que fallan"}</p>
      <ul className="space-y-1">
        {checks.items.map((item) => (
          <li key={item.clave}>
            <span className="flex items-center gap-2">
              {item.ok ? <CheckCircle2 className="h-3.5 w-3.5 text-green-600" /> : <XCircle className="h-3.5 w-3.5 text-destructive" />}
              {item.detalle}
            </span>
            {item.problemas && item.problemas.length > 0 && (
              <ul className="ml-6 mt-1 list-disc text-muted-foreground">
                {item.problemas.map((p) => <li key={`${p.campo}-${p.problema}`}>{p.campo}: {p.problema}</li>)}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function Stat({ label, value, foot }: { label: string; value: string; foot?: string }) {
  return (
    <div className="rounded-[10px] border border-border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mono mt-1 text-lg font-semibold">{value}</p>
      {foot && <p className="mt-0.5 text-[11px] text-muted-foreground">{foot}</p>}
    </div>
  )
}

function Figures({ report }: { report: LocalReportDetail }) {
  const { gsc, grupos, google } = report.datos
  const [marca, generica] = gsc.intencion_mensual.filas
  const visibles = marca.clics + generica.clics
  return (
    <Card>
      <CardHeader><CardTitle as="h2">Cifras calculadas</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Clics a la página principal" value={num(gsc.clics_mes)}
            foot={`${pct(gsc.clics_mes, gsc.clics_mes_anterior)} vs. anterior · ${pct(gsc.clics_mes, gsc.clics_mismo_mes_ano_anterior)} interanual`} />
          <Stat label="Impresiones" value={num(gsc.impresiones_mes)}
            foot={`${pct(gsc.impresiones_mes, gsc.impresiones_mes_anterior)} vs. anterior · ${pct(gsc.impresiones_mes, gsc.impresiones_mismo_mes_ano_anterior)} interanual`} />
          <Stat label="Clics con la marca" value={num(marca.clics)}
            foot={`${visibles ? Math.round((marca.clics / visibles) * 100) : 0} % de ${num(visibles)} identificados`} />
          <Stat label="Clics sin la marca" value={num(generica.clics)} foot={`${num(generica.prev_clics)} el periodo anterior`} />
          <Stat label="Grupos y eventos (impresiones)" value={num(grupos.resumen_mensual.impresiones)}
            foot={`${num(grupos.resumen_mensual.clics)} clics · ${num(grupos.resumen_mensual.impresiones_mes_anterior)} antes`} />
          <Stat label="Clics de toda la web" value={num(gsc.paginas_totales.actual)}
            foot={`${pct(gsc.paginas_totales.actual, gsc.paginas_totales.anterior)} vs. anterior`} />
          <Stat label="Personas que vieron la ficha" value={num(google.vistas_perfil)} foot={google.periodo} />
          <Stat label="Llamadas · cómo llegar" value={`${num(google.clics_llamada)} · ${num(google.indicaciones)}`}
            foot={report.datos.ga4.disponible ? "Analytics con datos" : "Analytics pendiente"} />
        </div>
        <Plan report={report} />
      </CardContent>
    </Card>
  )
}

const STATE_LABELS: Record<string, string> = {
  previsto: "Prevista", hecho: "Realizada", curso: "En curso", bloqueado: "En espera", eliminado: "Eliminada",
}

function Plan({ report }: { report: LocalReportDetail }) {
  const months = Object.entries(report.roadmap.meses ?? {}).sort(([a], [b]) => a.localeCompare(b))
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-xs font-semibold text-muted-foreground">Plan de trabajo (estado de las tareas)</summary>
      <div className="mt-2 space-y-3">
        {months.map(([mon, month]) => (
          <div key={mon}>
            <p className="text-xs font-semibold">{mon} · {month.titulo_publico || month.titulo}</p>
            <ul className="mt-1 space-y-0.5 text-xs">
              {month.tareas.map((t) => (
                <li key={t.nombre} className="flex flex-wrap gap-2">
                  <span className="w-20 shrink-0 text-muted-foreground">{STATE_LABELS[t.estado] ?? t.estado}</span>
                  <span>{t.nombre_publico || t.nombre}{t.tarea_id ? ` (#${t.tarea_id})` : ""}</span>
                  {t.evidencia && <span className="text-muted-foreground">· {t.evidencia}</span>}
                  {t.motivo && <span className="text-muted-foreground">· {t.motivo}</span>}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </details>
  )
}

const UPLOADS: SourceKind[] = ["gbp_actual", "gbp_anterior", "gbp_ano_anterior", "rastreo", "captura"]

function Sources({ clientId, report, editable, onUpdate }: {
  clientId: number
  report: LocalReportDetail
  editable: boolean
  onUpdate: (d: LocalReportDetail) => void
}) {
  const inputs = report.inputs
  const periods = report.datos.contexto?.periodos
  const [pending, setPending] = useState(inputs.busquedas === "Pendiente")
  const [searches, setSearches] = useState(typeof inputs.busquedas === "number" ? String(inputs.busquedas) : "")
  const [people, setPeople] = useState(inputs.personas_panel != null ? String(inputs.personas_panel) : "")
  const [terms, setTerms] = useState(formatTerms(inputs.terminos))
  const [notes, setNotes] = useState(inputs.observaciones ?? "")
  const [crawlDay, setCrawlDay] = useState(inputs.fecha_rastreo ?? "")

  const upload = useMutation({
    mutationFn: ({ kind, file }: { kind: SourceKind; file: File }) => localReportApi.upload(clientId, report.id, kind, file),
    onSuccess: (d) => { onUpdate(d); toast.success("Archivo subido") },
    onError: (e) => toast.error(getErrorMessage(e, "No se pudo subir el archivo")),
  })
  const remove = useMutation({
    mutationFn: (sourceId: number) => localReportApi.removeSource(clientId, report.id, sourceId),
    onSuccess: onUpdate,
    onError: (e) => toast.error(getErrorMessage(e, "No se pudo quitar el archivo")),
  })
  const save = useMutation({
    mutationFn: () => {
      const parsed = parseTerms(terms)
      const bad = parsed.find((t) => Number.isNaN(t.apariciones))
      if (bad) return Promise.reject(new Error(`Falta el número en "${bad.q}" (formato: término; apariciones)`))
      return localReportApi.updateInputs(clientId, report.id, {
        busquedas: pending ? "Pendiente" : searches ? Number(searches.replace(/\./g, "")) : null,
        personas_panel: people ? Number(people.replace(/\./g, "")) : null,
        terminos: parsed,
        observaciones: notes,
        fecha_rastreo: crawlDay || undefined,
      })
    },
    onSuccess: (d) => { onUpdate(d); toast.success("Datos de la ficha guardados") },
    onError: (e) => toast.error(e instanceof Error && !("isAxiosError" in e) ? e.message : getErrorMessage(e, "No se pudieron guardar")),
  })

  const expected: Partial<Record<SourceKind, string | undefined>> = {
    gbp_actual: periods?.actual?.label, gbp_anterior: periods?.anterior?.label, gbp_ano_anterior: periods?.ano_anterior?.label,
  }

  return (
    <Card>
      <CardHeader><CardTitle as="h2">Lo que no tiene The Agency</CardTitle></CardHeader>
      <CardContent className="space-y-5 text-sm">
        <p className="text-xs text-muted-foreground">
          Ficha del restaurante: business.google.com/locations → cuenta de la agencia → la ficha → Acciones &gt;
          Estadísticas → exportar el CSV con las fechas de cada periodo (sin cambiar el nombre del archivo: lleva las fechas).
        </p>
        <ul className="space-y-2">
          {UPLOADS.map((kind) => {
            const files = report.sources.filter((s) => s.kind === kind)
            return (
              <li key={kind} className="flex flex-wrap items-center justify-between gap-2 rounded-[10px] border border-border px-3 py-2">
                <span>
                  <span className="font-medium">{SOURCE_LABELS[kind]}</span>
                  {expected[kind] && <span className="text-xs text-muted-foreground"> · {expected[kind]}</span>}
                  {files.map((f) => (
                    <span key={f.id} className="ml-2 inline-flex items-center gap-1 text-xs text-muted-foreground">
                      {f.filename}
                      {editable && (
                        <button type="button" aria-label={`Quitar ${f.filename}`} onClick={() => remove.mutate(f.id)}>
                          <Trash2 className="h-3 w-3" />
                        </button>
                      )}
                    </span>
                  ))}
                </span>
                {editable && (
                  <input type="file" accept={kind === "captura" ? "image/*,application/pdf" : ".csv,text/csv"}
                    aria-label={`Subir ${SOURCE_LABELS[kind]}`} className="text-xs"
                    onChange={(e) => {
                      const file = e.target.files?.[0]
                      e.target.value = ""
                      if (file) upload.mutate({ kind, file })
                    }} />
                )}
              </li>
            )
          })}
        </ul>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-xs text-muted-foreground">
            Búsquedas que han mostrado la ficha
            <Input value={searches} onChange={(e) => setSearches(e.target.value)} disabled={!editable || pending}
              inputMode="numeric" className="mt-1" />
            <span className="mt-1 flex items-center gap-2">
              <input type="checkbox" checked={pending} disabled={!editable} onChange={(e) => setPending(e.target.checked)} />
              Pendiente (mes en curso: Google la publica a principios del mes siguiente)
            </span>
          </label>
          <label className="text-xs text-muted-foreground">
            Personas que vieron la ficha (captura del panel, para comprobar las fechas)
            <Input value={people} onChange={(e) => setPeople(e.target.value)} disabled={!editable} inputMode="numeric" className="mt-1" />
          </label>
        </div>
        <label className="block text-xs text-muted-foreground">
          Términos de búsqueda de la ficha (uno por línea: término; apariciones)
          <Textarea value={terms} onChange={(e) => setTerms(e.target.value)} disabled={!editable || pending} rows={4} className="mt-1 font-mono" />
        </label>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-xs text-muted-foreground">
            Fecha del rastreo subido
            <Input type="date" value={crawlDay} onChange={(e) => setCrawlDay(e.target.value)} disabled={!editable} className="mt-1" />
          </label>
        </div>
        <label className="block text-xs text-muted-foreground">
          Observaciones del equipo (2-3: campañas, cierres, cambios en la ficha, la carta…)
          <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} disabled={!editable} rows={3} className="mt-1" />
        </label>
        {editable && <Button size="sm" onClick={() => save.mutate()} isLoading={save.isPending}>Guardar estos datos</Button>}
      </CardContent>
    </Card>
  )
}

function Texts({ clientId, report, editable, onUpdate }: {
  clientId: number
  report: LocalReportDetail
  editable: boolean
  onUpdate: (d: LocalReportDetail) => void
}) {
  const { datos } = report
  const initial = editableTexts(report)
  const [draft, setDraft] = useState(initial)
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial)

  const save = useMutation({
    mutationFn: () => {
      const patch: TextsPatch = { informe: draft.informe, tecnico: draft.tecnico, motivos: draft.motivos, editorial: {}, textos: {} }
      for (const [k, v] of Object.entries(draft.editorial)) if (v !== initial.editorial[k]) patch.editorial![k] = v
      for (const [k, v] of Object.entries(draft.textos)) if (v !== initial.textos[k]) patch.textos![k] = v
      return localReportApi.updateTexts(clientId, report.id, patch)
    },
    onSuccess: (d) => { onUpdate(d); toast.success("Textos guardados") },
    onError: (e) => toast.error(getErrorMessage(e, "No se pudieron guardar los textos")),
  })
  const missing = report.text_keys.filter((k) => !draft.textos[k]?.trim()).length
  const blocked = Object.values(report.roadmap.meses ?? {}).flatMap((m) => m.tareas).filter((t) => t.estado === "bloqueado" && t.tarea_id)
  const setEditorial = (k: string, v: string) => setDraft((d) => ({ ...d, editorial: { ...d.editorial, [k]: v } }))
  const setText = (k: string, v: string) => setDraft((d) => ({ ...d, textos: { ...d.textos, [k]: v } }))

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 space-y-0">
        <CardTitle as="h2">Textos del informe</CardTitle>
        <span className="text-xs text-muted-foreground">
          {missing ? `${missing} de ${report.text_keys.length} notas sin escribir` : "Todas las notas escritas"}
        </span>
      </CardHeader>
      <CardContent className="space-y-6 text-sm">
        <section className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Portada</h3>
          <Field label="Modo (periodo de los datos)" value={draft.informe.modo} disabled={!editable} rows={1}
            onChange={(v) => setDraft((d) => ({ ...d, informe: { ...d.informe, modo: v } }))} />
          <Field label="Nota del informe" value={draft.informe.nota} disabled={!editable} rows={2}
            onChange={(v) => setDraft((d) => ({ ...d, informe: { ...d.informe, nota: v } }))} />
        </section>
        <section className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Lectura de cada sección</h3>
          {Object.keys(EDITORIAL_LABELS)
            .filter((k) => k !== "analytics" || datos.ga4.disponible)
            .map((k) => (
              <Field key={k} label={EDITORIAL_LABELS[k]} hint={report.guide.editorial[k]} value={draft.editorial[k] ?? ""}
                disabled={!editable} rows={4} onChange={(v) => setEditorial(k, v)} />
            ))}
        </section>
        <section className="space-y-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Notas de periodo y fuente</h3>
          {report.text_keys.map((k) => (
            <Field key={k} label={k} hint={report.guide.textos[k]} value={draft.textos[k] ?? ""} disabled={!editable}
              rows={2} mono onChange={(v) => setText(k, v)} />
          ))}
        </section>
        <TechRows title="Mejoras de la web: enlaces que redirigen (rastreo)" rows={draft.tecnico.filas_rastreo} disabled={!editable}
          onChange={(rows) => setDraft((d) => ({ ...d, tecnico: { ...d.tecnico, filas_rastreo: rows } }))} />
        <TechRows title="Mejoras de la web: otras incidencias" rows={draft.tecnico.otros} disabled={!editable}
          onChange={(rows) => setDraft((d) => ({ ...d, tecnico: { ...d.tecnico, otros: rows } }))} />
        {blocked.length > 0 && (
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Motivo de las tareas en espera (lo ve el cliente)</h3>
            {blocked.map((t) => (
              <Field key={t.tarea_id} label={`${t.nombre_publico || t.nombre} (#${t.tarea_id})`} rows={1} disabled={!editable}
                value={draft.motivos[String(t.tarea_id)] ?? ""}
                onChange={(v) => setDraft((d) => ({ ...d, motivos: { ...d.motivos, [String(t.tarea_id)]: v } }))} />
            ))}
          </section>
        )}
        {editable && (
          <div className="sticky bottom-0 flex items-center gap-3 border-t border-border bg-card py-3">
            <Button size="sm" onClick={() => save.mutate()} isLoading={save.isPending} disabled={!dirty}>Guardar textos</Button>
            {dirty && <span className="text-xs text-amber-600">Cambios sin guardar</span>}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function editableTexts(report: LocalReportDetail) {
  const { datos } = report
  return {
    editorial: { ...datos.editorial },
    textos: { ...datos.textos },
    informe: { modo: datos.informe.modo, nota: datos.informe.nota },
    tecnico: { filas_rastreo: datos.tecnico.filas_rastreo ?? [], otros: datos.tecnico.otros ?? [] },
    motivos: Object.fromEntries(Object.values(report.roadmap.meses ?? {}).flatMap((m) => m.tareas)
      .filter((t) => t.estado === "bloqueado" && t.tarea_id).map((t) => [String(t.tarea_id), t.motivo ?? ""])),
  }
}

function Field({ label, hint, value, onChange, disabled, rows, mono }: {
  label: string
  hint?: string
  value: string
  onChange: (v: string) => void
  disabled?: boolean
  rows: number
  mono?: boolean
}) {
  return (
    <label className="block text-xs text-muted-foreground">
      <span className={mono ? "font-mono" : "font-medium text-foreground"}>{label}</span>
      {hint && <span className="mt-0.5 block text-[11px]">{hint}</span>}
      <Textarea value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} rows={rows}
        className="mt-1 text-sm text-foreground" />
    </label>
  )
}

const EMPTY_ROW: TechRow = { titulo: "", detalle: "", estado: "", siguiente: "" }

function TechRows({ title, rows, onChange, disabled }: {
  title: string
  rows: TechRow[]
  onChange: (rows: TechRow[]) => void
  disabled: boolean
}) {
  const set = (i: number, key: keyof TechRow, v: string) => onChange(rows.map((r, j) => (j === i ? { ...r, [key]: v } : r)))
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      {rows.length === 0 && <p className="text-xs text-muted-foreground">Sin filas: la plantilla enseña las del estudio inicial.</p>}
      {rows.map((row, i) => (
        <div key={i} className="grid grid-cols-1 gap-2 rounded-[10px] border border-border p-2 sm:grid-cols-2">
          {(["titulo", "estado", "detalle", "siguiente"] as const).map((k) => (
            <Input key={k} value={row[k]} onChange={(e) => set(i, k, e.target.value)} disabled={disabled}
              placeholder={{ titulo: "Incidencia", estado: "Situación", detalle: "Detalle", siguiente: "Siguiente paso" }[k]}
              aria-label={`${title}: ${k}`} />
          ))}
          {!disabled && (
            <Button size="sm" variant="ghost" className="justify-self-start" onClick={() => onChange(rows.filter((_, j) => j !== i))}>
              Quitar fila
            </Button>
          )}
        </div>
      ))}
      {!disabled && <Button size="sm" variant="outline" onClick={() => onChange([...rows, EMPTY_ROW])}>Añadir fila</Button>}
    </section>
  )
}
