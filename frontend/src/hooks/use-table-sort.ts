import { useState, useMemo } from "react"

export interface SortConfig {
  key: string
  direction: "asc" | "desc"
}

const SORT_WEIGHTS: Record<string, Record<string, number>> = {
  priority: { urgent: 4, high: 3, medium: 2, low: 1 },
  status: { backlog: 0, pending: 1, in_progress: 2, waiting: 3, in_review: 4, completed: 5 },
}

export function useTableSort<T>(items: T[], defaultSort?: SortConfig) {
  const [sortConfig, setSortConfig] = useState<SortConfig | null>(defaultSort ?? null)

  const requestSort = (key: string) => {
    setSortConfig((prev) => {
      if (prev?.key === key) {
        // asc → desc → null (reset)
        if (prev.direction === "asc") return { key, direction: "desc" }
        return null
      }
      return { key, direction: "asc" }
    })
  }

  const sortedItems = useMemo(() => {
    if (!sortConfig) return items
    const { key, direction } = sortConfig
    const weights = SORT_WEIGHTS[key]

    return [...items].sort((a, b) => {
      const aVal = (a as Record<string, unknown>)[key]
      const bVal = (b as Record<string, unknown>)[key]

      // Nulls always at end regardless of direction
      if (aVal == null && bVal == null) return 0
      if (aVal == null) return 1
      if (bVal == null) return -1

      let cmp = 0

      if (weights) {
        // Weight-based sort (priority, status)
        const aw = weights[String(aVal)] ?? 0
        const bw = weights[String(bVal)] ?? 0
        cmp = aw - bw
      } else if (key === "due_date" || key === "scheduled_date" || key === "follow_up_date") {
        // Date sort
        cmp = new Date(String(aVal)).getTime() - new Date(String(bVal)).getTime()
      } else if (typeof aVal === "string" && typeof bVal === "string") {
        cmp = aVal.localeCompare(bVal, "es", { sensitivity: "base" })
      } else if (typeof aVal === "number" && typeof bVal === "number") {
        cmp = aVal - bVal
      } else {
        cmp = String(aVal).localeCompare(String(bVal), "es", { sensitivity: "base" })
      }

      return direction === "desc" ? -cmp : cmp
    })
  }, [items, sortConfig])

  return { sortedItems, sortConfig, requestSort }
}
