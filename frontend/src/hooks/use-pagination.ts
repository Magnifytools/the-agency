import { useState, useCallback } from "react"

export function usePagination(defaultPageSize = 25) {
  const [page, setPage] = useState(1)
  const [pageSize] = useState(defaultPageSize)

  const reset = useCallback(() => setPage(1), [])

  return { page, pageSize, setPage, reset }
}
