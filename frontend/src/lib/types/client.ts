import type { ContractType, ClientStatus } from "./common"
import type { EngineSummaryData, EngineAlert } from "./integration"
import type { Task } from "./task"

// --- Billing ---
export type BillingCycle = "monthly" | "bimonthly" | "quarterly" | "annual" | "one_time"
export type BillingEventType = "invoice_sent" | "payment_received" | "reminder_sent" | "note"

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
  cif: string | null
  vat_number: string | null
  currency: string
  monthly_fee: number | null
  ga4_property_id: string | null
  gsc_url: string | null
  billing_cycle: BillingCycle | null
  billing_day: number | null
  next_invoice_date: string | null
  last_invoiced_date: string | null
  engine_project_id: number | null
  engine_content_count: number | null
  engine_keyword_count: number | null
  engine_avg_position: number | null
  engine_clicks_30d: number | null
  engine_impressions_30d: number | null
  engine_metrics_synced_at: string | null
  engine_summary_data: EngineSummaryData | null
  engine_alerts_data: { alerts: EngineAlert[] } | null
  // Revenue intelligence
  business_model: string | null
  aov: number | null
  conversion_rate: number | null
  ltv: number | null
  seo_maturity_level: string | null
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
  cif?: string | null
  vat_number?: string | null
  currency?: string
  monthly_fee?: number | null
  ga4_property_id?: string | null
  gsc_url?: string | null
  billing_cycle?: BillingCycle | null
  billing_day?: number | null
  next_invoice_date?: string | null
  last_invoiced_date?: string | null
  engine_project_id?: number | null
  // Revenue intelligence
  business_model?: string | null
  aov?: number | null
  conversion_rate?: number | null
  ltv?: number | null
  seo_maturity_level?: string | null
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
  unit_price?: number
  unit_label?: string
  scope?: string
  budget_amount?: number
  start_date?: string
  target_end_date?: string
}

export interface ClientExtract extends Partial<ClientCreate> {
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

// Client Resources
export type ResourceType = "spreadsheet" | "document" | "email" | "account" | "dashboard" | "other"

export interface ClientResource {
  id: number
  client_id: number
  label: string
  url: string
  resource_type: ResourceType
  notes: string | null
  created_at: string
  updated_at: string
}

export interface ClientResourceCreate {
  label: string
  url: string
  resource_type?: ResourceType
  notes?: string | null
}

// Billing Events
export interface BillingEvent {
  id: number
  client_id: number
  event_type: BillingEventType
  amount: number | null
  invoice_number: string | null
  notes: string | null
  event_date: string
  created_at: string
  updated_at: string
}

export interface BillingEventCreate {
  event_type: BillingEventType
  amount?: number | null
  invoice_number?: string | null
  notes?: string | null
  event_date: string
}

export interface BillingStatus {
  billing_cycle: string | null
  billing_day: number | null
  next_invoice_date: string | null
  last_invoiced_date: string | null
  days_until_invoice: number | null
  is_overdue: boolean
  monthly_fee: number | null
  last_payment_date: string | null
  last_payment_amount: number | null
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
  profitability_status: "profitable" | "at_risk" | "unprofitable"
  tasks_by_status: Record<string, number>
  tasks_overdue: number
  tasks_due_this_week: number
  monthly_hours_breakdown: Record<string, number>
  team_breakdown: { user_id: number; full_name: string; hours: number; cost: number }[]
  actual_income: number
  monthly_profitability: Record<string, { income: number; cost: number }>
}

export interface ClientHealthScore {
  client_id: number
  client_name: string
  score: number
  factors: {
    communication: number
    tasks: number
    digests: number
    profitability: number
    followups: number
  }
  risk_level: "healthy" | "warning" | "at_risk"
}

// Client Summary
export interface ClientSummary {
  client: Client
  tasks: Task[]
  total_tasks: number
  total_estimated_minutes: number
  total_actual_minutes: number
  total_tracked_minutes: number
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
