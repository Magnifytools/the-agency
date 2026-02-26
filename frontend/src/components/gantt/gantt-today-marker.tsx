import { dateToX, type GanttConfig } from "./gantt-utils"

interface GanttTodayMarkerProps {
  config: GanttConfig
}

export function GanttTodayMarker({ config }: GanttTodayMarkerProps) {
  const x = dateToX(new Date(), config)
  if (x < 0 || x > config.totalWidth) return null

  return (
    <div
      className="absolute top-0 bottom-0 z-10 pointer-events-none"
      style={{ left: 220 + x }}
    >
      <div className="w-0.5 h-full bg-brand/60" style={{ borderLeft: "2px dashed #FEE630" }} />
      <div className="absolute -top-0.5 -left-2 bg-brand text-background text-[8px] font-bold px-1 rounded-sm">
        HOY
      </div>
    </div>
  )
}
