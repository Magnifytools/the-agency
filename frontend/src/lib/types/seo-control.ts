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
}

export interface SeoPageRow extends SeoMoverBase {
  page: string
  section: string
  section_label: string
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
  queries: { gainers: SeoQueryRow[]; losers: SeoQueryRow[] } | null
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
  q?: string
  min_impressions: number
  limit: number
}

export interface SeoMoversResponse<Row> extends SeoSourceInfo {
  window: SeoWindow | null
  rows: Row[]
  total: number
}
