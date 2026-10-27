import { describe, expect, it } from "vitest"
import { boardStatusQuery, calendarMonthFrom, calendarMonthParam, initialTasksView, lastTasksView, mondayOf, rememberTasksView, selectedTaskAssignee, shiftCalendarMonth, shouldPreserveCurrentProject, taskQueryKeyWithWeek, weekOffsetFrom, weekParam, withExplicitActualMinutes, withTaskAssignee } from "./task-page-utils"

describe("task page query and submit helpers", () => {
  it("opens Todas when a PM QA deep link carries a filter", () => {
    expect(initialTasksView(new URLSearchParams("qaFilter=unassigned"))).toBe("all")
    expect(initialTasksView(new URLSearchParams())).toBe("my_day")
    expect(initialTasksView(new URLSearchParams("view=all"))).toBe("all")
    expect(initialTasksView(new URLSearchParams("view=weekly"))).toBe("weekly")
    expect(initialTasksView(new URLSearchParams("view=unknown"))).toBe("my_day")
    expect(initialTasksView(new URLSearchParams("view=my_day&qaFilter=overdue"))).toBe("all")
  })

  it("changes the query key when the visible week changes", () => {
    const base = ["tasks", "weekly", 1]
    expect(taskQueryKeyWithWeek(base, { from: "2026-09-14", to: "2026-09-18" }))
      .not.toEqual(taskQueryKeyWithWeek(base, { from: "2026-09-21", to: "2026-09-25" }))
  })

  it("opens a person's tasks and lets members return explicitly to all assignees", () => {
    expect(selectedTaskAssignee(new URLSearchParams("assigned=9"), 2, false)).toBe("9")
    expect(selectedTaskAssignee(new URLSearchParams(), 2, false)).toBe("2")
    const all = withTaskAssignee(new URLSearchParams("view=all&assigned=9"), "", false)
    expect(all.toString()).toBe("view=all&assigned=all")
    expect(selectedTaskAssignee(all, 2, false)).toBe("")
    expect(withTaskAssignee(all, "", true).toString()).toBe("view=all")
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

describe("task views kept in the URL", () => {
  it("resolves the menu link to the last task view and falls back to the list", () => {
    window.localStorage.removeItem("agency.tasks.lastView")
    expect(initialTasksView(new URLSearchParams("view=tareas"))).toBe("all")
    rememberTasksView("sprint")
    expect(initialTasksView(new URLSearchParams("view=tareas"))).toBe("sprint")
    rememberTasksView("my_day")
    expect(lastTasksView()).toBe("sprint")
    window.localStorage.setItem("agency.tasks.lastView", "my_day")
    expect(lastTasksView()).toBe("all")
  })

  it("reads and writes the visible month", () => {
    expect(calendarMonthFrom("2026-03", "2026-10-27")).toEqual({ year: 2026, month: 2 })
    expect(calendarMonthFrom("2026-13", "2026-10-27")).toEqual({ year: 2026, month: 9 })
    expect(calendarMonthFrom(null, "2026-10-27")).toEqual({ year: 2026, month: 9 })
    expect(calendarMonthParam(shiftCalendarMonth({ year: 2026, month: 0 }, -1))).toBe("2025-12")
    expect(calendarMonthParam(shiftCalendarMonth({ year: 2026, month: 11 }, 1))).toBe("2027-01")
  })

  it("stores the visible week as its Monday and reads it back as an offset", () => {
    expect(mondayOf("2026-11-01")).toBe("2026-10-26")
    expect(weekParam(1, "2026-10-27")).toBe("2026-11-02")
    expect(weekOffsetFrom("2026-11-04", "2026-10-27")).toBe(1)
    expect(weekOffsetFrom("2026-10-12", "2026-10-27")).toBe(-2)
    expect(weekOffsetFrom("basura", "2026-10-27")).toBe(0)
    expect(weekOffsetFrom(null, "2026-10-27")).toBe(0)
  })

  it("splits the board into active columns and the recent Hecho column", () => {
    const active = "backlog,pending,in_progress,advanced,waiting,in_review"
    expect(boardStatusQuery(active, active)).toEqual({ active, completed: true })
    expect(boardStatusQuery("", active)).toEqual({ active, completed: true })
    expect(boardStatusQuery("waiting", active)).toEqual({ active: "waiting", completed: false })
    expect(boardStatusQuery("completed", active)).toEqual({ active: null, completed: true })
  })
})
