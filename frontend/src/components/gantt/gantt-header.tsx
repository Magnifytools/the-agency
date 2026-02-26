import type { GanttConfig } from "./gantt-utils"
import { getTopHeaders, getTimeColumns } from "./gantt-utils"

interface GanttHeaderProps {
  config: GanttConfig
}

export function GanttHeader({ config }: GanttHeaderProps) {
  const topHeaders = getTopHeaders(config)
  const columns = getTimeColumns(config)

  return (
    <div className="sticky top-0 z-10 border-b border-border bg-card/95 backdrop-blur-sm">
      {/* Month row */}
      <div className="relative h-6" style={{ width: config.totalWidth }}>
        {topHeaders.map((h, i) => (
          <div
            key={i}
            className="absolute top-0 h-full flex items-center px-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground border-r border-border/50"
            style={{ left: h.left, width: h.width }}
          >
            {h.width > 40 ? h.label : ""}
          </div>
        ))}
      </div>
      {/* Week/Day row */}
      <div className="relative h-5" style={{ width: config.totalWidth }}>
        {columns.map((col, i) => (
          <div
            key={i}
            className="absolute top-0 h-full flex items-center justify-center text-[9px] text-muted-foreground/70 border-r border-border/30"
            style={{ left: col.left, width: col.width }}
          >
            {col.width > 20 ? col.label : ""}
          </div>
        ))}
      </div>
    </div>
  )
}
