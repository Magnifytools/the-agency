import {
  differenceInDays,
  eachMonthOfInterval,
  eachWeekOfInterval,
  endOfWeek,
  endOfMonth,
  format,
  addDays,
  subDays,
  max as dateMax,
  min as dateMin,
} from "date-fns"
import { es } from "date-fns/locale"

export type ZoomLevel = "week" | "month" | "quarter"

export interface GanttConfig {
  startDate: Date
  endDate: Date
  zoom: ZoomLevel
  dayWidth: number
  totalWidth: number
  totalDays: number
}

export interface TimeColumn {
  label: string
  left: number
  width: number
}

export interface TimeHeaderGroup {
  label: string
  left: number
  width: number
}

const ZOOM_DAY_WIDTH: Record<ZoomLevel, number> = {
  week: 40,
  month: 14,
  quarter: 5,
}

const ZOOM_PADDING: Record<ZoomLevel, { before: number; after: number; minDays: number }> = {
  week: { before: 3, after: 7, minDays: 14 },
  month: { before: 7, after: 14, minDays: 30 },
  quarter: { before: 14, after: 30, minDays: 90 },
}

export function calculateConfig(
  projectStart: Date | null,
  projectEnd: Date | null,
  zoom: ZoomLevel
): GanttConfig {
  const now = new Date()
  const padding = ZOOM_PADDING[zoom]
  const start = projectStart ? subDays(projectStart, padding.before) : subDays(now, padding.minDays)
  const end = projectEnd ? addDays(projectEnd, padding.after) : addDays(now, padding.minDays)

  const dayWidth = ZOOM_DAY_WIDTH[zoom]
  const totalDays = Math.max(differenceInDays(end, start), padding.minDays)
  const totalWidth = totalDays * dayWidth

  return { startDate: start, endDate: end, zoom, dayWidth, totalWidth, totalDays }
}

export function dateToX(date: Date, config: GanttConfig): number {
  const days = differenceInDays(date, config.startDate)
  return days * config.dayWidth
}

export function getBarProps(
  start: Date | null,
  end: Date | null,
  config: GanttConfig
): { left: number; width: number } | null {
  if (!start && !end) return null
  if (!start && end) {
    // Point marker — return thin bar at end position
    const x = dateToX(end, config)
    return { left: x - 4, width: 8 }
  }
  if (start && !end) {
    // Open-ended bar from start to today or 7 days
    const endDate = dateMax([new Date(), addDays(start, 7)])
    const left = dateToX(start, config)
    const right = dateToX(endDate, config)
    return { left, width: Math.max(right - left, 8) }
  }
  // Both dates
  const left = dateToX(start!, config)
  const right = dateToX(end!, config)
  return { left, width: Math.max(right - left, 8) }
}

export function getTopHeaders(config: GanttConfig): TimeHeaderGroup[] {
  if (config.zoom === "quarter") {
    // Group by quarter
    const months = eachMonthOfInterval({ start: config.startDate, end: config.endDate })
    const quarters: TimeHeaderGroup[] = []
    let currentQ = -1
    let currentYear = -1
    let qLeft = 0

    months.forEach((monthStart, i) => {
      const q = Math.floor(monthStart.getMonth() / 3)
      const y = monthStart.getFullYear()
      const monthEnd = dateMin([endOfMonth(monthStart), config.endDate])
      const right = dateToX(monthEnd, config)

      if (q !== currentQ || y !== currentYear) {
        if (currentQ >= 0) {
          quarters[quarters.length - 1].width = dateToX(dateMax([monthStart, config.startDate]), config) - qLeft
        }
        currentQ = q
        currentYear = y
        qLeft = dateToX(dateMax([monthStart, config.startDate]), config)
        quarters.push({
          label: `T${q + 1} ${y}`,
          left: qLeft,
          width: 0,
        })
      }

      if (i === months.length - 1) {
        quarters[quarters.length - 1].width = Math.max(right - qLeft, 0)
      }
    })

    return quarters
  }

  const months = eachMonthOfInterval({ start: config.startDate, end: config.endDate })
  return months.map((monthStart) => {
    const monthEnd = dateMin([endOfMonth(monthStart), config.endDate])
    const left = dateToX(dateMax([monthStart, config.startDate]), config)
    const right = dateToX(monthEnd, config)
    return {
      label: format(monthStart, "MMM yyyy", { locale: es }),
      left,
      width: Math.max(right - left, 0),
    }
  })
}

export function getTimeColumns(config: GanttConfig): TimeColumn[] {
  if (config.zoom === "week") {
    // Show individual days
    const cols: TimeColumn[] = []
    let d = config.startDate
    while (d <= config.endDate) {
      const left = dateToX(d, config)
      cols.push({
        label: format(d, "d", { locale: es }),
        left,
        width: config.dayWidth,
      })
      d = addDays(d, 1)
    }
    return cols
  }

  if (config.zoom === "month") {
    // Show weeks
    const weeks = eachWeekOfInterval(
      { start: config.startDate, end: config.endDate },
      { weekStartsOn: 1 }
    )
    return weeks.map((weekStart) => {
      const wEnd = dateMin([endOfWeek(weekStart, { weekStartsOn: 1 }), config.endDate])
      const wStart = dateMax([weekStart, config.startDate])
      const left = dateToX(wStart, config)
      const right = dateToX(wEnd, config)
      return {
        label: format(weekStart, "d MMM", { locale: es }),
        left,
        width: Math.max(right - left, 0),
      }
    })
  }

  // Quarter zoom — show months
  const months = eachMonthOfInterval({ start: config.startDate, end: config.endDate })
  return months.map((monthStart) => {
    const mEnd = dateMin([endOfMonth(monthStart), config.endDate])
    const mStart = dateMax([monthStart, config.startDate])
    const left = dateToX(mStart, config)
    const right = dateToX(mEnd, config)
    return {
      label: format(monthStart, "MMM", { locale: es }),
      left,
      width: Math.max(right - left, 0),
    }
  })
}

export function isToday(date: Date): boolean {
  const now = new Date()
  return (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  )
}
