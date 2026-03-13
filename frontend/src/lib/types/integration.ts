// --- Engine ---
export interface EngineSummaryData {
  project_id: number
  project_name: string
  domain: string
  content_count: number
  indexed_count: number
  keywords_top3: number
  keywords_top10: number
  keywords_top20: number
  clicks_30d: number
  impressions_30d: number
  clicks_previous_30d: number
  impressions_previous_30d: number
  clicks_change_pct: number
  avg_position: number | null
  trend: string
  seo_health: { score: number; trend: string } | null
  recent_changes: { severity?: string; type?: string; title: string; detail?: string; detected_at?: string }[]
}

export interface EngineAlert {
  severity: string
  type: string
  title: string
  detail: string | null
  detected_at: string
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
  estimated_close_date: string | null
  probability: number | null
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
  weighted_value: number
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

// --- Agency Vault ---

export type AssetCategory = "email" | "domain" | "hosting" | "tool"
export type HostingType = "shared" | "vps" | "dedicated" | "cloud" | "other"

export interface AgencyAsset {
  id: number
  category: AssetCategory
  name: string
  value: string | null
  provider: string | null
  url: string | null
  notes: string | null
  associated_domain: string | null
  registrar: string | null
  expiry_date: string | null
  auto_renew: boolean
  dns_provider: string | null
  hosting_type: HostingType | null
  tool_category: string | null
  monthly_cost: number | null
  // Credentials — password never returned in list responses
  username: string | null
  has_password: boolean
  is_active: boolean | null
  subscription_type: string | null
  purpose: string | null
  created_at: string
  updated_at: string
}

export interface AgencyAssetCreate {
  category: AssetCategory
  name: string
  value?: string | null
  provider?: string | null
  url?: string | null
  notes?: string | null
  associated_domain?: string | null
  registrar?: string | null
  expiry_date?: string | null
  auto_renew?: boolean
  dns_provider?: string | null
  hosting_type?: HostingType | null
  tool_category?: string | null
  monthly_cost?: number | null
  // Credentials
  username?: string | null
  password?: string | null
  is_active?: boolean | null
  subscription_type?: string | null
  purpose?: string | null
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
  time_entries_created?: number
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
  webhook_configured: boolean
  bot_token_configured: boolean
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

// --- Industry News ---

export interface IndustryNewsItem {
  id: number
  title: string
  published_date: string
  content: string | null
  url: string | null
  created_at: string
  updated_at: string
}

export interface IndustryNewsCreate {
  title: string
  published_date: string
  content?: string | null
  url?: string | null
}

// --- News URL Extraction ---

export interface NewsExtraction {
  title: string | null
  content: string | null
  published_date: string | null
}

// --- Inbox Quick Capture ---

export type InboxNoteStatus = "pending" | "classified" | "processed" | "dismissed"

export interface AISuggestion {
  suggested_project: { id: number | null; name: string; confidence: number } | null
  suggested_client: { id: number | null; name: string; confidence: number } | null
  suggested_action: "create_task" | "add_communication" | "link_to_project"
  suggested_title: string
  suggested_priority: "low" | "medium" | "high" | "urgent"
  reasoning: string
}

export interface InboxAttachment {
  id: number
  name: string
  mime_type: string
  size_bytes: number
}

export interface InboxNote {
  id: number
  user_id: number
  raw_text: string
  source: string
  status: InboxNoteStatus
  project_id: number | null
  client_id: number | null
  project_name: string | null
  client_name: string | null
  resolved_as: string | null
  resolved_entity_id: number | null
  ai_suggestion: AISuggestion | null
  link_url: string | null
  attachments: InboxAttachment[]
  created_at: string
  updated_at: string
}

export interface InboxNoteCreate {
  raw_text: string
  source?: string
  project_id?: number | null
  client_id?: number | null
  link_url?: string | null
}
