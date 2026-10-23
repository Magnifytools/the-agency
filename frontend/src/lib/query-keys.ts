import type { QueryClient, QueryKey } from "@tanstack/react-query"
import { incidentKeys } from "@/lib/incidents-api"

export const taskKeys = {
  all: () => ["tasks"] as const,
  list: (filters: readonly unknown[]) => ["tasks", "list", ...filters] as const,
  agenda: (section: string, date: string, userId: number | undefined, timezoneOffset: number, scope: "mine" | "team" = "mine") =>
    ["tasks", "agenda", section, date, userId, timezoneOffset, scope] as const,
  recurring: () => ["tasks", "recurring"] as const,
  project: (projectId: number) => ["tasks", "project", projectId] as const,
  assigned: (scope: string, ...filters: readonly unknown[]) => ["tasks", "assigned", scope, ...filters] as const,
  detail: (taskId: number) => ["tasks", "detail", taskId] as const,
}

export const projectKeys = {
  all: () => ["projects"] as const,
  list: (filters: readonly unknown[] = []) => ["projects", "list", ...filters] as const,
  detail: (projectId: number) => ["projects", "detail", projectId] as const,
  client: (clientId: number) => ["projects", "client", clientId] as const,
  burndown: (projectId: number) => ["projects", "burndown", projectId] as const,
}

export const dashboardKeys = {
  all: () => ["dashboard"] as const,
  overview: (year: number, month: number, userId?: number, permissionSignature = "") => ["dashboard", "overview", userId ?? "anonymous", permissionSignature, year, month] as const,
  operations: (userId?: number, permissionSignature = "") => ["dashboard", "operations", userId ?? "anonymous", permissionSignature] as const,
  financialOverview: (year: number, month: number, userId?: number, permissionSignature = "") => ["dashboard", "financial-overview", userId ?? "anonymous", permissionSignature, year, month] as const,
  profitability: (year: number, month: number, userId?: number, permissionSignature = "") => ["dashboard", "profitability", userId ?? "anonymous", permissionSignature, year, month] as const,
  team: (year: number, month: number, userId?: number, permissionSignature = "") => ["dashboard", "team", userId ?? "anonymous", permissionSignature, year, month] as const,
  discordPreview: (userId?: number, permissionSignature = "") => ["dashboard", "discord-preview", userId ?? "anonymous", permissionSignature] as const,
  utilization: (year: number, month: number, userId?: number, permissionSignature = "") => ["dashboard", "utilization", userId ?? "anonymous", permissionSignature, year, month] as const,
  monthlyClose: (year: number, month: number, userId?: number, permissionSignature = "") => ["dashboard", "monthly-close", userId ?? "anonymous", permissionSignature, year, month] as const,
  financialSettings: (userId?: number, permissionSignature = "") => ["dashboard", "financial-settings", userId ?? "anonymous", permissionSignature] as const,
  today: () => ["dashboard", "today"] as const,
}

export const briefingKeys = {
  all: () => ["daily-briefing"] as const,
}

export const timeKeys = {
  all: () => ["time-entries"] as const,
  task: (taskId: number) => ["time-entries", "task", taskId] as const,
  today: (userId: number | undefined, date: string) => ["time-entries", "today", userId, date] as const,
  client: (clientId: number) => ["time-entries", "client", clientId] as const,
  week: (weekStart?: string) => ["time-entries", "week", weekStart ?? "current"] as const,
  reports: () => ["time-entries", "reports"] as const,
}

// Webs: vigilancia de cambios. Todo cuelga de ["web-changes"] para poder
// invalidar por familias: revisar toca listas y fichas, no los diffs (caros e
// inmutables: el antes y el después de un cambio no cambian).
export const webKeys = {
  all: () => ["web-changes"] as const,
  changeLists: () => ["web-changes", "list"] as const,
  changes: (filters: object) => ["web-changes", "list", filters] as const,
  change: (changeId: string) => ["web-changes", "change", changeId] as const,
  diff: (changeId: string) => ["web-changes", "diff", changeId] as const,
  htmlDiff: (changeId: string) => ["web-changes", "html-diff", changeId] as const,
  watchLists: () => ["web-changes", "watches"] as const,
  watches: (clientId: number, includeArchived = false) => ["web-changes", "watches", clientId, includeArchived] as const,
  watchDetails: () => ["web-changes", "watch"] as const,
  watch: (watchId: string) => ["web-changes", "watch", watchId] as const,
  watchHistory: (watchId: string) => ["web-changes", "watch-history", watchId] as const,
  progress: (clientId: number) => ["web-changes", "progress", clientId] as const,
  runs: (clientId: number) => ["web-changes", "runs", clientId] as const,
  runErrors: (runId: string) => ["web-changes", "run-errors", runId] as const,
  settings: (clientId: number) => ["web-changes", "settings", clientId] as const,
}

/** Tras revisar: listas, fichas de cambio y fichas de URL. Los diffs no. */
export function invalidateWebReview(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: webKeys.changeLists() }),
    queryClient.invalidateQueries({ queryKey: ["web-changes", "change"] }),
    queryClient.invalidateQueries({ queryKey: webKeys.watchDetails() }),
  ])
}

/** Tras un barrido o un cambio en las URLs: todo lo de webs menos los diffs. */
export function invalidateWebWatches(queryClient: QueryClient) {
  return queryClient.invalidateQueries({
    predicate: (query) => query.queryKey[0] === "web-changes"
      && query.queryKey[1] !== "diff" && query.queryKey[1] !== "html-diff",
  })
}

export type OperationalImpact = {
  projectId?: number | null
  previousProjectId?: number | null
  projectIds?: Array<number | null | undefined>
  clientId?: number | null
  previousClientId?: number | null
  clientIds?: Array<number | null | undefined>
}

function uniqueIds(...values: Array<number | null | undefined>) {
  return [...new Set(values.filter((value): value is number => value != null))]
}

export async function invalidateTaskChange(
  queryClient: QueryClient,
  affected: OperationalImpact = {},
) {
  const clientIds = uniqueIds(affected.clientId, affected.previousClientId, ...(affected.clientIds ?? []))
  const invalidations = [
    queryClient.invalidateQueries({ queryKey: taskKeys.all() }),
    queryClient.invalidateQueries({ queryKey: incidentKeys.all() }),
    queryClient.invalidateQueries({ queryKey: projectKeys.all() }),
    queryClient.invalidateQueries({ queryKey: timeKeys.all() }),
    queryClient.invalidateQueries({ queryKey: ["active-timer"] }),
    queryClient.invalidateQueries({ queryKey: dashboardKeys.all() }),
    queryClient.invalidateQueries({ queryKey: briefingKeys.all() }),
    queryClient.invalidateQueries({ queryKey: searchKeys.all() }),
    queryClient.invalidateQueries({ queryKey: ["client-portfolio"] }),
  ]
  if (clientIds.length === 0) invalidations.push(queryClient.invalidateQueries({ queryKey: ["client-status"] }))
  for (const clientId of clientIds) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: clientKeys.summary(clientId) }),
      queryClient.invalidateQueries({ queryKey: clientKeys.dashboard(clientId) }),
      queryClient.invalidateQueries({ queryKey: ["client-activity", clientId] }),
      queryClient.invalidateQueries({ queryKey: ["client-status", clientId] }),
    )
  }
  await Promise.all(invalidations)
}

export async function invalidateProjectChange(queryClient: QueryClient, affected: OperationalImpact = {}) {
  const clientIds = uniqueIds(affected.clientId, affected.previousClientId, ...(affected.clientIds ?? []))
  const invalidations = [
    queryClient.invalidateQueries({ queryKey: incidentKeys.all() }),
    queryClient.invalidateQueries({ queryKey: projectKeys.all() }),
    queryClient.invalidateQueries({ queryKey: taskKeys.all() }),
    queryClient.invalidateQueries({ queryKey: timeKeys.all() }),
    queryClient.invalidateQueries({ queryKey: briefingKeys.all() }),
    queryClient.invalidateQueries({ queryKey: dashboardKeys.all() }),
    queryClient.invalidateQueries({ queryKey: searchKeys.all() }),
    queryClient.invalidateQueries({ queryKey: ["client-portfolio"] }),
  ]
  if (clientIds.length === 0) invalidations.push(queryClient.invalidateQueries({ queryKey: ["client-status"] }))
  for (const clientId of clientIds) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: clientKeys.summary(clientId) }),
      queryClient.invalidateQueries({ queryKey: clientKeys.dashboard(clientId) }),
      queryClient.invalidateQueries({ queryKey: ["client-activity", clientId] }),
      queryClient.invalidateQueries({ queryKey: ["client-status", clientId] }),
    )
  }
  await Promise.all(invalidations)
}

export async function invalidateTimeChange(queryClient: QueryClient, affected: OperationalImpact = {}) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: clientKeys.summaries() }),
    queryClient.invalidateQueries({ queryKey: ["client-dashboard"] }),
    invalidateTaskChange(queryClient, affected),
  ])
}

export type QuerySnapshot = readonly [QueryKey, unknown]

export async function optimisticallyUpdateExactQuery<T>(
  queryClient: QueryClient,
  queryKey: QueryKey,
  updater: (old: T | undefined) => T | undefined,
): Promise<QuerySnapshot> {
  await queryClient.cancelQueries({ queryKey, exact: true })
  const snapshot: QuerySnapshot = [queryKey, queryClient.getQueryData<T>(queryKey)]
  queryClient.setQueryData<T>(queryKey, updater)
  return snapshot
}

export function restoreQuerySnapshot(queryClient: QueryClient, snapshot?: QuerySnapshot) {
  if (snapshot) queryClient.setQueryData(snapshot[0], snapshot[1])
}

export const clientKeys = {
  all: () => ["clients"] as const,
  dashboard: (clientId: number) => ["client-dashboard", clientId] as const,
  summary: (clientId: number) => ["client-summary", clientId] as const,
  summaries: () => ["client-summary"] as const,
}

// Control SEO: todo lo de un cliente cuelga de ["client-seo", id] (los términos
// de marca cambian el reparto, así que guardar la ficha lo invalida entero).
export const clientSeoKeys = {
  all: (clientId: number) => ["client-seo", clientId] as const,
  summary: (clientId: number, days: number) => ["client-seo", clientId, "summary", days] as const,
  list: (clientId: number, kind: "queries" | "pages", params: object) =>
    ["client-seo", clientId, kind, params] as const,
  history: (clientId: number, query: string) => ["client-seo", clientId, "history", query] as const,
  groups: (clientId: number, days: number) => ["client-seo", clientId, "groups", days] as const,
  leads: (clientId: number) => ["client-seo", clientId, "leads"] as const,
}

export async function invalidateClientChange(queryClient: QueryClient, clientIds: number[] = []) {
  const invalidations = [
    queryClient.invalidateQueries({ queryKey: clientKeys.all() }),
    queryClient.invalidateQueries({ queryKey: clientKeys.summaries() }),
    queryClient.invalidateQueries({ queryKey: ["clients-all"] }),
    queryClient.invalidateQueries({ queryKey: ["clients-all-active"] }),
    queryClient.invalidateQueries({ queryKey: ["clients-active"] }),
    queryClient.invalidateQueries({ queryKey: ["clients-active-list"] }),
    queryClient.invalidateQueries({ queryKey: ["clients-list"] }),
    queryClient.invalidateQueries({ queryKey: ["client-portfolio"] }),
    queryClient.invalidateQueries({ queryKey: ["active-timer"] }),
    queryClient.invalidateQueries({ queryKey: ["admin-active-timers"] }),
    queryClient.invalidateQueries({ queryKey: projectKeys.all() }),
    queryClient.invalidateQueries({ queryKey: taskKeys.all() }),
    queryClient.invalidateQueries({ queryKey: timeKeys.all() }),
    queryClient.invalidateQueries({ queryKey: incidentKeys.all() }),
    queryClient.invalidateQueries({ queryKey: dashboardKeys.all() }),
    queryClient.invalidateQueries({ queryKey: briefingKeys.all() }),
    queryClient.invalidateQueries({ queryKey: searchKeys.all() }),
  ]
  for (const clientId of uniqueIds(...clientIds)) {
    invalidations.push(
      queryClient.invalidateQueries({ queryKey: clientKeys.dashboard(clientId) }),
      queryClient.invalidateQueries({ queryKey: ["client-activity", clientId] }),
      queryClient.invalidateQueries({ queryKey: ["client-status", clientId] }),
      queryClient.invalidateQueries({ queryKey: clientSeoKeys.all(clientId) }),
    )
  }
  await Promise.all(invalidations)
}

export const holdedKeys = {
  config: () => ["holded-config"] as const,
  dashboard: () => ["holded-dashboard"] as const,
  invoices: (status: string, dateFrom: string, dateTo: string, page: number) =>
    ["holded-invoices", status, dateFrom, dateTo, page] as const,
  expenses: (category: string, dateFrom: string, dateTo: string, page: number) =>
    ["holded-expenses", category, dateFrom, dateTo, page] as const,
  syncLogs: (limit: number) => ["holded-sync-logs", limit] as const,
  clientInvoices: (clientId: number) => ["holded-client-invoices", clientId] as const,
}

export const inboxKeys = {
  all: (userId: number) => ["inbox", userId] as const,
  list: (userId: number, status?: string, pageSize = 50) => ["inbox", userId, "list", status ?? "all", pageSize] as const,
  preview: (userId: number, status?: string, limit = 5) => ["inbox", userId, "preview", status ?? "all", limit] as const,
  count: (userId: number) => ["inbox", userId, "count"] as const,
}

export const suggestionKeys = {
  all: ["suggestions"] as const,
  list: (status: string) => ["suggestions", "list", status] as const,
}

export const searchKeys = {
  all: () => ["global-search"] as const,
  results: (userId: number, permissionSignature: string, query: string) => ["global-search", userId, permissionSignature, query] as const,
}

export function isHoldedQueryKey(queryKey: readonly unknown[]): boolean {
  const key = queryKey[0]
  return typeof key === "string" && key.startsWith("holded-")
}
