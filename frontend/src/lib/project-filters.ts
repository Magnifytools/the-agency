/** Civil date boundaries for the user's current week/month/quarter. */
export function projectPeriodBounds(period: string, now = new Date()): { period_from?: string; period_to?: string } {
  const year = now.getFullYear()
  const month = now.getMonth()
  let start: Date
  let end: Date
  if (period === "week") {
    start = new Date(year, month, now.getDate() - (now.getDay() + 6) % 7)
    end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 6)
  } else if (period === "month") {
    start = new Date(year, month, 1)
    end = new Date(year, month + 1, 0)
  } else if (period === "quarter") {
    const firstMonth = Math.floor(month / 3) * 3
    start = new Date(year, firstMonth, 1)
    end = new Date(year, firstMonth + 3, 0)
  } else return {}
  const civilDate = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`
  return { period_from: civilDate(start), period_to: civilDate(end) }
}
