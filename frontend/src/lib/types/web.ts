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
