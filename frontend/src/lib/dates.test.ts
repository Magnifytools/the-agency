import { afterEach, describe, expect, it } from "vitest"

import {
  businessDateString,
  civilDayUtcRange,
  formatCivilDate,
  millisecondsUntilNextBusinessDay,
  parseApiInstant,
  setAgencyTimezone,
  timeEntryBusinessDate,
} from "./dates"

afterEach(() => setAgencyTimezone("Europe/Madrid"))

describe("agency date contract", () => {
  it("renders timer and manual entries using their distinct stored date meanings", () => {
    const date = "2026-09-17T22:30:00"
    expect(timeEntryBusinessDate({ date, started_at: date })).toBe("2026-09-18")
    expect(timeEntryBusinessDate({ date, started_at: null })).toBe("2026-09-17")
  })
  it("uses the configured business date at Madrid midnight", () => {
    setAgencyTimezone("Europe/Madrid")
    expect(businessDateString(new Date("2026-09-17T22:30:00Z"))).toBe("2026-09-18")
    expect(millisecondsUntilNextBusinessDay(new Date("2026-09-17T21:59:30Z"))).toBeCloseTo(30_000, -3)
  })

  it("builds DST-aware half-open UTC ranges", () => {
    expect(civilDayUtcRange("2026-03-29")).toEqual({
      start: "2026-03-28T23:00:00.000Z",
      end: "2026-03-29T22:00:00.000Z",
    })
    expect(civilDayUtcRange("2026-10-25")).toEqual({
      start: "2026-10-24T22:00:00.000Z",
      end: "2026-10-25T23:00:00.000Z",
    })
  })

  it("keeps civil dates unchanged in browsers west and east of UTC", () => {
    setAgencyTimezone("America/Los_Angeles")
    expect(businessDateString(new Date("2026-09-18T06:30:00Z"))).toBe("2026-09-17")
    setAgencyTimezone("Asia/Shanghai")
    expect(businessDateString(new Date("2026-09-17T16:30:00Z"))).toBe("2026-09-18")
    expect(formatCivilDate("2026-09-17", { day: "2-digit", month: "2-digit", year: "numeric" })).toBe("17/09/2026")
  })

  it("parses legacy naive API instants as UTC and respects explicit offsets", () => {
    expect(parseApiInstant("2026-09-17T22:30:00").toISOString()).toBe("2026-09-17T22:30:00.000Z")
    expect(parseApiInstant("2026-09-18T00:30:00+02:00").toISOString()).toBe("2026-09-17T22:30:00.000Z")
  })
})
