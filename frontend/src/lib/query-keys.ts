import type { QueryClient, QueryKey } from "@tanstack/react-query"

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

export async function invalidateTaskChange(
  queryClient: QueryClient,
  affected: { projectId?: number | null; clientId?: number | null } = {},
) {
  const invalidations = [
    queryClient.invalidateQueries({ queryKey: taskKeys.all() }),
    queryClient.invalidateQueries({ queryKey: projectKeys.all() }),
  ]
  if (affected.clientId != null) {
    invalidations.push(queryClient.invalidateQueries({ queryKey: clientKeys.summary(affected.clientId) }))
  }
  await Promise.all(invalidations)
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
  dashboard: (clientId: number) => ["client-dashboard", clientId] as const,
  billing: (clientId: number) => ["billing-events", clientId] as const,
  billingStatus: (clientId: number) => ["billing-status", clientId] as const,
  summary: (clientId: number) => ["client-summary", clientId] as const,
  resources: (clientId: number) => ["client-resources", clientId] as const,
  reports: (clientId: number) => ["client-reports", clientId] as const,
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

export const vaultKeys = {
  assets: (category?: string) => ["vault-assets", category ?? "all"] as const,
}

export const inboxKeys = {
  all: () => ["inbox-notes"] as const,
  list: (status?: string) => ["inbox-notes", status ?? "all"] as const,
  count: () => ["inbox-count"] as const,
}

export function isHoldedQueryKey(queryKey: readonly unknown[]): boolean {
  const key = queryKey[0]
  return typeof key === "string" && key.startsWith("holded-")
}
