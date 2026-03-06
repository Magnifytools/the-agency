export function formatCurrency(n: number, currency = "EUR"): string {
  return n.toLocaleString("es-ES", { style: "currency", currency })
}

export function formatCompact(n: number): string {
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}k`
  return n.toFixed(0)
}
