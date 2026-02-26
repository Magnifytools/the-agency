import type { GanttConfig } from "./gantt-utils"
import { getBarProps } from "./gantt-utils"

const STATUS_COLORS: Record<string, string> = {
  pending: "#6B7280",
  in_progress: "#FEE630",
  completed: "#22C55E",
  cancelled: "#EF4444",
}

interface GanttRowProps {
  label: string
  startDate: Date | null
  endDate: Date | null
  status: string
  type: "phase" | "task" | "milestone"
  phaseType?: "sprint" | "milestone" | "standard"
  config: GanttConfig
  isChild?: boolean
  assignedTo?: string | null
}

export function GanttRow({
  label,
  startDate,
  endDate,
  status,
  type,
  phaseType,
  config,
  isChild,
  assignedTo,
}: GanttRowProps) {
  const bar = getBarProps(startDate, endDate, config)
  const color = STATUS_COLORS[status] || "#6B7280"
  const isMilestone = type === "milestone" || phaseType === "milestone"
  const isPointMarker = !startDate && endDate

  return (
    <div className="flex group hover:bg-muted/30 transition-colors">
      {/* Label column — sticky left */}
      <div
        className="sticky left-0 z-20 bg-card flex items-center gap-2 border-r border-border px-3 py-1.5 flex-shrink-0"
        style={{ width: 220, minWidth: 220 }}
      >
        {isChild && <div className="w-3" />}
        {isMilestone ? (
          <div
            className="w-2.5 h-2.5 rotate-45 flex-shrink-0"
            style={{ backgroundColor: color }}
          />
        ) : (
          <div
            className="w-2 h-2 rounded-full flex-shrink-0"
            style={{ backgroundColor: color }}
          />
        )}
        <span
          className={`text-xs truncate ${type === "phase" ? "font-semibold text-foreground" : "text-muted-foreground"}`}
          title={label}
        >
          {label}
        </span>
        {assignedTo && (
          <span className="text-[9px] text-muted-foreground/60 truncate ml-auto">
            {assignedTo}
          </span>
        )}
      </div>

      {/* Timeline area */}
      <div
        className="relative flex-1 border-b border-border/20"
        style={{ height: type === "phase" ? 32 : 28 }}
      >
        {bar && !isMilestone && !isPointMarker && (
          <div
            className="absolute top-1/2 -translate-y-1/2 rounded-md transition-all"
            style={{
              left: bar.left,
              width: bar.width,
              height: type === "phase" ? 18 : 12,
              backgroundColor: color,
              opacity: type === "phase" ? 0.7 : 0.5,
            }}
            title={`${label}: ${startDate?.toLocaleDateString("es-ES") || "?"} — ${endDate?.toLocaleDateString("es-ES") || "?"}`}
          />
        )}
        {bar && isPointMarker && !isMilestone && (
          <div
            className="absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full border-2"
            style={{
              left: bar.left,
              borderColor: color,
              backgroundColor: `${color}40`,
            }}
            title={`${label}: ${endDate?.toLocaleDateString("es-ES")}`}
          />
        )}
        {bar && isMilestone && (
          <div
            className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rotate-45"
            style={{
              left: bar.left,
              backgroundColor: color,
            }}
            title={`${label}: ${(endDate || startDate)?.toLocaleDateString("es-ES")}`}
          />
        )}
      </div>
    </div>
  )
}
