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
