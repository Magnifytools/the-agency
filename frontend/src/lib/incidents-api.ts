import { api } from "@/lib/api"

export type IncidentState = "active" | "snoozed" | "resolved" | "dismissed"
export type IncidentSeverity = "info" | "warning" | "critical"
export type IncidentDecisionAction = "snooze" | "dismiss" | "reactivate"

export interface Incident {
  id: number
  revision: number
  condition_type: string
  state: IncidentState
  severity: IncidentSeverity
  title: string
  message: string | null
  href: string
  entity_type: string
  entity_key: string
  created_at: string
  snoozed_until: string | null
  resolved_at: string | null
  resolution_reason: string | null
  dismissal_reason: string | null
}

export interface IncidentListResponse {
  items: Incident[]
  next_cursor: number | null
}

export interface IncidentDecision {
  revision: number
  action: IncidentDecisionAction
  until?: string | null
  reason?: string | null
}

export const incidentKeys = {
  all: (userId?: number) => userId === undefined ? ["incidents"] as const : ["incidents", userId] as const,
  list: (userId: number, state: IncidentState, limit = 30) => ["incidents", userId, "list", state, limit] as const,
  count: (userId: number) => ["incidents", userId, "count"] as const,
}

export const incidentsApi = {
  list: ({ state, cursor, limit = 30 }: { state: IncidentState; cursor?: number; limit?: number }) =>
    api.get<IncidentListResponse>("/incidents", { params: { state, cursor, limit } }).then((response) => response.data),
  count: () => api.get<{ count: number }>("/incidents/count").then((response) => response.data),
  decide: (incidentId: number, decision: IncidentDecision) =>
    api.post<Incident>(`/incidents/${incidentId}/decision`, decision).then((response) => response.data),
}
