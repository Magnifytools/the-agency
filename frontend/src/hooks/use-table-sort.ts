import { useState, useMemo } from "react"

export interface SortConfig {
  key: string
  direction: "asc" | "desc"
}

export function useTableSort<T>(items: T[], defaultSort?: SortConfig) {
  const [sortConfig, setSortConfig] = useState<SortConfig | null>(defaultSort ?? null)

  const requestSort = (key: string) => {
    setSortConfig((prev) => {
      if (prev?.key === key) {
        return { key, direction: prev.direction === "asc" ? "desc" : "asc" }
      }
      return { key, direction: "asc" }
    })
  }

  const sortedItems = useMemo(() => {
    if (!sortConfig) return items
    const { key, direction } = sortConfig
    return [...items].sort((a, b) => {
      const aVal = (a as Record<string, unknown>)[key]
      const bVal = (b as Record<string, unknown>)[key]

      if (aVal == null && bVal == null) return 0
      if (aVal == null) return 1
      if (bVal == null) return -1

      let cmp = 0
      if (typeof aVal === "string" && typeof bVal === "string") {
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
