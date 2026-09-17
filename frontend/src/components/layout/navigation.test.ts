import { describe, expect, it, vi } from "vitest"
import { activeArea, activeAreaLink, navigationFor } from "./navigation"
vi.mock("@/lib/hidden-modules", () => ({ isHidden: (name: string) => ["finance", "capacity", "my_week", "reports", "leads", "growth", "proposals", "vault", "discord", "automations"].includes(name) }))

describe("agency areas and permission boundaries", () => {
  it("gives five areas to an admin without exposing hidden modules", () => {
    const areas = navigationFor(() => true, true)
    expect(areas.map((area) => area.label)).toEqual(["Hoy", "Trabajo", "Clientes", "Resúmenes", "Ajustes"])
    expect(areas[0].links[0].to).toBe("/tasks?view=my_day")
    expect(areas.flatMap((area) => area.links).some((link) => link.to === "/finance")).toBe(false)
    expect(areas.find((area) => area.id === "settings")?.links.some((link) => link.to === "/users")).toBe(true)
    expect(areas.find((area) => area.id === "summaries")?.links.some((link) => link.to === "/users")).toBe(false)
  })
  it("keeps only authorized destinations and selects the first available work surface", () => {
    const areas = navigationFor((module) => module === "projects", false)
    expect(areas.map((area) => area.id)).toEqual(["work", "summaries", "settings"])
    expect(areas[0].links[0].to).toBe("/projects")
    expect(areas.flatMap((area) => area.links).some((link) => ["/users", "/clients", "/tasks?view=all", "/digests"].includes(link.to))).toBe(false)
  })
  it("distinguishes agenda from work while preserving legacy and QA task links", () => {
    expect(activeArea("/tasks", "?id=27")).toBe("today")
    expect(activeArea("/tasks", "?view=all")).toBe("work")
    expect(activeArea("/tasks", "?qaFilter=overdue")).toBe("work")
    expect(activeAreaLink("/tasks?view=my_day", "/tasks", "?view=weekly")).toBe(false)
    expect(activeAreaLink("/tasks?view=all", "/tasks", "?view=weekly")).toBe(true)
    expect(activeArea("/projects/17", "")).toBe("work")
    expect(activeArea("/digests/19/edit", "")).toBe("summaries")
    expect(activeArea("/users", "")).toBe("settings")
  })
})
