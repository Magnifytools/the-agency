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

export function isHoldedQueryKey(queryKey: readonly unknown[]): boolean {
  const key = queryKey[0]
  return typeof key === "string" && key.startsWith("holded-")
}
