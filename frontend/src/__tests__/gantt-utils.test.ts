import { describe, it, expect } from "vitest"
import {
  calculateConfig,
  dateToX,
  getBarProps,
  getTopHeaders,
  getTimeColumns,
  isToday,
} from "@/components/gantt/gantt-utils"
import type { GanttConfig } from "@/components/gantt/gantt-utils"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeConfig(overrides?: Partial<GanttConfig>): GanttConfig {
  const startDate = new Date(2026, 0, 1) // Jan 1 2026
  const endDate = new Date(2026, 2, 31) // Mar 31 2026
  return {
    startDate,
    endDate,
    zoom: "month",
    dayWidth: 14,
    totalDays: 90,
    totalWidth: 90 * 14,
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// calculateConfig
// ---------------------------------------------------------------------------

describe("calculateConfig", () => {
  it("returns correct dayWidth for each zoom level", () => {
    const week = calculateConfig(new Date(2026, 0, 1), new Date(2026, 2, 31), "week")
    expect(week.dayWidth).toBe(40)

    const month = calculateConfig(new Date(2026, 0, 1), new Date(2026, 2, 31), "month")
    expect(month.dayWidth).toBe(14)

    const quarter = calculateConfig(new Date(2026, 0, 1), new Date(2026, 2, 31), "quarter")
    expect(quarter.dayWidth).toBe(5)
  })

  it("adds padding around project dates", () => {
    const start = new Date(2026, 0, 15)
    const end = new Date(2026, 1, 15)
    const config = calculateConfig(start, end, "month")

    // Start should be 7 days before project start
    expect(config.startDate.getTime()).toBeLessThan(start.getTime())
    // End should be 14 days after project end
    expect(config.endDate.getTime()).toBeGreaterThan(end.getTime())
  })

  it("totalWidth = totalDays * dayWidth", () => {
    const config = calculateConfig(new Date(2026, 0, 1), new Date(2026, 5, 30), "month")
    expect(config.totalWidth).toBe(config.totalDays * config.dayWidth)
  })

  it("handles null dates gracefully (falls back to current date range)", () => {
    const config = calculateConfig(null, null, "month")
    expect(config.totalDays).toBeGreaterThanOrEqual(30)
    expect(config.dayWidth).toBe(14)
  })

  it("ensures minimum 30 days", () => {
    // Even for a very short project
    const config = calculateConfig(new Date(2026, 0, 1), new Date(2026, 0, 5), "week")
    expect(config.totalDays).toBeGreaterThanOrEqual(30)
  })
})

// ---------------------------------------------------------------------------
// dateToX
// ---------------------------------------------------------------------------

describe("dateToX", () => {
  it("returns 0 for the config startDate", () => {
    const config = makeConfig()
    expect(dateToX(config.startDate, config)).toBe(0)
  })

  it("returns dayWidth for one day after startDate", () => {
    const config = makeConfig({ dayWidth: 14 })
    const nextDay = new Date(config.startDate)
    nextDay.setDate(nextDay.getDate() + 1)
    expect(dateToX(nextDay, config)).toBe(14)
  })

  it("returns negative value for dates before startDate", () => {
    const config = makeConfig()
    const before = new Date(config.startDate)
    before.setDate(before.getDate() - 5)
    expect(dateToX(before, config)).toBeLessThan(0)
  })

  it("scales correctly for 10 days", () => {
    const config = makeConfig({ dayWidth: 40 })
    const tenDaysLater = new Date(config.startDate)
    tenDaysLater.setDate(tenDaysLater.getDate() + 10)
    expect(dateToX(tenDaysLater, config)).toBe(400)
  })
})

// ---------------------------------------------------------------------------
// getBarProps
// ---------------------------------------------------------------------------

describe("getBarProps", () => {
  it("returns null when both start and end are null", () => {
    const config = makeConfig()
    expect(getBarProps(null, null, config)).toBeNull()
  })

  it("returns a thin marker when only end date is provided", () => {
    const config = makeConfig()
    const end = new Date(2026, 0, 15)
    const bar = getBarProps(null, end, config)
    expect(bar).not.toBeNull()
    expect(bar!.width).toBe(8) // point marker
  })

  it("returns a proper bar when both dates are provided", () => {
    const config = makeConfig({ dayWidth: 14 })
    const start = new Date(2026, 0, 10) // Day 9 from Jan 1
    const end = new Date(2026, 0, 20) // Day 19 from Jan 1
    const bar = getBarProps(start, end, config)
    expect(bar).not.toBeNull()
    expect(bar!.width).toBe(10 * 14) // 10 days * 14px
  })

  it("enforces minimum width of 8px", () => {
    const config = makeConfig({ dayWidth: 2 })
    const start = new Date(2026, 0, 10)
    const end = new Date(2026, 0, 11) // 1 day = 2px, below 8
    const bar = getBarProps(start, end, config)
    expect(bar!.width).toBeGreaterThanOrEqual(8)
  })

  it("handles open-ended bar (start only, no end)", () => {
    const config = makeConfig()
    const start = new Date(2026, 0, 10)
    const bar = getBarProps(start, null, config)
    expect(bar).not.toBeNull()
    expect(bar!.width).toBeGreaterThanOrEqual(8)
  })
})

// ---------------------------------------------------------------------------
// getTopHeaders
// ---------------------------------------------------------------------------

describe("getTopHeaders", () => {
  it("returns one header per month in the range", () => {
    const config = makeConfig({
      startDate: new Date(2026, 0, 1),
      endDate: new Date(2026, 2, 31),
      dayWidth: 14,
    })
    const headers = getTopHeaders(config)
    // Jan, Feb, Mar
    expect(headers.length).toBe(3)
    expect(headers[0].label).toContain("ene")
    expect(headers[1].label).toContain("feb")
    expect(headers[2].label).toContain("mar")
  })

  it("each header has non-negative width", () => {
    const config = makeConfig()
    const headers = getTopHeaders(config)
    headers.forEach((h) => {
      expect(h.width).toBeGreaterThanOrEqual(0)
    })
  })
})

// ---------------------------------------------------------------------------
// getTimeColumns
// ---------------------------------------------------------------------------

describe("getTimeColumns", () => {
  it("in week zoom, returns one column per day", () => {
    const config = makeConfig({
      startDate: new Date(2026, 0, 1),
      endDate: new Date(2026, 0, 7),
      zoom: "week",
      dayWidth: 40,
      totalDays: 7,
      totalWidth: 280,
    })
    const cols = getTimeColumns(config)
    // 7 days inclusive
    expect(cols.length).toBe(7)
    // First column at left 0
    expect(cols[0].left).toBe(0)
    expect(cols[0].width).toBe(40)
  })

  it("in month zoom, returns week-based columns", () => {
    const config = makeConfig({
      startDate: new Date(2026, 0, 1),
      endDate: new Date(2026, 0, 31),
      zoom: "month",
      dayWidth: 14,
    })
    const cols = getTimeColumns(config)
    // Should have ~5 weeks in January
    expect(cols.length).toBeGreaterThanOrEqual(4)
    expect(cols.length).toBeLessThanOrEqual(6)
  })

  it("in quarter zoom, returns month-based columns", () => {
    const config = makeConfig({
      startDate: new Date(2026, 0, 1),
      endDate: new Date(2026, 2, 31),
      zoom: "quarter",
      dayWidth: 5,
    })
    const cols = getTimeColumns(config)
    expect(cols.length).toBe(3) // Jan, Feb, Mar
  })
})

// ---------------------------------------------------------------------------
// isToday
// ---------------------------------------------------------------------------

describe("isToday", () => {
  it("returns true for today", () => {
    expect(isToday(new Date())).toBe(true)
  })

  it("returns false for yesterday", () => {
    const yesterday = new Date()
    yesterday.setDate(yesterday.getDate() - 1)
    expect(isToday(yesterday)).toBe(false)
  })

  it("returns false for a fixed past date", () => {
    expect(isToday(new Date(2020, 5, 15))).toBe(false)
  })
})
