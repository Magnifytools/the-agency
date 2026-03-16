// --- Financial Types ---

export type IncomeType = "factura" | "recurrente" | "extra"
export type IncomeStatus = "pendiente" | "cobrado"
export type ExpenseStatus = "pendiente" | "pagado"
export type TaxStatusType = "pendiente" | "pagado" | "aplazado"
export type InsightSeverity = "info" | "warning" | "critical"

export interface Income {
  id: number
  date: string
  description: string
  amount: number
  type: IncomeType
  client_id: number | null
  client_name: string | null
  invoice_number: string
  vat_rate: number
  vat_amount: number
  status: IncomeStatus
  notes: string
  due_date?: string | null
  created_at: string
  updated_at: string
}

export interface IncomeCreate {
  date: string
  description: string
  amount: number
  type?: IncomeType
  client_id?: number | null
  invoice_number?: string
  vat_rate?: number
  vat_amount?: number
  status?: IncomeStatus
  notes?: string
  due_date?: string | null
}

export interface BalanceSnapshot {
  id: number
  date: string
  amount: number
  notes: string
  created_at: string
  updated_at: string
}

export interface BalanceSnapshotCreate {
  date: string
  amount: number
  notes?: string
}

export interface ExpenseCategory {
  id: number
  name: string
  description: string
  color: string
  is_active: boolean
  created_at: string
}

export interface ExpenseCategoryCreate {
  name: string
  description?: string
  color?: string
}

export interface Expense {
  id: number
  date: string
  description: string
  amount: number
  category_id: number | null
  category_name: string | null
  is_recurring: boolean
  recurrence_period: string
  vat_rate: number
  vat_amount: number
  is_deductible: boolean
  supplier: string
  notes: string
  created_at: string
  updated_at: string
}

export interface ExpenseCreate {
  date: string
  description: string
  amount: number
  category_id?: number | null
  is_recurring?: boolean
  recurrence_period?: string
  vat_rate?: number
  vat_amount?: number
  is_deductible?: boolean
  supplier?: string
  notes?: string
}

export interface Tax {
  id: number
  name: string
  model: string
  period: string
  year: number
  base_amount: number
  tax_rate: number
  tax_amount: number
  status: TaxStatusType
  due_date: string | null
  paid_date: string | null
  notes: string
  created_at: string
}

export interface TaxCreate {
  name: string
  model?: string
  period?: string
  year: number
  base_amount?: number
  tax_rate?: number
  tax_amount?: number
  status?: TaxStatusType
  due_date?: string | null
  paid_date?: string | null
  notes?: string
}

export interface TaxCalendarItem {
  model: string
  name: string
  period: string
  due_date: string
  status: string
}

export interface QuarterlyVatResult {
  period: string
  year: number
  vat_collected: number
  vat_paid: number
  vat_balance: number
  income_base: number
  expense_base: number
}

export interface Forecast {
  id: number
  month: string
  projected_income: number
  projected_expenses: number
  projected_taxes: number
  projected_profit: number
  confidence: number
  notes: string
  created_at: string
}

export interface ForecastCreate {
  month: string
  projected_income?: number
  projected_expenses?: number
  projected_taxes?: number
  projected_profit?: number
  confidence?: number
  notes?: string
}

export interface ForecastVsActual {
  month: string
  projected_income: number
  actual_income: number
  projected_expenses: number
  actual_expenses: number
  projected_profit: number
  actual_profit: number
}

export interface RunwayResponse {
  current_cash: number
  avg_monthly_burn: number
  runway_months: number | null
  runway_date: string | null
  source?: "manual" | "calculated"
  balance_date?: string | null
}

export interface FinancialInsight {
  id: number
  type: string
  title: string
  description: string
  severity: InsightSeverity
  is_read: boolean
  is_dismissed: boolean
  created_at: string
}

export interface AdvisorTask {
  id: number
  source_key: string
  title: string
  description: string
  status: "open" | "done"
  priority: "low" | "medium" | "high"
  due_date: string | null
  created_at: string
}

export interface AdvisorAiBrief {
  id: number
  period_start: string | null
  period_end: string | null
  content: string
  model: string
  provider: string
  created_at: string
}

export interface AdvisorOverview {
  total_income_month: number
  total_expenses_month: number
  net_profit_month: number
  margin_pct: number
  pending_taxes: number
  next_tax_deadline: string | null
  unread_insights: number
  open_tasks: number
  cash_runway_months: number | null
}

export interface CsvPreviewResponse {
  headers: string[]
  rows: string[][]
  total_rows: number
  detected_delimiter: string
}

export interface CsvImportRequest {
  content: string
  target: "expenses" | "income"
  mapping: Record<string, string>
  delimiter?: string
}

export interface CsvImportResponse {
  records_processed: number
  records_imported: number
  records_skipped: number
  errors: string[]
}

export interface CsvMapping {
  id: number
  name: string
  target: string
  mapping: Record<string, string>
  delimiter: string
  created_at: string
}

export interface SyncLog {
  id: number
  source: string
  file_name: string
  records_processed: number
  records_imported: number
  records_skipped: number
  errors: string
  status: string
  created_at: string
}

// --- Proposals & Service Templates ---
export type ServiceType = "seo_sprint" | "migration" | "market_study" | "consulting_retainer" | "partnership_retainer" | "brand_audit" | "custom"
export type ProposalStatus = "draft" | "sent" | "accepted" | "rejected" | "expired"

export interface PricingOption {
  name: string
  description: string
  ideal_for?: string
  price: number
  is_recurring: boolean
  recommended: boolean
}

export interface PhaseItem {
  name: string
  duration: string
  outcome: string
}

export interface ServiceTemplate {
  id: number
  service_type: ServiceType
  name: string
  description: string | null
  is_recurring: boolean
  price_range_min: number | null
  price_range_max: number | null
  default_phases: PhaseItem[] | null
  default_includes: string | null
  default_excludes: string | null
  prompt_context: string | null
  created_at: string
  updated_at: string
}

export interface Proposal {
  id: number
  title: string
  lead_id: number | null
  client_id: number | null
  created_by: number | null
  contact_name: string | null
  company_name: string
  service_type: ServiceType | null
  situation: string | null
  problem: string | null
  cost_of_inaction: string | null
  opportunity: string | null
  approach: string | null
  relevant_cases: string | null
  pricing_options: PricingOption[] | null
  internal_hours_david: number | null
  internal_hours_nacho: number | null
  internal_cost_estimate: number | null
  estimated_margin_percent: number | null
  generated_content: Record<string, unknown> | null
  status: ProposalStatus
  sent_at: string | null
  responded_at: string | null
  response_notes: string | null
  valid_until: string | null
  converted_project_id: number | null
  created_at: string
  updated_at: string
  // Denormalized
  client_name: string | null
  lead_company: string | null
  created_by_name: string | null
}

export interface ProposalCreate {
  title: string
  lead_id?: number | null
  client_id?: number | null
  contact_name?: string | null
  company_name?: string
  service_type?: ServiceType | null
  situation?: string | null
  problem?: string | null
  cost_of_inaction?: string | null
  opportunity?: string | null
  approach?: string | null
  relevant_cases?: string | null
  pricing_options?: PricingOption[] | null
  internal_hours_david?: number | null
  internal_hours_nacho?: number | null
  internal_cost_estimate?: number | null
  estimated_margin_percent?: number | null
  generated_content?: Record<string, unknown> | null
  valid_until?: string | null
}

export interface ProposalUpdate {
  title?: string
  lead_id?: number | null
  client_id?: number | null
  contact_name?: string | null
  company_name?: string
  service_type?: ServiceType | null
  situation?: string | null
  problem?: string | null
  cost_of_inaction?: string | null
  opportunity?: string | null
  approach?: string | null
  relevant_cases?: string | null
  pricing_options?: PricingOption[] | null
  internal_hours_david?: number | null
  internal_hours_nacho?: number | null
  internal_cost_estimate?: number | null
  estimated_margin_percent?: number | null
  generated_content?: Record<string, unknown> | null
  valid_until?: string | null
  status?: ProposalStatus
  response_notes?: string | null
}

export interface ProposalStatusUpdate {
  status: ProposalStatus
  response_notes?: string | null
}

// Investment Models
export interface InvestmentCalculateRequest {
  client_id?: number | null
  proposal_id?: number | null
  business_model?: string | null
  aov?: number | null
  conversion_rate?: number | null
  ltv?: number | null
  seo_maturity?: string | null
  current_monthly_traffic?: number | null
  monthly_investment?: number | null
  months?: number
}

export interface InvestmentScenario {
  label: string
  key: string
  traffic_increase: number
  new_conversions: number
  revenue_increase: number
  roi_percent: number
  payback_months: number | null
}

export interface InvestmentMonthlyRow {
  month: number
  traffic: number
  new_visitors: number
  conversions: number
  revenue: number
  cumulative_investment: number
  cumulative_revenue: number
  roi: number
}

export interface InvestmentSummary {
  break_even_month: number | null
  year1_roi_range: string
  year1_revenue_range: string
  total_investment: number
  opportunity_cost?: number | null
}

export interface NullScenario {
  label: string
  traffic_decline: number
  lost_conversions: number
  lost_revenue: number
  cumulative_opportunity_cost: number
  monthly_projection: {
    month: number
    traffic: number
    lost_visitors: number
    lost_conversions: number
    lost_revenue: number
    cumulative_opportunity_cost: number
  }[]
}

export interface PricingTierRoi {
  name: string
  price: number
  is_recommended: boolean
  roi_conservative: number
  roi_moderate: number
  roi_optimistic: number
  payback_months: number | null
}

export interface InvestmentCalculateResponse {
  scenarios: InvestmentScenario[]
  null_scenario?: NullScenario | null
  pricing_comparison?: PricingTierRoi[] | null
  monthly_projection: InvestmentMonthlyRow[]
  summary: InvestmentSummary
  assumptions: Record<string, unknown>
  inputs_used: Record<string, unknown>
}
