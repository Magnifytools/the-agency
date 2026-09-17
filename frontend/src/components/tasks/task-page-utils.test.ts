import { describe, expect, it } from "vitest"
import { initialTasksView, shouldPreserveCurrentProject, taskQueryKeyWithWeek, withExplicitActualMinutes } from "./task-page-utils"

describe("task page query and submit helpers", () => {
  it("opens Todas when a PM QA deep link carries a filter", () => {
    expect(initialTasksView(new URLSearchParams("qaFilter=unassigned"))).toBe("all")
    expect(initialTasksView(new URLSearchParams())).toBe("my_day")
  })

  it("changes the query key when the visible week changes", () => {
    const base = ["tasks", "weekly", 1]
    expect(taskQueryKeyWithWeek(base, { from: "2026-09-14", to: "2026-09-18" }))
      .not.toEqual(taskQueryKeyWithWeek(base, { from: "2026-09-21", to: "2026-09-25" }))
  })

  it("preserves actual minutes unless the field was explicitly edited", () => {
    const data = { title: "Solo cambio de título", priority: "medium" as const }
    expect(withExplicitActualMinutes(data, "60", false)).not.toHaveProperty("actual_minutes")
    expect(withExplicitActualMinutes(data, "60", true)).toMatchObject({ actual_minutes: 60 })
  })

  it("keeps the selected closed project available while editing", () => {
    expect(shouldPreserveCurrentProject(9, "9", [1, 2])).toBe(true)
    expect(shouldPreserveCurrentProject(9, "", [1, 2])).toBe(false)
    expect(shouldPreserveCurrentProject(9, "9", [1, 9])).toBe(false)
  })
})
