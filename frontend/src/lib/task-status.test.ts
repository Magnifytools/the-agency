import { describe, expect, it } from "vitest"
import { taskStatusFilterValue, taskStatusPresentation } from "./task-status"

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
})
