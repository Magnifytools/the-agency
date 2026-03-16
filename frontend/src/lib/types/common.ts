// --- Common / Shared types ---

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export type UserRole = "admin" | "member"
export type ContractType = "monthly" | "one_time"
export type ClientStatus = "active" | "paused" | "finished"
export type TaskStatus = "backlog" | "pending" | "in_progress" | "waiting" | "in_review" | "completed"
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
  preferences?: { shortcuts?: Record<string, string> } | null
  region?: string | null
  locality?: string | null
}

export interface UserCreate {
  email: string
  password: string
  full_name: string
  role: UserRole
  hourly_rate?: number | null
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

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

export interface CapacityMember {
  user_id: number
  full_name: string
  weekly_hours: number
  assigned_minutes: number
  task_count: number
  load_percent: number
  status: "available" | "busy" | "overloaded"
}

export interface CapacityTask {
  task_id: number
  title: string
  status: string
  priority: string
  estimated_minutes: number
  due_date: string | null
  client_id: number | null
  client_name: string | null
  project_id: number | null
  project_name: string | null
}

export interface CapacityClientGroup {
  client_id: number | null
  client_name: string
  tasks: CapacityTask[]
  total_minutes: number
}

export interface CapacityMemberDetail extends CapacityMember {
  clients: CapacityClientGroup[]
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

export interface WeeklyTimesheetTask {
  task_id: number | null
  task_title: string
  client_name: string | null
  daily_minutes: Record<string, number>
  total_minutes: number
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
    tasks: WeeklyTimesheetTask[]
  }[]
}

export interface AdminActiveTimer {
  id: number
  user_id: number
  user_name: string
  user_email: string
  task_id: number | null
  task_title: string | null
  client_name: string | null
  started_at: string
  elapsed_seconds: number
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

export interface SearchResults {
  clients: { id: number; name: string; company: string | null; status: string }[]
  projects: { id: number; name: string; client_name: string | null; status: string }[]
  tasks: { id: number; title: string; client_name: string | null; status: string }[]
  leads: { id: number; company_name: string; contact_name: string | null; status: string }[]
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

// ── Automation Rules ──────────────────────────────────────

export type AutomationTrigger = "task_completed" | "task_overdue" | "phase_completed" | "project_status_changed" | "time_entry_created" | "communication_logged" | "daily_check"
export type AutomationActionType = "create_task" | "change_task_status" | "change_project_status" | "assign_user" | "send_notification" | "send_discord" | "create_insight"

export interface AutomationRule {
  id: number
  name: string
  description: string | null
  trigger: AutomationTrigger
  conditions: Record<string, unknown>
  action_type: AutomationActionType
  action_config: Record<string, unknown>
  is_active: boolean
  run_count: number
  last_run_at: string | null
  created_by: number | null
  creator_name: string | null
  created_at: string
  updated_at: string
  recent_logs?: AutomationLogEntry[]
}

export interface AutomationLogEntry {
  id: number
  rule_id: number
  rule_name: string | null
  trigger_event: string
  trigger_data: Record<string, unknown> | null
  action_result: Record<string, unknown> | null
  success: boolean
  error_message: string | null
  executed_at: string
}

export interface AutomationRuleCreate {
  name: string
  description?: string | null
  trigger: AutomationTrigger
  conditions?: Record<string, unknown>
  action_type: AutomationActionType
  action_config?: Record<string, unknown>
  is_active?: boolean
}

export interface AutomationTriggerOption {
  key: AutomationTrigger
  label: string
  description: string
}

export interface AutomationActionOption {
  key: AutomationActionType
  label: string
  description: string
}
