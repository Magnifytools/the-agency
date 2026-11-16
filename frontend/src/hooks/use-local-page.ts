import { useState } from "react"

/**
 * Paginación en el navegador de una lista que ya está entera en memoria. Si la
 * lista encoge (otra ventana, otro filtro), la página se ajusta a la última.
 */
export function useLocalPage<T>(items: T[], pageSize = 10) {
  const [page, setPage] = useState(1)
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize))
  const current = Math.min(page, totalPages)
  return {
    page: current,
    setPage,
    pageSize,
    total: items.length,
    rows: items.slice((current - 1) * pageSize, current * pageSize),
  }
}
