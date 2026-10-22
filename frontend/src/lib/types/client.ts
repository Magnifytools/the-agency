import type { ContractType, ClientStatus, ProfitabilityStatus } from "./common"
import type { EngineSummaryData, EngineAlert } from "./integration"
import type { Task } from "./task"
import type { ProjectCreate } from "./project"
import type { SeoPageGroup } from "./seo-control"

export type SeoTrend = "up" | "stable" | "down" | "drop_alert"

export interface Client {
  id: number
  name: string
  email: string | null
  phone: string | null
  company: string | null
  website: string | null
  contract_type: ContractType
  monthly_budget: number | null
  status: ClientStatus
  notes: string | null
  vat_number: string | null
  currency: string
  monthly_fee: number | null
  ga4_property_id: string | null
  gsc_url: string | null
  // Control SEO: búsquedas que cuentan como "de marca"
  brand_terms?: string[]
  // Control SEO: grupos de URL propios (el primero que acepta la página gana)
  seo_page_groups?: SeoPageGroup[]
  engine_project_id: number | null
  engine_content_count: number | null
  engine_keyword_count: number | null
  engine_avg_position: number | null
  engine_clicks_30d: number | null
  engine_impressions_30d: number | null
  engine_metrics_synced_at: string | null
  engine_summary_data: EngineSummaryData | null
  engine_alerts_data: { alerts: EngineAlert[] } | null
  // Semáforo SEO, derivado en backend del summary de Engine
  seo_clicks_change_pct: number | null
  seo_impressions_change_pct: number | null
  seo_trend: SeoTrend | null
  // Revenue intelligence
  is_internal: boolean
  intermediary_name: string | null
  is_intermediary_deal: boolean
  context?: string | null
  created_at: string
  updated_at: string
}

export interface ClientDocument {
  id: number
  client_id: number
  name: string
  description?: string | null
  mime_type: string
  size_bytes: number
  created_at: string
}

export interface ClientCreate {
  name: string
  email?: string | null
  phone?: string | null
  company?: string | null
  website?: string | null
  contract_type?: ContractType
  monthly_budget?: number | null
  status?: ClientStatus
  notes?: string | null
  vat_number?: string | null
  currency?: string
  monthly_fee?: number | null
  ga4_property_id?: string | null
  gsc_url?: string | null
  brand_terms?: string[]
  // Control SEO: grupos de URL propios (el primero que acepta la página gana)
  seo_page_groups?: SeoPageGroup[]
  engine_project_id?: number | null
  // Revenue intelligence
  is_internal?: boolean
  intermediary_name?: string | null
  is_intermediary_deal?: boolean
  context?: string | null
}

export interface ClientExtractProject {
  name?: string
  description?: string
  project_type?: string
  is_recurring?: boolean
  pricing_model?: string
  monthly_fee?: number
  unit_price?: number
  unit_label?: string
  scope?: string
  budget_amount?: number
  start_date?: string
  target_end_date?: string
}

export interface ClientExtractContact {
  name: string
  email?: string | null
  phone?: string | null
  position?: string | null
  company?: string | null
  is_primary?: boolean
  notes?: string | null
  language?: string | null
}

export interface ClientExtract extends Partial<ClientCreate> {
  contacts?: ClientExtractContact[] | null
  project?: ClientExtractProject | null
}

export interface ClientContact {
  id: number
  client_id: number
  name: string
  email: string | null
  phone: string | null
  position: string | null
  department: string | null
  preferred_channel: string | null
  language: string | null
  linkedin_url: string | null
  is_primary: boolean
  notes: string | null
  created_at: string
  updated_at: string
}

export interface ClientContactCreate {
  name: string
  email?: string | null
  phone?: string | null
  position?: string | null
  department?: string | null
  preferred_channel?: string | null
  language?: string | null
  linkedin_url?: string | null
  is_primary?: boolean
  notes?: string | null
}

export type ClientOnboardingProjectCreate = Omit<ProjectCreate, "client_id">

export interface ClientOnboardingCreate {
  client: ClientCreate
  contacts: ClientContactCreate[]
  project: ClientOnboardingProjectCreate | null
}

export interface ClientOnboardingResult {
  status: "confirmed" | "not_committed" | "processing"
  client_id: number | null
  contact_ids: number[]
  project_id: number | null
  replayed: boolean
  undo_state: "available" | "undone" | "unavailable"
  change_log_id: number | null
}

// Client Dashboard
export interface ClientDashboard {
  hours_this_month: number
  hours_last_month: number
  hours_trend_pct: number
  total_cost_this_month: number
  monthly_fee: number
  monthly_budget: number
  margin: number
  margin_pct: number
  profitability_status: ProfitabilityStatus
  tasks_by_status: Record<string, number>
  tasks_overdue: number
  tasks_due_this_week: number
  monthly_hours_breakdown: Record<string, number>
  team_breakdown: { user_id: number; full_name: string; hours: number; cost: number }[]
  actual_income: number
  monthly_profitability: Record<string, { income: number; cost: number }>
}

export type ClientStatusLevel = "ok" | "watch" | "act" | "no_data"

/** Estado explicado de un cliente: una fila de la cartera. */
export interface ClientStatusRow {
  client_id: number
  client_name: string
  status: ClientStatusLevel
  /** Motivos de Vigilar/Actuar, lo que pide actuar primero. */
  reasons: string[]
  seo: {
    source: "search_console"
    clicks: number
    clicks_previous: number
    change_pct: number | null
    trend: "up" | "stable" | "down" | "drop_alert" | null
    as_of: string | null
  } | null
  /** Una señal por cadencia encendida (mensual primero); vacía sin política. */
  digests: ClientDigestSignal[]
  /** La peor de `digests` (compatibilidad). */
  digest: ClientDigestSignal | null
  /** null = quien mira no puede leer tareas. */
  tasks: { overdue: number; waiting: number; followups_late: number } | null
  /** null = quien mira no puede leer horas. fee y consumption_pct sólo para admins con cuota. */
  month: { hours: number; fee?: number; consumption_pct?: number } | null
  /**
   * Sólo en el estado de un cliente (no en la cartera) y si quien mira lee tareas
   * y resúmenes: tareas completadas desde `since` que ningún resumen con entrega
   * confirmada cubre todavía. `count` va sin límite; `items`, las 5 últimas.
   */
  ready?: { since: string; count: number; items: { id: number; title: string; completed_on: string }[] } | null
  /** GA4 de los últimos 28 días con datos frente a los 28 anteriores. Sólo se enseña. */
  ga4?: {
    current: import("./integration").Ga4Totals
    previous: import("./integration").Ga4Totals | null
    vs_previous: import("./integration").Ga4Changes | null
    as_of: string
  } | null
  /** Disponibilidad de la web. null = quien mira no lee "web" o el cliente no tiene URLs. */
  uptime?: import("./web").ClientUptimeBlock | null
}

export type ClientCohort = "all" | "external" | "internal"

// Client Summary
export interface ClientSummary {
  client: Client
  tasks: Task[] | null
  total_tasks: number | null
  total_estimated_minutes: number | null
  total_actual_minutes: number | null
  total_tracked_minutes: number | null
}

export interface ClientTeamBreakdown {
  user_id: number
  user_name: string
  total_minutes: number
  cost_eur: number
}

export interface ClientTimeReport {
  client_id: number | null
  client_name: string
  total_minutes: number
  entries_count: number
  cost_eur: number
  team_breakdown: ClientTeamBreakdown[]
}

export interface ClientDigestSignal {
  cadence: "weekly" | "monthly"
  /** Último periodo de esa cadencia con entrega externa confirmada. */
  last_sent_period_end: string | null
  expected_period_end: string
  state: "ok" | "due" | "late"
}
