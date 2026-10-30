import { api } from "@/lib/api"
import type { DigestStatus, DigestTone } from "@/lib/types"

export type ReportCadence = "weekly" | "monthly"
export type ReportScope = "mine" | "team"
export interface ReportPolicy {
  client_id: number
  configured: boolean
  /** Alguna de las dos cadencias encendida. */
  enabled: boolean
  weekly_enabled: boolean
  monthly_enabled: boolean
  responsible_user_id: number | null
  responsible_name: string | null
  responsible_active: boolean | null
  responsible_can_prepare: boolean | null
  revision: number | null
  updated_at: string | null
}
export interface ReportPolicyUpdate {
  weekly_enabled: boolean
  monthly_enabled: boolean
  responsible_user_id: number | null
  revision: number
}
export interface ExternalDeliverySummary {
  digest_id: number | null
  state: "confirmed" | "unconfirmed"
  actor_name: string | null
  confirmed_at: string | null
}
export type ExternalDeliveryAction = "confirmed" | "revoked"
export interface ExternalDeliveryEvent {
  id: number
  digest_id: number
  action: ExternalDeliveryAction
  actor_id: number
  actor_name: string
  created_at: string
}
export interface ExternalDeliveryHistory {
  can_record: boolean
  events: ExternalDeliveryEvent[]
  external_delivery: ExternalDeliverySummary
  has_newer_version: boolean
}
export interface ExternalDeliveryResult {
  event: ExternalDeliveryEvent
  external_delivery: ExternalDeliverySummary
  has_newer_version: boolean
}
export type GenerationReason = "client_inactive" | "internal_client" | "policy_missing" | "policy_disabled" | "responsible_unavailable" | "local_report" | "already_exists" | "eligible"
export interface GenerationPreviewItem {
  client_id: number
  client_name: string
  policy_revision: number | null
  cadence: ReportCadence | null
  responsible_user_id: number | null
  responsible_name: string | null
  period_start: string | null
  period_end: string | null
  eligible: boolean
  reason: GenerationReason
  latest_digest_id: number | null
  version_count: number
  state: string
  digest: { latest_digest_id: number | null; latest_status: DigestStatus | null; version_count: number }
  internal_distribution: { digest_id: number | null; state: string | null; delivery_id: string | null; sent_at: string | null }
  external_delivery: ExternalDeliverySummary
  // Sólo en la fila mensual de un cliente con informe SEO local: ese informe hace de mensual.
  local_report?: { report_id: number | null; delivered_at: string | null; delivered_by_name: string | null } | null
}
export interface GenerationPreview {
  as_of: string
  scope: ReportScope
  items: GenerationPreviewItem[]
  counts: { eligible: number; excluded: number }
}
export interface CohortGenerateItem {
  generation_key: string
  client_id: number
  policy_revision: number
  period_start: string
  period_end: string
}
export interface CohortGenerateResult {
  client_id: number
  period_start?: string | null
  period_end?: string | null
  outcome: "generated" | "skipped" | "failed"
  digest_id?: number | null
  reason?: GenerationReason | "policy_changed" | "permission_changed" | "period_changed" | "concurrent_generation" | "generation_failed" | null
}

export const CADENCE_LABEL: Record<ReportCadence, string> = {
  monthly: "Informe mensual",
  weekly: "Seguimiento semanal",
}
/** Una fila de la cohorte es un cliente y un periodo (puede tener las dos cadencias). */
export const previewItemKey = (item: { client_id: number; period_start?: string | null; period_end?: string | null }) =>
  `${item.client_id}:${item.period_start ?? ""}:${item.period_end ?? ""}`

// Prefix keys shared by the policy editor, generation preview and version actions.
export const reportPolicyKeys = {
  all: ["report-policy"] as const,
  preview: ["digest-generation-preview"] as const,
  external: ["digest-external-delivery"] as const,
}
export const reportPolicyApi = {
  getPolicy: (clientId: number) => api.get<ReportPolicy>(`/digests/policies/${clientId}`).then(r => r.data),
  updatePolicy: (clientId: number, body: ReportPolicyUpdate) => api.put<ReportPolicy>(`/digests/policies/${clientId}`, body).then(r => r.data),
  responsibles: () => api.get<{ id: number; full_name: string }[]>("/digests/policy-responsibles").then(r => r.data),
  generationPreview: (scope: ReportScope) => api.get<GenerationPreview>("/digests/generation-preview", { params: { scope } }).then(r => r.data),
  generateCohort: (body: { items: CohortGenerateItem[]; tone: DigestTone }) => api.post<{ results: CohortGenerateResult[] }>("/digests/generate-cohort", body, { timeout: 300_000 }).then(r => r.data),
  externalEvents: (digestId: number) => api.get<ExternalDeliveryHistory>(`/digests/${digestId}/external-delivery-events`).then(r => r.data),
  recordExternalEvent: (digestId: number, action: ExternalDeliveryAction, requestKey: string) =>
    api.post<ExternalDeliveryResult>(`/digests/${digestId}/external-delivery-events`, { action }, { headers: { "X-Agency-Request-Key": requestKey } }).then(r => r.data),
}
