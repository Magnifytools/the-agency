import { api } from "@/lib/api"
import type { InboxNote } from "@/lib/types"

/** Qué se hace con una petición fuera de alcance. */
export type ScopeDecision = "pending" | "absorb" | "bill" | "swap"

export const SCOPE_DECISION_LABELS: Record<ScopeDecision, string> = {
  pending: "Pendiente",
  absorb: "La asumimos",
  bill: "A facturar",
  swap: "A cambio de otra cosa",
}

export const SCOPE_DECISIONS: ScopeDecision[] = ["pending", "absorb", "bill", "swap"]

export interface ScopeRequest {
  id: number
  client_id: number
  project_id: number | null
  project_name: string | null
  title: string
  detail: string | null
  estimated_minutes: number
  requested_on: string
  decision: ScopeDecision
  decision_note: string | null
  decided_at: string | null
  decided_by_name: string | null
  created_at: string
  created_by_name: string | null
}

export interface ScopeTotals {
  absorbed_minutes: number
  billable_minutes: number
  swapped_minutes: number
  pending_minutes: number
  count: number
}

export interface ScopeRequestList {
  month: string
  totals: ScopeTotals
  items: ScopeRequest[]
}

export interface ScopeRequestInput {
  title: string
  detail?: string | null
  estimated_minutes: number
  project_id?: number | null
  requested_on?: string
  decision?: ScopeDecision
  decision_note?: string | null
}

export const scopeRequestsApi = {
  list: (clientId: number, month: string) =>
    api.get<ScopeRequestList>(`/clients/${clientId}/scope-requests`, { params: { month } }).then((r) => r.data),
  create: (clientId: number, data: ScopeRequestInput) =>
    api.post<ScopeRequest>(`/clients/${clientId}/scope-requests`, data).then((r) => r.data),
  update: (clientId: number, id: number, data: Partial<ScopeRequestInput>) =>
    api.patch<ScopeRequest>(`/clients/${clientId}/scope-requests/${id}`, data).then((r) => r.data),
  delete: (clientId: number, id: number) =>
    api.delete(`/clients/${clientId}/scope-requests/${id}`).then((r) => r.data),
  fromInbox: (noteId: number, data: { client_id: number; estimated_minutes: number; title?: string; project_id?: number | null }) =>
    api.post<InboxNote>(`/inbox/${noteId}/scope-request`, data).then((r) => r.data),
}

export const scopeRequestKeys = {
  all: (clientId: number) => ["scope-requests", clientId] as const,
  month: (clientId: number, month: string) => ["scope-requests", clientId, month] as const,
}

/** 90 -> "1 h 30 min"; 45 -> "45 min"; 120 -> "2 h". */
export function formatScopeMinutes(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (!hours) return `${rest} min`
  return rest ? `${hours} h ${rest} min` : `${hours} h`
}

/** Convierte lo escrito en el campo de coste ("1,5" h o minutos) a minutos enteros. */
export function parseEstimate(value: string, unit: "min" | "h"): number | null {
  const number = Number(value.replace(",", ".").trim())
  if (!Number.isFinite(number) || number <= 0) return null
  const minutes = Math.round(unit === "h" ? number * 60 : number)
  return minutes > 0 && minutes <= 60000 ? minutes : null
}
