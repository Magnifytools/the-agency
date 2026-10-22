// --- Webs: disponibilidad (monitor de caídas, módulo "web") ---

/** paused = la URL está pausada (no se mira). */
export type UptimeStatus = "unknown" | "up" | "suspect" | "down" | "blocked" | "paused"

export interface WebOutage {
  id: number
  target_id: number
  /** down = caída; blocked = nos bloquean (401/403/429/desafío) y no podemos comprobarla. */
  kind: "down" | "blocked"
  started_at: string
  confirmed_at: string
  ended_at: string | null
  duration_minutes: number
  cause: string | null
  cause_label: string | null
  status_code: number | null
  slack_down_status: "pending" | "sent" | "failed" | "skipped"
  slack_recovery_status: "pending" | "sent" | "failed" | "skipped" | null
}

export interface UptimeTarget {
  id: number
  client_id: number
  url: string
  label: string | null
  is_active: boolean
  status: UptimeStatus
  status_since: string | null
  last_checked_at: string | null
  last_status_code: number | null
  last_error: string | null
  last_error_label: string | null
  last_response_ms: number | null
  /** % de comprobaciones buenas (los bloqueos no cuentan). null = sin datos. */
  uptime_24h: number | null
  uptime_30d: number | null
  open_outage: WebOutage | null
  recent_outages: WebOutage[]
}

export interface ClientUptimeTargets {
  /** false = el monitor está apagado (UPTIME_ENABLED). */
  enabled: boolean
  /** false = cliente pausado, antiguo o interno: sus URLs no se miran. */
  monitored: boolean
  website: string | null
  targets: UptimeTarget[]
}

export interface UptimeOverviewRow {
  client_id: number
  client_name: string
  website: string | null
  /** Peor estado de sus URLs activas; null = sin URLs. */
  status: UptimeStatus | null
  targets: UptimeTarget[]
}

export interface UptimeOverview {
  enabled: boolean
  interval_seconds: number
  clients: UptimeOverviewRow[]
}

export interface UptimeProbeResult {
  target_id: number
  outcome: "up" | "down" | "blocked"
  cause: string | null
  cause_label: string | null
  status_code: number | null
  response_ms: number | null
  checked_at: string
}

export interface UptimeHistoryDay {
  date: string
  up: number
  down: number
  blocked: number
  uptime_pct: number | null
  avg_response_ms: number | null
}

export interface UptimeHistory {
  target: UptimeTarget
  days: UptimeHistoryDay[]
  outages: WebOutage[]
}

/** Canal de Slack del cliente. El webhook nunca vuelve del servidor. */
export interface ClientSlackSettings {
  configured: boolean
  enabled: boolean
  /** configurado + encendido + no revocado. */
  active: boolean
  revoked_at: string | null
  channel_hint: string | null
  downtime_to_slack: boolean
  user_agent: string | null
  updated_at: string | null
}

export interface ClientSlackSettingsInput {
  /** Omitido = se conserva el webhook guardado. */
  webhook_url?: string
  channel_hint: string | null
  enabled: boolean
  downtime_to_slack: boolean
  user_agent: string | null
}

/** Bloque de disponibilidad en el estado del cliente (sólo si quien mira lee "web"). */
export interface ClientUptimeBlock {
  status: UptimeStatus | null
  targets: number
  alert: "down" | "blocked" | null
  down_since: string | null
  blocked_since: string | null
  last_checked_at: string | null
}

// --- Webs: cambios (vigilancia de cambios, fase 2) ---

export type WebSeverity = "critical" | "warning" | "info"
export type WebChangeKind = "seo" | "content" | "links" | "html" | "availability"

export interface WebWatchState {
  last_checked_at: string | null
  last_changed_at: string | null
  last_status_code: number | null
  last_final_url: string | null
  last_error: string | null
  consecutive_errors: number
  needs_js_render: boolean
  /** Hay sección acotada y hoy no casa: se vigila la página entera. */
  scope_missed: boolean
  title: string | null
  word_count: number | null
}

export interface WebWatch {
  id: string
  client_id: number
  url: string
  label: string | null
  is_active: boolean
  archived_at: string | null
  watch_seo: boolean
  watch_content: boolean
  watch_links: boolean
  watch_html: boolean
  content_selector: string | null
  /** null (o lista vacía) = hereda los del cliente. */
  ignore_selectors: string[] | null
  ignore_regexes: string[] | null
  /** Se guarda pero no avisa. */
  muted: boolean
  source: string
  check_requested_at: string | null
  created_at: string | null
  updated_at: string | null
  checking: boolean
  state: WebWatchState | null
}

export interface ClientWebWatches {
  /** false = el job web_sweep está apagado: no corre nada, tampoco "Comprobar ahora". */
  enabled: boolean
  /** false = cliente no activo o interno: sus webs no se comprueban. */
  monitored: boolean
  watches: WebWatch[]
}

export interface WebWatchInput {
  url: string
  label?: string | null
  content_selector?: string | null
  watch_seo?: boolean
  watch_content?: boolean
  watch_links?: boolean
  watch_html?: boolean
}

export interface WebWatchUpdate {
  label?: string | null
  is_active?: boolean
  muted?: boolean
  watch_seo?: boolean
  watch_content?: boolean
  watch_links?: boolean
  watch_html?: boolean
  content_selector?: string | null
  ignore_selectors?: string[] | null
  ignore_regexes?: string[] | null
}

/** Recuento honesto del alta en bloque / sitemap. */
export interface WebBulkResult {
  created: number
  restored: number
  skipped_duplicates: number
  invalid: Array<{ url: string; reason: string }>
  truncated: boolean
  found_in_sitemap?: number
  sitemap_has_more?: boolean
  limit_applied?: number
}

export interface WebSweepRun {
  id: string
  client_id: number
  run_date: string
  trigger: "scheduler" | "manual"
  status: "running" | "done" | "partial" | "failed"
  started_at: string | null
  finished_at: string | null
  watches_total: number
  watches_done: number
  watches_error: number
  changes_found: number
  notified_at: string | null
  notify_status: string | null
  notify_error: string | null
}

export interface WebRunError {
  id: string
  watch_id: string | null
  url: string | null
  kind: string
  message: string
  status_code: number | null
  created_at: string | null
}

export interface WebCheckProgress {
  enabled: boolean
  is_running: boolean
  checking: string[]
  /** Pedidas y aún no recogidas por el job (con el job apagado se quedan aquí). */
  queued: string[]
  last_run: Pick<WebSweepRun, "id" | "status" | "trigger" | "watches_total" | "watches_done" | "watches_error"
    | "changes_found" | "started_at" | "finished_at"> | null
}

export interface WebCheckAccepted {
  status: "accepted"
  requested_at: string
  enabled: boolean
  watches?: number
  watch_id?: string
}

export interface WebChangeItem {
  id: string
  kind: WebChangeKind
  field: string
  severity: WebSeverity
  rule_code: string
  rule_label: string
  before_val: string | null
  after_val: string | null
  /** Forma distinta por regla: listas en enlaces/H2/schema, números en HTML_CHANGED. */
  detail: Record<string, unknown> | null
}

export interface WebChange {
  id: string
  client_id: number
  client_name: string | null
  watch_id: string
  url: string | null
  label: string | null
  run_id: string | null
  max_severity: WebSeverity
  detected_at: string
  acknowledged_at: string | null
  acknowledged_by: number | null
  acknowledged_by_label: string | null
  note: string | null
  has_diff: boolean
  items: WebChangeItem[]
}

export type WebSeverityCounts = Record<WebSeverity | "all", number>

export interface WebChangeList {
  changes: WebChange[]
  /** Por severidad, IGNORANDO los filtros de severidad y de revisado. */
  counts: WebSeverityCounts
  counts_pending: WebSeverityCounts
  total: number
  truncated: boolean
}

export interface WebChangeFilters {
  client_id?: number
  watch_id?: string
  severity?: WebSeverity
  kind?: WebChangeKind
  acknowledged?: boolean
  limit?: number
}

export interface WebChangeDetail {
  change: WebChange
  watch: { id: string; url: string; label: string | null; client_id: number; archived_at: string | null; watch_html: boolean }
}

export interface WebTextDiff {
  before: string | null
  after: string | null
}

export interface WebHtmlDiffHunk {
  before_start: number
  after_start: number
  lines: Array<{ t: "+" | "-" | " "; s: string }>
  lines_total: number
}

export interface WebHtmlDiff {
  available: boolean
  /** Siempre presente con available=false. */
  reason?: "sin_actual" | "sin_anterior" | "demasiado_grande"
  stats?: { before_lines: number; after_lines: number; added: number; removed: number }
  hunks?: WebHtmlDiffHunk[]
  hunks_total?: number
  truncated?: boolean
}

export interface WebWatchDetail {
  watch: WebWatch
  changes: WebChange[]
}

export interface WebSnapshotRow {
  id: string
  captured_at: string | null
  status_code: number | null
  byte_size: number | null
  content_hash: string | null
  html_hash: string | null
  is_pinned: boolean
  has_html: boolean
}

export interface WebWatchPreviewInput {
  content_selector?: string | null
  ignore_selectors?: string[] | null
  ignore_regexes?: string[] | null
}

export interface WebWatchPreview {
  url: string
  status_code: number
  final_url: string | null
  page_words: number
  watched_words: number
  selector: string | null
  selector_matches: boolean
  section_nodes: number
  ignored: Array<{ selector: string; valid: boolean; nodes: number; words: number }>
  sample: string
}

export interface WebChangeSettingsValues {
  default_content_selector: string | null
  default_ignore_selectors: string[] | null
  default_ignore_regexes: string[] | null
  max_concurrency: number | null
  request_timeout_s: number | null
  crawl_delay_ms: number | null
  digest_min_severity: WebSeverity | null
  sweep_weekdays: number[] | null
  sweep_skip_dates: string[] | null
  sweep_summary_to_slack: boolean | null
}

export interface WebChangeSettings {
  enabled: boolean
  sweep_local_time: string
  /** Lo guardado: null = el default del código. */
  stored: WebChangeSettingsValues
  /** Lo que de verdad se usa. */
  effective: WebChangeSettingsValues & { sweep_weekdays: number[]; sweep_skip_dates: string[]; digest_min_severity: WebSeverity }
  code_defaults: {
    default_ignore_selectors: string[]
    default_ignore_regexes: string[]
    max_concurrency: number
    request_timeout_s: number
    crawl_delay_ms: number
    digest_min_severity: WebSeverity
    sweep_weekdays: number[]
    sweep_summary_to_slack: boolean
  }
  /** Se lee de la configuración, nunca del último barrido. */
  slack: "ready" | "disabled" | "revoked"
  updated_at: string | null
}

export interface WebCaptureSettingsInput {
  default_content_selector: string | null
  default_ignore_selectors: string[] | null
  default_ignore_regexes: string[] | null
  max_concurrency: number | null
  request_timeout_s: number | null
  crawl_delay_ms: number | null
  digest_min_severity: WebSeverity | null
}

export interface WebCalendarSettingsInput {
  sweep_weekdays: number[]
  sweep_skip_dates: string[]
  sweep_summary_to_slack: boolean
}
