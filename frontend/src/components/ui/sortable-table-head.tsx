import { ChevronUp, ChevronDown } from "lucide-react"
import { TableHead } from "@/components/ui/table"
import type { SortConfig } from "@/hooks/use-table-sort"

interface Props {
  sortKey: string
  currentSort: SortConfig | null
  onSort: (key: string) => void
  children: React.ReactNode
  className?: string
}

export function SortableTableHead({ sortKey, currentSort, onSort, children, className }: Props) {
  const isActive = currentSort?.key === sortKey
  const direction = isActive ? currentSort.direction : null

  return (
    <TableHead
      className={`cursor-pointer select-none hover:text-foreground transition-colors ${className ?? ""}`}
      onClick={() => onSort(sortKey)}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        {isActive && (
          direction === "asc"
            ? <ChevronUp className="h-3.5 w-3.5" />
            : <ChevronDown className="h-3.5 w-3.5" />
        )}
      </span>
    </TableHead>
  )
}
