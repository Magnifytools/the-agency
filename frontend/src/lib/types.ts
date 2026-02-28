export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export type UserRole = "admin" | "member"
export type ContractType = "monthly" | "one_time"
export type ClientStatus = "active" | "paused" | "finished"
export type TaskStatus = "pending" | "in_progress" | "completed"
export type TaskPriority = "urgent" | "high" | "medium" | "low"
export type ProjectStatus = "planning" | "active" | "on_hold" | "completed" | "cancelled"
export type PhaseStatus = "pending" | "in_progress" | "completed"

export interface UserPermission {
  module: string
  can_read: boolean
  can_write: boolean
}

export interface User {
  id: number
  email: string
  full_name: string
  role: UserRole
  hourly_rate: number | null
  is_active: boolean
  permissions: UserPermission[]
}

export interface UserCreate {
  email: string
  password: string
  full_name: string
  role: UserRole
  hourly_rate?: number | null
}

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
  created_at: string
  updated_at: string
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
  currency?: string
  monthly_fee?: number | null
  ga4_property_id?: string | null
  gsc_url?: string | null
  billing_cycle?: BillingCycle | null
  billing_day?: number | null
  next_invoice_date?: string | null
  last_invoiced_date?: string | null
  engine_project_id?: number | null
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

export interface ActivityEvent {
  id: string
  type: string
  subtype: string
  timestamp: string
  title: string
  description: string | null
  detail: string | null
  user_name: string | null
  contact_name?: string | null
  icon: string
}

export interface NotificationItem {
  id: number
  user_id: number
  type: string
  title: string
  message: string | null
  is_read: boolean
  link_url: string | null
  entity_type: string | null
  entity_id: number | null
  created_at: string
}

export interface CapacityMember {
  user_id: number
  full_name: string
  weekly_hours: number
  assigned_minutes: number
  task_count: number
  load_percent: number
  status: "available" | "busy" | "overloaded"
}

export interface TaskCategory {
  id: number
  name: string
  default_minutes: number
  created_at: string
  updated_at: string
}

export interface Task {
  id: number
  title: string
  description: string | null
  status: TaskStatus
  priority: TaskPriority
  estimated_minutes: number | null
  actual_minutes: number | null
  start_date: string | null
  due_date: string | null
  client_id: number
  category_id: number | null
  assigned_to: number | null
  project_id: number | null
  phase_id: number | null
  depends_on: number | null
  created_at: string
  updated_at: string
  client_name: string | null
  category_name: string | null
  assigned_user_name: string | null
  project_name: string | null
  phase_name: string | null
}

export interface TaskCreate {
  title: string
  description?: string | null
  status?: TaskStatus
  priority?: TaskPriority
  estimated_minutes?: number | null
  actual_minutes?: number | null
  start_date?: string | null
  due_date?: string | null
  client_id: number
  category_id?: number | null
  assigned_to?: number | null
  project_id?: number | null
  phase_id?: number | null
  depends_on?: number | null
  is_inbox?: boolean
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

// Time Entries
export interface TimeEntry {
  id: number
  minutes: number | null
  started_at: string | null
  date: string
  notes: string | null
  task_id: number | null
  user_id: number
  created_at: string
  updated_at: string
  task_title: string | null
  client_name: string | null
}

export interface TimeEntryCreate {
  minutes: number
  task_id: number | null
  notes?: string | null
  date?: string | null
}

export interface ActiveTimer {
  id: number
  task_id: number | null
  task_title: string | null
  client_name: string | null
  started_at: string
}

// Dashboard
export interface DashboardOverview {
  active_clients: number
  pending_tasks: number
  in_progress_tasks: number
  hours_this_month: number
  total_budget: number
  total_cost: number
  margin: number
  margin_percent: number
}

export interface ClientProfitability {
  client_id: number
  client_name: string
  budget: number
  cost: number
  margin: number
  margin_percent: number
  estimated_minutes: number
  actual_minutes: number
  variance_minutes: number
  status: "profitable" | "at_risk" | "unprofitable"
}

export interface ProfitabilityResponse {
  clients: ClientProfitability[]
}

export interface TeamMemberSummary {
  user_id: number
  full_name: string
  hourly_rate: number | null
  hours_this_month: number
  cost: number
  task_count: number
  clients_touched: number
}

export interface MonthlyClose {
  year: number
  month: number
  reviewed_numbers: boolean
  reviewed_margin: boolean
  reviewed_cash_buffer: boolean
  reviewed_reinvestment: boolean
  reviewed_debt: boolean
  reviewed_taxes: boolean
  reviewed_personal: boolean
  responsible_name: string
  notes: string
  updated_at?: string | null
}

export interface FinancialSettings {
  tax_reserve: number
  credit_limit: number
  credit_used: number
  credit_utilization: number
  monthly_close_day: number
  credit_alert_pct: number
  tax_reserve_target_pct: number
  default_vat_rate: number
  corporate_tax_rate: number
  irpf_retention_rate: number
  cash_start: number
  advisor_expense_alert_pct: number
  advisor_margin_warning_pct: number
  ai_provider: string
  ai_model: string
  ai_api_url: string
}

export interface WeeklyTimesheet {
  week_start: string
  week_end: string
  days: string[]
  users: {
    user_id: number
    full_name: string
    daily_minutes: Record<string, number>
    total_minutes: number
  }[]
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

// Projects
export interface ProjectPhase {
  id: number
  name: string
  description: string | null
  order_index: number
  start_date: string | null
  due_date: string | null
  completed_at: string | null
  status: PhaseStatus
  project_id: number
  created_at: string
  updated_at: string
}

export interface Project {
  id: number
  name: string
  description: string | null
  project_type: string | null
  start_date: string | null
  target_end_date: string | null
  actual_end_date: string | null
  status: ProjectStatus
  progress_percent: number
  budget_hours: number | null
  budget_amount: number | null
  gsc_url: string | null
  ga4_property_id: string | null
  is_recurring: boolean
  client_id: number
  client_name: string | null
  phases: ProjectPhase[]
  task_count: number
  completed_task_count: number
  created_at: string
  updated_at: string
}

export interface ProjectListItem {
  id: number
  name: string
  project_type: string | null
  start_date: string | null
  target_end_date: string | null
  status: ProjectStatus
  progress_percent: number
  client_id: number
  client_name: string | null
  gsc_url: string | null
  ga4_property_id: string | null
  is_recurring: boolean
  phase_count: number
  task_count: number
  completed_task_count: number
}

export interface ProjectCreate {
  name: string
  description?: string | null
  project_type?: string | null
  start_date?: string | null
  target_end_date?: string | null
  budget_hours?: number | null
  budget_amount?: number | null
  gsc_url?: string | null
  ga4_property_id?: string | null
  is_recurring?: boolean
  client_id: number
}

export interface ProjectTemplate {
  name: string
  phase_count: number
  task_count: number
}

// Communications
export type CommunicationChannel = "email" | "call" | "meeting" | "whatsapp" | "slack" | "other"
export type CommunicationDirection = "inbound" | "outbound"

export interface Communication {
  id: number
  channel: CommunicationChannel
  direction: CommunicationDirection
  subject: string | null
  summary: string
  contact_name: string | null
  occurred_at: string
  requires_followup: boolean
  followup_date: string | null
  followup_notes: string | null
  client_id: number
  user_id: number
  user_name: string | null
  created_at: string
  updated_at: string
}

export interface CommunicationCreate {
  channel: CommunicationChannel
  direction: CommunicationDirection
  subject?: string | null
  summary: string
  contact_name?: string | null
  occurred_at: string
  requires_followup?: boolean
  followup_date?: string | null
  followup_notes?: string | null
}

// AI Email Draft
export interface EmailDraftRequest {
  client_id: number
  purpose: string
  contact_name?: string | null
  reply_to_id?: number | null
  project_context?: string | null
}

export interface EmailDraftResponse {
  subject: string
  body: string
  tone: string
  suggested_followup: string | null
}

// PM Insights
export type InsightType = "deadline" | "stalled" | "overdue" | "followup" | "workload" | "suggestion" | "quality"
export type InsightPriority = "high" | "medium" | "low"
export type InsightStatus = "active" | "dismissed" | "acted"

export interface Insight {
  id: number
  insight_type: InsightType
  priority: InsightPriority
  title: string
  description: string
  suggested_action: string | null
  status: InsightStatus
  dismissed_at: string | null
  acted_at: string | null
  generated_at: string
  expires_at: string | null
  user_id: number | null
  client_id: number | null
  project_id: number | null
  task_id: number | null
  client_name: string | null
  project_name: string | null
  task_title: string | null
  created_at: string
  updated_at: string
}

export interface InsightCount {
  total: number
  high: number
  medium: number
  low: number
}

export interface DailyBriefing {
  date: string
  greeting: string
  priorities: { id: number; title: string; client: string | null; due: string | null }[]
  alerts: { id: number; title: string; client: string | null; days_overdue: number }[]
  followups: { client: string | null; subject: string; followup_date: string | null }[]
  suggestion: string | null
}

// Alert Settings
export interface AlertSettings {
  id: number
  user_id: number
  days_without_activity: number
  days_before_deadline: number
  days_without_contact: number
  max_tasks_per_week: number
  notify_in_app: boolean
  notify_email: boolean
}

export interface AlertSettingsUpdate {
  days_without_activity?: number
  days_before_deadline?: number
  days_without_contact?: number
  max_tasks_per_week?: number
  notify_in_app?: boolean
  notify_email?: boolean
}

// Proposals & Service Templates
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

// Reports
export type ReportType = "client_status" | "weekly_summary" | "project_status"
export type ReportPeriod = "week" | "month"

export interface ReportRequest {
  type: ReportType
  client_id?: number | null
  project_id?: number | null
  period?: ReportPeriod
}

export interface ReportSection {
  title: string
  content: string
}

export interface Report {
  id: number
  type: string
  title: string
  generated_at: string
  period_start: string | null
  period_end: string | null
  client_name: string | null
  project_name: string | null
  sections: ReportSection[]
  summary: string
}

export interface ReportNarrative {
  narrative: string
  executive_summary: string
}

// Growth Operations
export type GrowthFunnelStage = "referral" | "desire" | "activate" | "revenue" | "retention" | "other"
export type GrowthStatus = "idea" | "in_progress" | "completed" | "discarded"

export interface GrowthIdea {
  id: number
  title: string
  description: string | null
  funnel_stage: GrowthFunnelStage
  target_kpi: string | null
  status: GrowthStatus
  impact: number
  confidence: number
  ease: number
  ice_score: number
  experiment_start_date: string | null
  experiment_end_date: string | null
  results_notes: string | null
  is_successful: boolean | null
  project_id: number | null
  task_id: number | null
  project_name: string | null
  task_title: string | null
  created_at: string
  updated_at: string
}

export interface GrowthIdeaCreate {
  title: string
  description?: string | null
  funnel_stage?: GrowthFunnelStage
  target_kpi?: string | null
  status?: GrowthStatus
  impact?: number
  confidence?: number
  ease?: number
  experiment_start_date?: string | null
  experiment_end_date?: string | null
  results_notes?: string | null
  is_successful?: boolean | null
  project_id?: number | null
  task_id?: number | null
}

// Invitations
export interface Invitation {
  id: number
  email: string
  role: UserRole
  invited_by: number
  inviter_name: string | null
  expires_at: string
  accepted_at: string | null
  created_at: string
}

export interface InvitationCreateResult extends Invitation {
  token: string
}

export interface InvitationCreate {
  email: string
  role?: UserRole
  modules?: string[]
}

export interface GrowthIdeaUpdate {
  title?: string
  description?: string | null
  funnel_stage?: GrowthFunnelStage
  target_kpi?: string | null
  status?: GrowthStatus
  impact?: number
  confidence?: number
  ease?: number
  experiment_start_date?: string | null
  experiment_end_date?: string | null
  results_notes?: string | null
  is_successful?: boolean | null
  project_id?: number | null
  task_id?: number | null
}

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
  runway_months: number
  runway_date: string | null
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

// --- Weekly Digests ---

export type DigestStatus = "draft" | "reviewed" | "sent"
export type DigestTone = "formal" | "cercano" | "equipo"

export interface DigestItem {
  title: string
  description: string
}

export interface DigestSections {
  done: DigestItem[]
  need: DigestItem[]
  next: DigestItem[]
}

export interface DigestContent {
  greeting: string
  date: string
  sections: DigestSections
  closing: string
}

export interface Digest {
  id: number
  client_id: number
  client_name: string | null
  period_start: string
  period_end: string
  status: DigestStatus
  tone: DigestTone
  content: DigestContent | null
  raw_context: Record<string, unknown> | null
  generated_at: string | null
  edited_at: string | null
  created_by: number
  creator_name: string | null
  created_at: string
  updated_at: string
}

export interface DigestGenerateRequest {
  client_id: number
  period_start?: string | null
  period_end?: string | null
  tone?: DigestTone
}

export interface DigestUpdateRequest {
  content?: DigestContent | null
  tone?: DigestTone | null
}

export interface DigestRenderResponse {
  format: "slack" | "email" | "discord"
  rendered: string
}

// --- CRM Leads ---

export type LeadStatus = "new" | "contacted" | "discovery" | "proposal" | "negotiation" | "won" | "lost"
export type LeadSource = "website" | "referral" | "linkedin" | "conference" | "cold_outreach" | "other"
export type LeadActivityType = "note" | "email_sent" | "email_received" | "call" | "meeting" | "proposal_sent" | "status_change" | "followup_set"

export interface Lead {
  id: number
  company_name: string
  contact_name: string | null
  email: string | null
  phone: string | null
  website: string | null
  linkedin_url: string | null
  status: LeadStatus
  source: LeadSource
  assigned_to: number | null
  assigned_user_name: string | null
  estimated_value: number | null
  service_interest: string | null
  currency: string
  notes: string | null
  industry: string | null
  company_size: string | null
  current_website_traffic: string | null
  next_followup_date: string | null
  next_followup_notes: string | null
  last_contacted_at: string | null
  converted_client_id: number | null
  converted_at: string | null
  lost_reason: string | null
  created_at: string
  updated_at: string
}

export interface LeadCreate {
  company_name: string
  contact_name?: string | null
  email?: string | null
  phone?: string | null
  website?: string | null
  linkedin_url?: string | null
  status?: LeadStatus
  source?: LeadSource
  assigned_to?: number | null
  estimated_value?: number | null
  service_interest?: string | null
  currency?: string
  notes?: string | null
  industry?: string | null
  company_size?: string | null
  current_website_traffic?: string | null
  next_followup_date?: string | null
  next_followup_notes?: string | null
}

export interface LeadActivity {
  id: number
  lead_id: number
  user_id: number
  user_name: string | null
  activity_type: LeadActivityType
  title: string
  description: string | null
  created_at: string
}

export interface LeadDetail extends Lead {
  activities: LeadActivity[]
}

export interface PipelineStageSummary {
  status: LeadStatus
  count: number
  total_value: number
}

export interface PipelineSummary {
  stages: PipelineStageSummary[]
  total_leads: number
  total_value: number
}

export interface LeadReminder {
  id: number
  company_name: string
  contact_name: string | null
  next_followup_date: string | null
  next_followup_notes: string | null
  status: LeadStatus
  assigned_user_name: string | null
  days_until_followup: number
}

// --- Holded Integration ---

export interface HoldedSyncLog {
  id: number
  sync_type: string
  status: string
  records_synced: number
  error_message: string | null
  started_at: string
  completed_at: string | null
}

export interface HoldedSyncStatus {
  contacts: HoldedSyncLog | null
  invoices: HoldedSyncLog | null
  expenses: HoldedSyncLog | null
}

export interface HoldedSyncResult {
  sync_type: string
  status: string
  records_synced: number
  error_message: string | null
}

export interface HoldedInvoice {
  id: number
  holded_id: string
  client_id: number | null
  contact_name: string | null
  invoice_number: string | null
  date: string | null
  due_date: string | null
  total: number
  subtotal: number
  tax: number
  status: string | null
  currency: string
  synced_at: string | null
}

export interface HoldedExpense {
  id: number
  holded_id: string
  description: string | null
  date: string | null
  total: number
  subtotal: number
  tax: number
  category: string | null
  supplier: string | null
  status: string | null
  synced_at: string | null
}

export interface HoldedMonthlyFinancials {
  month: string
  income: number
  expenses: number
  profit: number
}

export interface HoldedDashboard {
  income_this_month: number
  expenses_this_month: number
  profit_this_month: number
  income_ytd: number
  expenses_ytd: number
  profit_ytd: number
  pending_invoices: HoldedInvoice[]
  monthly_data: HoldedMonthlyFinancials[]
}

export interface HoldedConfig {
  api_key_configured: boolean
  last_sync_contacts: HoldedSyncLog | null
  last_sync_invoices: HoldedSyncLog | null
  last_sync_expenses: HoldedSyncLog | null
}

export interface HoldedTestConnection {
  success: boolean
  message: string
}

// --- Daily Updates ---

export type DailyUpdateStatus = "draft" | "sent"

export interface ParsedTask {
  description: string
  details: string
}

export interface ParsedProject {
  name: string
  client: string
  tasks: ParsedTask[]
}

export interface ParsedDailyData {
  projects: ParsedProject[]
  general: ParsedTask[]
  tomorrow: string[]
}

export interface DailyUpdate {
  id: number
  user_id: number
  user_name: string | null
  date: string
  raw_text: string
  parsed_data: ParsedDailyData | null
  status: DailyUpdateStatus
  discord_sent_at: string | null
  created_at: string
  updated_at: string
}

export interface DailySubmitRequest {
  raw_text: string
  date?: string | null
}

export interface DailyDiscordResponse {
  success: boolean
  message: string
}

// --- Discord Integration ---

export interface DiscordSettings {
  id: number
  webhook_url: string | null
  webhook_configured: boolean
  auto_daily_summary: boolean
  summary_time: string
  include_ai_note: boolean
  last_sent_at: string | null
}

export interface DiscordTestResponse {
  success: boolean
  message: string
}

export interface DiscordSendResponse {
  success: boolean
  message: string
  date?: string
}
