import { describe, expect, it } from "vitest"
import { plannedStartNotice, taskStatusFilterValue, taskStatusPresentation, taskStatusSelectClass } from "./task-status"

describe("task status presentation", () => {
  it("groups legacy backlog and advanced without changing their meaning", () => {
    expect(taskStatusPresentation("backlog", null)).toEqual({
      group: "pending",
      label: "Pendiente",
      detail: "Sin planificar",
    })
    expect(taskStatusPresentation("backlog", "2026-09-21").detail).toBe("Backlog con fecha (revisar)")
    expect(taskStatusPresentation("advanced")).toEqual({
      group: "in_progress",
      label: "En curso",
      detail: "Avance registrado",
    })
  })

  it("keeps grouped filters backed by the raw API enum values", () => {
    expect(taskStatusFilterValue("pending")).toBe("pending,backlog")
    expect(taskStatusFilterValue("in_progress")).toBe("in_progress,advanced")
  })

  it("marks every status selector for the native-menu contrast treatment", () => {
    for (const status of ["pending", "in_progress", "waiting", "in_review", "completed"] as const) {
      expect(taskStatusSelectClass(status)).toContain("task-status-select")
    }
  })
})

describe("plannedStartNotice (gemelo de apply_planned_start)", () => {
  const today = "2026-11-18"

  it("avisa de que una pendiente con la fecha llegada pasa a En curso", () => {
    expect(plannedStartNotice({ status: "pending", scheduled_date: today }, null, today)).toMatch(/En curso/)
    expect(plannedStartNotice(
      { status: "pending", scheduled_date: "2026-11-10" },
      { status: "pending", scheduled_date: null },
      today,
    )).toMatch(/En curso/)
  })

  it("avisa de que elegir Pendiente quita la fecha", () => {
    expect(plannedStartNotice(
      { status: "pending", scheduled_date: today },
      { status: "in_progress", scheduled_date: today },
      today,
    )).toMatch(/quita la fecha/)
  })

  it("calla con fecha futura, otro estado, plantilla o nada cambiado", () => {
    expect(plannedStartNotice({ status: "pending", scheduled_date: "2026-11-19" }, null, today)).toBeNull()
    expect(plannedStartNotice({ status: "in_progress", scheduled_date: today }, null, today)).toBeNull()
    expect(plannedStartNotice({ status: "pending", scheduled_date: today, is_recurring: true }, null, today)).toBeNull()
    expect(plannedStartNotice(
      { status: "backlog", scheduled_date: "2026-05-01" },
      { status: "backlog", scheduled_date: "2026-05-01" },
      today,
    )).toBeNull()
  })
})
