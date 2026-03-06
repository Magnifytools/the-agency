import type { ProjectStatus, PhaseStatus } from "./common"

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
  hours_used: number | null
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

export interface ProjectDraft {
  name: string
  description?: string
  project_type?: string
  is_recurring?: boolean
  budget_amount?: number
  start_date?: string
  target_end_date?: string
  client_name?: string
}

export interface ProjectTeamBreakdown {
  user_id: number
  user_name: string
  total_minutes: number
  entries_count: number
}

export interface ProjectTimeReport {
  project_id: number
  project_name: string
  client_id: number
  client_name: string
  total_minutes: number
  entries_count: number
  team_breakdown: ProjectTeamBreakdown[]
}

// Project Evidence
export type EvidenceType = "screenshot" | "report" | "analytics" | "ranking" | "content" | "deliverable" | "other"

export interface ProjectEvidence {
  id: number
  project_id: number
  phase_id: number | null
  title: string
  url: string
  evidence_type: EvidenceType
  description: string | null
  created_by: number | null
  creator_name: string | null
  phase_name: string | null
  created_at: string
  updated_at: string
}

export interface ProjectEvidenceCreate {
  title: string
  url: string
  evidence_type?: EvidenceType
  phase_id?: number | null
  description?: string | null
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

// Reports
export type ReportType = "client_status" | "weekly_summary" | "project_status" | "client_monthly"
export type ReportPeriod = "week" | "month"
export type ReportAudience = "executive" | "marketing" | "operational"

export interface ReportRequest {
  type: ReportType
  client_id?: number | null
  project_id?: number | null
  period?: ReportPeriod
  audience?: ReportAudience | null
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
  audience: string | null
}

export interface ReportSCQASection {
  key: string
  title: string
  content: string
}

export interface ReportNarrative {
  narrative: string
  executive_summary: string
  scqa_sections?: ReportSCQASection[]
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
