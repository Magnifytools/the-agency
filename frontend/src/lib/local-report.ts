import { api } from "@/lib/api"
import { filenameFromDisposition, type PdfFile } from "@/lib/pdf-download"

/** Informe mensual SEO local de un cliente (`/api/clients/{id}/local-report`). */

export type SourceKind = "gbp_actual" | "gbp_anterior" | "gbp_ano_anterior" | "rastreo" | "captura" | "otro"
export type AiStatus = "running" | "done" | "failed" | null

export interface LocalReportConfig {
  template: string
  landing_url: string
  project_id: number | null
  settings: {
    grupos?: { tabla?: string; tarjeta?: string; excluir?: string[] }
    nombres_paginas?: Record<string, string>
    [key: string]: unknown
  }
  roadmap: { meses: Record<string, unknown> }
  updated_at: string | null
}

export interface LocalReportSummary {
  id: number
  period_start: string
  period_end: string
  period_label: string
  file_stem: string | null
  computed_at: string | null
  generated_at: string | null
  delivered_at: string | null
  checks_ok: boolean | null
  ai_status: AiStatus
  created_at: string | null
}

export interface LocalReportOverview {
  config: LocalReportConfig | null
  templates: string[]
  default_period: { start: string; end: string }
  reports: LocalReportSummary[]
}

export interface TechRow {
  titulo: string
  detalle: string
  estado: string
  siguiente: string
}

export interface RoadmapTask {
  nombre: string
  nombre_publico?: string
  estado: "previsto" | "hecho" | "curso" | "bloqueado" | "eliminado"
  evidencia?: string | null
  motivo?: string | null
  tarea_id?: number
}

export interface CheckItem {
  clave: string
  ok: boolean
  detalle: string
  problemas?: { campo: string; problema: string }[]
}

export interface ReportInputs {
  busquedas?: number | "Pendiente" | null
  personas_panel?: number | null
  terminos?: { q: string; apariciones: number; tipo?: string }[]
  observaciones?: string
  fecha_rastreo?: string
}

/** El `datos.json` de la plantilla (sólo lo que enseña la web). */
export interface ReportData {
  informe: { modo: string; nota: string; fecha_documento: string; mes_datos: string }
  gsc: {
    clics_mes: number
    clics_mes_anterior: number
    clics_mismo_mes_ano_anterior: number
    impresiones_mes: number
    impresiones_mes_anterior: number
    impresiones_mismo_mes_ano_anterior: number
    clics_trimestre_actual: number
    clics_trimestre_anterior: number
    intencion_mensual: { filas: { tipo: string; clics: number; prev_clics: number }[] }
    paginas: { nombre: string; ruta: string; clics: number; clics_anterior: number | null; clics_ano_anterior: number | null }[]
    paginas_totales: { actual: number; anterior: number; ano_anterior: number }
  }
  grupos: {
    consultas: { q: string; intencion: string; imp_actual: number; imp_anterior: number; clics_actual: number }[]
    resumen_mensual: { impresiones: number; impresiones_mes_anterior: number; clics: number }
  }
  google: {
    periodo: string
    vistas_perfil: number | null
    clics_llamada: number | null
    indicaciones: number | null
    busquedas_que_mostraron_ficha: number | string | null
  }
  tecnico: { filas_rastreo: TechRow[]; otros: TechRow[]; fecha_ultimo_crawl?: string; enlaces_redirigen?: number }
  editorial: Record<string, string>
  textos: Record<string, string>
  ga4: { disponible: boolean }
  contexto?: { periodos?: Record<string, { start: string; end: string; label: string }> }
}

export interface LocalReportDetail extends LocalReportSummary {
  datos: ReportData
  roadmap: { meses: Record<string, { titulo?: string; titulo_publico?: string; tareas: RoadmapTask[] }> }
  inputs: ReportInputs
  warnings: string[]
  checks: { ok: boolean; items: CheckItem[] } | null
  ai_error: string | null
  ai_drafted_at: string | null
  sources: { id: number; kind: SourceKind; filename: string; size: number; content_type: string; created_at: string | null }[]
  text_keys: string[]
  guide: { editorial: Record<string, string>; textos: Record<string, string> }
}

export interface TextsPatch {
  textos?: Record<string, string>
  editorial?: Record<string, string>
  informe?: { modo?: string; nota?: string }
  tecnico?: { filas_rastreo?: TechRow[]; otros?: TechRow[] }
  motivos?: Record<string, string>
  nombres_paginas?: Record<string, string>
  intenciones_grupos?: Record<string, string>
}

export const SOURCE_LABELS: Record<SourceKind, string> = {
  gbp_actual: "Ficha de Google · periodo",
  gbp_anterior: "Ficha de Google · periodo anterior",
  gbp_ano_anterior: "Ficha de Google · año anterior",
  rastreo: "Rastreo (Screaming Frog, Redirection 3xx Inlinks)",
  captura: "Captura",
  otro: "Otro",
}

export const EDITORIAL_LABELS: Record<string, string> = {
  resumen: "Resumen estratégico",
  web: "Visibilidad de la web",
  paginas: "Páginas más visitadas",
  analytics: "Tráfico de la web (Analytics)",
  intencion: "Marca y búsquedas genéricas",
  grupos: "Grupos y celebraciones",
  maps: "Ficha de Google",
  negocio: "Interés por grupos",
  tecnico: "Mejoras de la web",
}

const base = (clientId: number) => `/clients/${clientId}/local-report`
// Calcular son ~25 consultas a Google; generar arranca Chromium.
const SLOW = { timeout: 180_000 }

function file(clientId: number, reportId: number, kind: "html" | "pdf" | "datos", fallback: string): Promise<PdfFile> {
  return api
    .get<Blob>(`${base(clientId)}/reports/${reportId}/files/${kind}`, { responseType: "blob", timeout: 60_000 })
    .then((r) => ({ blob: r.data, filename: filenameFromDisposition(r.headers["content-disposition"], fallback) }))
}

export const localReportApi = {
  overview: (clientId: number) => api.get<LocalReportOverview>(base(clientId)).then((r) => r.data),
  createConfig: (clientId: number, template: string) =>
    api.post<LocalReportConfig>(`${base(clientId)}/config`, { template }).then((r) => r.data),
  updateConfig: (clientId: number, data: Partial<Pick<LocalReportConfig, "landing_url" | "project_id" | "settings">>) =>
    api.put<LocalReportConfig>(`${base(clientId)}/config`, data).then((r) => r.data),
  create: (clientId: number, period?: { period_start: string; period_end: string }) =>
    api.post<LocalReportDetail>(`${base(clientId)}/reports`, period ?? {}, SLOW).then((r) => r.data),
  get: (clientId: number, reportId: number) =>
    api.get<LocalReportDetail>(`${base(clientId)}/reports/${reportId}`).then((r) => r.data),
  recompute: (clientId: number, reportId: number) =>
    api.post<LocalReportDetail>(`${base(clientId)}/reports/${reportId}/recompute`, {}, SLOW).then((r) => r.data),
  updateInputs: (clientId: number, reportId: number, inputs: ReportInputs) =>
    api.put<LocalReportDetail>(`${base(clientId)}/reports/${reportId}/inputs`, inputs).then((r) => r.data),
  updateTexts: (clientId: number, reportId: number, patch: TextsPatch) =>
    api.patch<LocalReportDetail>(`${base(clientId)}/reports/${reportId}/texts`, patch).then((r) => r.data),
  upload: (clientId: number, reportId: number, kind: SourceKind, upload: File) => {
    const form = new FormData()
    form.append("kind", kind)
    form.append("file", upload)
    return api.post<LocalReportDetail>(`${base(clientId)}/reports/${reportId}/sources`, form, { timeout: 120_000 })
      .then((r) => r.data)
  },
  removeSource: (clientId: number, reportId: number, sourceId: number) =>
    api.delete<LocalReportDetail>(`${base(clientId)}/reports/${reportId}/sources/${sourceId}`).then((r) => r.data),
  draft: (clientId: number, reportId: number) =>
    api.post<LocalReportSummary>(`${base(clientId)}/reports/${reportId}/draft`).then((r) => r.data),
  generate: (clientId: number, reportId: number) =>
    api.post<LocalReportDetail>(`${base(clientId)}/reports/${reportId}/generate`, {}, SLOW).then((r) => r.data),
  deliver: (clientId: number, reportId: number) =>
    api.post<LocalReportDetail>(`${base(clientId)}/reports/${reportId}/deliver`).then((r) => r.data),
  newVersion: (clientId: number, reportId: number) =>
    api.post<LocalReportDetail>(`${base(clientId)}/reports/${reportId}/new-version`).then((r) => r.data),
  html: (clientId: number, reportId: number) => file(clientId, reportId, "html", `informe-${reportId}.html`),
  pdf: (clientId: number, reportId: number) => file(clientId, reportId, "pdf", `informe-${reportId}.pdf`),
  datos: (clientId: number, reportId: number) => file(clientId, reportId, "datos", `informe-${reportId}_datos.json`),
}

export const localReportKeys = {
  overview: (clientId: number) => ["local-report", clientId] as const,
  report: (clientId: number, reportId: number) => ["local-report", clientId, reportId] as const,
}

/** "término; apariciones" por línea ↔ lista de términos de la ficha. */
export function parseTerms(text: string): { q: string; apariciones: number }[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = /^(.*?)[;\t,]\s*([\d.]+)\s*$/.exec(line)
      if (!match) return { q: line, apariciones: Number.NaN }
      return { q: match[1].trim(), apariciones: Number(match[2].replace(/\./g, "")) }
    })
}

export function formatTerms(terms: { q: string; apariciones: number }[] | undefined): string {
  return (terms ?? []).map((t) => `${t.q}; ${t.apariciones}`).join("\n")
}

export function reportState(r: LocalReportSummary): { label: string; tone: "default" | "success" | "warning" } {
  if (r.delivered_at) return { label: "Entregado", tone: "success" }
  if (r.generated_at) return { label: "Generado sin entregar", tone: "warning" }
  return { label: "Borrador", tone: "default" }
}
