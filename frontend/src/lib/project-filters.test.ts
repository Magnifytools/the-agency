import { describe, expect, it } from "vitest"
import { projectPeriodBounds } from "./project-filters"

describe("project period civil dates", () => {
  it("keeps Sunday in the Monday-based week across a year boundary", () => {
    expect(projectPeriodBounds("week", new Date(2027, 0, 3, 0, 15))).toEqual({ period_from: "2026-12-28", period_to: "2027-01-03" })
  })
  it("includes the last day of a leap month and quarter", () => {
    expect(projectPeriodBounds("month", new Date(2028, 1, 10))).toEqual({ period_from: "2028-02-01", period_to: "2028-02-29" })
    expect(projectPeriodBounds("quarter", new Date(2026, 11, 31))).toEqual({ period_from: "2026-10-01", period_to: "2026-12-31" })
  })
  it("leaves an unfiltered request without date bounds", () => {
    expect(projectPeriodBounds("")).toEqual({})
  })
})
