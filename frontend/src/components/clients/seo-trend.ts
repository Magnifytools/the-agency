/** "▼ 42,5 %": variation of organic clicks vs the previous 30 days. */
export function formatChangePct(pct: number): string {
  const arrow = pct > 0 ? "▲" : pct < 0 ? "▼" : "="
  return `${arrow} ${Math.abs(pct).toLocaleString("es-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`
}
