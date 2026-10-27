// Control SEO por cliente (GET /api/clients/{id}/seo y sus listados).
// Clics/impresiones sumados en la ventana; posición ponderada por impresiones;
// position_delta positivo = mejora.

export type SeoControlStatus =
  | "no_property"
  | "not_connected"
  | "reconnect_required"
  | "not_synced"
  | "backfilling"
  | "error"
  | "ok"

export type SeoWindowDays = 7 | 28

export interface SeoWindow {
  start: string
  end: string
  previous_start: string
  previous_end: string
  days: SeoWindowDays
}

export interface SeoTotalsSide {
  clicks: number
  impressions: number
  ctr: number | null
  position: number | null
}

export interface SeoTotals {
  current: SeoTotalsSide
  previous: SeoTotalsSide
  change: {
    clicks_pct: number | null
    impressions_pct: number | null
    ctr_delta: number | null
    position_delta: number | null
  }
}

export interface SeoClicksImpressions {
  clicks: number
  impressions: number
}

export interface SeoBrandSide {
  brand: SeoClicksImpressions
  non_brand: SeoClicksImpressions
  unclassified: SeoClicksImpressions
}

export interface SeoBrandWeek {
  week_start: string
  week_end: string
  brand_clicks: number
  non_brand_clicks: number
  unclassified_clicks: number
}

export interface SeoSection {
  key: string
  label: string
  clicks: number
  previous_clicks: number
  clicks_pct: number | null
  clicks_share: number | null
  impressions: number
  position: number | null
  position_delta: number | null
  pages: number
}

export type SeoMoverState = "new" | "lost" | "both"

interface SeoMoverBase {
  clicks: number
  previous_clicks: number
  clicks_delta: number
  clicks_pct: number | null
  impressions: number
  previous_impressions: number
  position: number | null
  previous_position: number | null
  position_delta: number | null
  state: SeoMoverState
}

export interface SeoQueryRow extends SeoMoverBase {
  query: string
  is_brand: boolean
  /** Posición en los últimos meses guardados (`trend_months`); null = no salió ese mes. */
  trend?: (number | null)[]
}

export interface SeoPageRow extends SeoMoverBase {
  page: string
  section: string
  section_label: string
  /** Grupo de URL de la página (sólo en el listado de páginas). */
  group?: string
}

interface SeoSourceInfo {
  status: SeoControlStatus
  site_url: string | null
  error_code: string | null
  last_synced_at: string | null
}

export interface ClientSeoSummary extends SeoSourceInfo {
  window: SeoWindow | null
  totals: SeoTotals | null
  brand: {
    terms: string[]
    current: SeoBrandSide
    previous: SeoBrandSide
    trend: SeoBrandWeek[]
  } | null
  sections: SeoSection[]
  queries: { gainers: SeoQueryRow[]; losers: SeoQueryRow[]; trend_months?: string[] } | null
  pages: { gainers: SeoPageRow[]; losers: SeoPageRow[] } | null
  coverage: { query_clicks_share: number | null } | null
}

export type SeoMoverSort = "clicks_gain" | "clicks_loss" | "position_gain" | "position_loss"
export type SeoBrandFilter = "all" | "brand" | "non_brand"

export interface SeoMoversParams {
  days: SeoWindowDays
  sort: SeoMoverSort
  brand?: SeoBrandFilter
  section?: string
  group?: string
  q?: string
  min_impressions: number
  limit: number
}

export interface SeoMoversResponse<Row> extends SeoSourceInfo {
  window: SeoWindow | null
  rows: Row[]
  total: number
  /** Sólo en consultas: meses de `trend` (día 1, ISO). */
  trend_months?: string[]
}

// ── Historial de una consulta (GET /seo/queries/history?query=) ──

export interface SeoHistoryPoint {
  clicks: number
  impressions: number
  /** Ponderada por impresiones; null si no hubo impresiones. */
  position: number | null
}

export interface SeoQueryHistory extends SeoSourceInfo {
  query: string
  is_brand: boolean | null
  /** Meses completos guardados (hasta 16, más los anteriores importados de The Engine). */
  months: (SeoHistoryPoint & { month: string; imported?: boolean })[]
  /** Días del detalle (hasta 120). */
  days: (SeoHistoryPoint & { date: string })[]
  /** false mientras no se hayan traído los meses de antes de los 120 días. */
  monthly_backfilled: boolean
}

// ── Grupos de URL ──

export type SeoGroupRuleType = "prefix" | "contains" | "regex"

export interface SeoPageGroupRule {
  type: SeoGroupRuleType
  value: string
}

export interface SeoPageGroup {
  name: string
  rules: SeoPageGroupRule[]
}

/** Misma forma que una sección; `key` = nombre del grupo ("Sin grupo" al final). */
export type SeoGroupRow = SeoSection

export interface SeoGroupsResponse extends SeoSourceInfo {
  window: SeoWindow | null
  groups: SeoGroupRow[]
  configured: number
}

// ── Leads por landing (GA4) ──

export interface LeadsChange {
  leads: number
  /** null si no hay datos de la ventana anterior con los que comparar. */
  previous: number | null
  change_pct: number | null
}

export interface ClientLeads {
  status: "ok" | "no_property" | "not_synced"
  events: string[]
  days: number
  property_id?: string
  error_code?: string | null
  start?: string
  end?: string
  previous_start?: string
  previous_end?: string
  comparable?: boolean
  total?: LeadsChange
  landings?: (LeadsChange & { landing_page: string })[]
  landing_count?: number
  channels?: (LeadsChange & { channel: string })[]
}

// ── Bloque B: anotaciones, antes/después y páginas que pierden tráfico ──

export type SeoAnnotationKind = "manual" | "google" | "web_change" | "task"

export interface SeoAnnotation {
  kind: SeoAnnotationKind
  id: number | string | null
  date: string
  end_date: string | null
  title: string
  author: string | null
  href: string | null
}

export interface SeoAnnotations {
  items: SeoAnnotation[]
  google_available: boolean
}

export interface SeoImpactSide {
  clicks: number
  impressions: number
  position: number | null
  start: string
  end: string
}

export interface SeoImpact {
  status: SeoControlStatus
  pivot: string
  scope: "site" | "page" | "group"
  page: string | null
  group: string | null
  reason: "too_early" | "outside_detail" | "no_data" | null
  available_from?: string
  detail_start?: string | null
  result: {
    days: number
    before: SeoImpactSide
    after: SeoImpactSide
    clicks_change_pct: number | null
    impressions_change_pct: number | null
    position_delta: number | null
    pages: number | null
  } | null
}

export interface SeoDecayRow {
  page: string
  current: { clicks: number; impressions: number; position: number | null }
  peak: { clicks: number; impressions: number; position: number | null; start: string; end: string }
  lost_clicks: number
  drop_pct: number | null
  cause: "position" | "demand" | "ctr"
}

export interface SeoDecay {
  status: SeoControlStatus
  rows: SeoDecayRow[]
  total?: number
  windows: number
  end?: string
  window_days?: number
}
