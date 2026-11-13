// Barrel file — re-exports all types from domain-specific files.
// Existing imports like `from "@/lib/types"` continue to work unchanged.

export * from "./types/common"
export * from "./types/client"
export * from "./types/task"
export * from "./types/project"
export * from "./types/finance"
export * from "./types/integration"
export * from "./types/web"
export * from "./types/web-health"
export * from "./types/seo-control"

// --- Undo: journal de cambios ---
// Una entrada = una acción del usuario (una transacción), no una fila tocada.
// Borrar un proyecto que desvincula 8 tareas es UN "Deshacer".
export interface ChangeEntry {
  id: number
  label: string
  action: "create" | "update" | "delete"
  entity_type: string
  entity_id: number | null
  created_at: string
  operation_count: number
}

export interface UndoResult {
  id: number
  label: string
  restored: number
  // Lo que el undo NO ha tocado porque otra persona lo cambió después.
  warnings: string[]
}

export interface CommandContext {
  url?: string
  title?: string
  selection?: string
}

export interface CommandChoice {
  id: string
  label: string
  subtitle?: string | null
}

export interface CommandQuestion {
  field: string
  label: string
  kind: "choice" | "notice"
  choices: CommandChoice[]
}

export interface CommandEntity {
  type: "task" | "project" | "client" | "time_entry" | "incident"
  id: number
  label: string
  project_id?: number | null
  client_id?: number | null
  href?: string
  message?: string
  severity?: string
  recipient_name?: string
  revision?: number
}

export interface CommandReceipt {
  id: string
  request_key: string
  raw_text: string
  channel: "app" | "extension"
  context: CommandContext | null
  status: "needs_input" | "needs_review" | "executed" | "failed"
  intent: { kind?: string; [key: string]: unknown } | null
  prompt: { questions?: CommandQuestion[]; kind?: string; plan?: unknown; signature?: string } | null
  result: {
    kind?: string
    message: string
    entities: CommandEntity[]
    applied?: Record<string, string | number | null>
    applied_labels?: Record<string, string>
    query?: { kind: string; items: CommandEntity[]; total: number; page: number; page_size: number; has_more: boolean }
    undo_available: boolean
    action?: { kind: "open_project_form"; href: string }
  } | null
  change_log_id: number | null
  error: { code: string; detail?: string | null } | null
  revision: number
  created_at: string
  updated_at: string
}

export interface OperationalUsage {
  as_of: string
  window: { days: number; start: string; end: string }
  work_context: { total: number; with_project: number; without_project: number; coverage_percent: number | null }
  work_planning: { total: number; planned_or_waiting: number; unplanned: number; coverage_percent: number | null }
  incidents: { active: number; snoozed: number; dismissed: number; resolved_in_window: number }
  dailys: { updates: number; authors: number; user_days: number }
  commands: { executed: number; failed: number; needs_input: number; needs_review: number; undone: number; terminal_total: number; success_percent: number | null; by_channel: { app: number; extension: number; unknown: number } }
  deliveries: { sent: number; failed: number; uncertain: number; expired: number; cancelled: number; pending: number; sending: number; terminal_total: number; confirmation_percent: number | null }
}

/** Idea o fallo de la app enviado con "Sugerencias o fallos". */
export interface AppSuggestion {
  id: number
  text: string
  /** Pantalla desde la que se envió (ruta interna). */
  page_path: string | null
  author_id: number | null
  author_name: string | null
  created_at: string
  done_at: string | null
  done_by_name: string | null
  /** Pantallazos adjuntos (se ven en `suggestionsApi.imageUrl`). */
  images: { id: number; name: string; size_bytes: number }[]
}

// ── Bing Webmaster Tools (una cuenta por web; `api/routes/client_bing.py`) ──

export interface ClientBingConnection {
  connected: boolean
  site_url: string | null
  /** `invalid`: Bing rechazó la clave en la última llamada (motivo en `last_error`). */
  status: "ok" | "invalid" | null
  last_error: string | null
  connected_at: string | null
  connected_by_name: string | null
}

export interface BingAccountSites {
  sites: string[]
  /** El sitio de la cuenta que coincide con la web del cliente, si alguno. */
  suggested: string | null
}

export type BingUrlState = "crawled" | "redirect" | "crawl_error" | "discovered" | "unknown" | "error"

export interface BingWindow {
  start: string
  end: string
}

export interface BingUrlRow {
  url: string
  label: string | null
  state: BingUrlState
  http_status: number | null
  last_crawled_at: string | null
  discovered_at: string | null
  days_since_crawl: number | null
  /** null = Bing no trae rendimiento de esa URL en la ventana (no es un cero). */
  impressions: number | null
  clicks: number | null
  position: number | null
  error?: string
}

export interface BingCheckResult {
  site_url: string
  checked_at: string
  window: BingWindow | null
  /** URLs vigiladas activas del cliente; si pasa de `max_urls`, se miran las primeras. */
  watched_total: number
  max_urls: number
  urls: BingUrlRow[]
}

export interface BingPageQueries {
  url: string
  window: BingWindow | null
  queries: { query: string; impressions: number; clicks: number; position: number | null }[]
}
