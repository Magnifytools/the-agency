// --- Webs: salud diaria (dominio, certificado, robots.txt y sitemap) ---
// Lo escribe el job `web_health` (backend/services/web/health.py).
export type WebExpiryLevel = "ok" | "warning" | "critical"

export interface WebHostExpiry {
  host: string
  checked_at: string
  cert: {
    status: "ok" | "invalid" | "error" | "no_https"
    expires_at: string | null
    days_left: number | null
    level: WebExpiryLevel | null
    issuer: string | null
    error: string | null
  }
  domain: {
    status: "ok" | "no_date" | "unsupported" | "not_found" | "error"
    name: string | null
    expires_at: string | null
    days_left: number | null
    level: WebExpiryLevel | null
    error: string | null
  }
}

export interface WebRobotsInfo {
  origin: string
  checked_at: string
  status: "ok" | "missing" | "error"
  error: string | null
  body: string | null
  blocks_all: boolean
  previous_body: string | null
  changed_at: string | null
  reviewed_at: string | null
  reviewed_by: string | null
  pending_review: boolean
  sitemap: {
    url: string | null
    source: "declared" | "default" | null
    status: "ok" | "empty" | "invalid" | "error" | null
    url_count: number | null
    has_more: boolean | null
    error: string | null
  }
}

export interface ClientWebHealth {
  expiry_enabled: boolean
  robots_enabled: boolean
  changes_enabled: boolean
  thresholds: {
    cert_warning_days: number
    cert_critical_days: number
    domain_warning_days: number
    domain_critical_days: number
  }
  hosts: WebHostExpiry[]
  robots: WebRobotsInfo[]
}

// --- Revisión tras publicar (enlace de una tarea completada, job `publish_checks`) ---
export interface PublishCheckItem {
  code: "http" | "indexable" | "canonical" | "title" | "meta_description"
  label: string
  ok: boolean
  detail: string
}

export interface TaskPublishCheck {
  enabled: boolean
  url: string | null
  status: "none" | "disabled" | "waiting" | "pending" | "ok" | "problems" | "unreachable" | "skipped"
  checked_at?: string | null
  attempts?: number
  next_attempt_at?: string | null
  http_status?: number | null
  final_url?: string | null
  error?: string | null
  results?: PublishCheckItem[]
}
