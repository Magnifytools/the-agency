import { useState, useCallback, useMemo } from "react"

export function useBulkSelect<T extends { id: number }>(items: T[]) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  const isSelected = useCallback((id: number) => selectedIds.has(id), [selectedIds])

  const toggleItem = useCallback((id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }, [])

  const toggleAll = useCallback(() => {
    setSelectedIds((prev) => {
      if (prev.size === items.length) {
        return new Set()
      }
      return new Set(items.map((i) => i.id))
    })
  }, [items])

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set())
  }, [])

  const selectedCount = selectedIds.size

  const allSelected = useMemo(() => items.length > 0 && selectedIds.size === items.length, [items, selectedIds])

  return { selectedIds, isSelected, toggleItem, toggleAll, clearSelection, selectedCount, allSelected }
}
