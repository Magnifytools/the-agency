import { describe, expect, it } from "vitest"
import { ruleForPattern, toggleWeekday } from "./recurrence"

describe("ruleForPattern", () => {
  it("keeps only what each rule uses", () => {
    expect(ruleForPattern({ recurrence_day: 3, recurrence_weekdays: null }, "weekdays"))
      .toEqual({ recurrence_pattern: "weekdays", recurrence_day: null, recurrence_weekdays: [3] })
    expect(ruleForPattern({ recurrence_day: null, recurrence_weekdays: [1, 4] }, "quarterly"))
      .toEqual({ recurrence_pattern: "quarterly", recurrence_day: 1, recurrence_weekdays: null })
    expect(ruleForPattern({ recurrence_day: 20, recurrence_weekdays: null }, "weekly"))
      .toEqual({ recurrence_pattern: "weekly", recurrence_day: 4, recurrence_weekdays: null })
    expect(ruleForPattern({ recurrence_day: 15, recurrence_weekdays: null }, "last_business_day"))
      .toEqual({ recurrence_pattern: "last_business_day", recurrence_day: null, recurrence_weekdays: null })
  })

  it("toggles weekdays in order", () => {
    expect(toggleWeekday([3], 1)).toEqual([1, 3])
    expect(toggleWeekday([1, 3], 3)).toEqual([1])
  })
})
