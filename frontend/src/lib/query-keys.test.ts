import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"
import { incidentKeys } from "./incidents-api"
import {
  clientKeys,
  dashboardKeys,
  briefingKeys,
  invalidateTaskChange,
  optimisticallyUpdateExactQuery,
  projectKeys,
  restoreQuerySnapshot,
  taskKeys,
  myWeekKeys,
  inboxKeys,
  searchKeys,
} from "./query-keys"

describe("shared operational query keys", () => {
  it("invalidates task surfaces and project counters while preserving unrelated cache", async () => {
    const client = new QueryClient()
    const keys = [
      taskKeys.list(["search", "month", 3]),
      taskKeys.agenda("planned", "2026-09-17", 7, -480),
      taskKeys.project(21),
      taskKeys.assigned("timer", 7, "2026-09-17"),
      projectKeys.detail(21),
      projectKeys.client(4),
      clientKeys.summary(4),
      clientKeys.summary(5),
      projectKeys.detail(22),
      dashboardKeys.today(),
      myWeekKeys.week("2026-09-14"),
      [...briefingKeys.all(), "mine"],
      incidentKeys.count(7),
      incidentKeys.list(7, "active"),
      searchKeys.results(7, "tasks", "reunión"),
      ["unrelated", "settings"] as const,
    ]
    keys.forEach((key) => client.setQueryData(key, { ok: true }))

    await invalidateTaskChange(client, {
      projectId: 21,
      previousProjectId: 22,
      clientId: 4,
      previousClientId: 5,
    })

    for (const key of keys.slice(0, -1)) {
      expect(client.getQueryState(key)?.isInvalidated).toBe(true)
    }
    expect(client.getQueryState(keys.at(-1)!)?.isInvalidated).toBe(false)
  })

  it("updates and rolls back only the exact filtered drag query", async () => {
    const client = new QueryClient()
    const draggedKey = taskKeys.list(["client:4", "search:seo", "2026-09", "user:7", "weekly", "2026-09-14", "2026-09-18"])
    const siblingKey = taskKeys.list(["client:4", "search:seo", "2026-10", "user:7", "calendar"])
    const original = { items: [{ id: 9, scheduled_date: "2026-09-15" }], total: 1 }
    const sibling = { items: [{ id: 9, scheduled_date: "2026-10-02" }], total: 1 }
    client.setQueryData(draggedKey, original)
    client.setQueryData(siblingKey, sibling)
    const cancelSpy = vi.spyOn(client, "cancelQueries")

    const snapshot = await optimisticallyUpdateExactQuery<typeof original>(client, draggedKey, (old) => old && ({
      ...old,
      items: old.items.map((task) => task.id === 9 ? { ...task, scheduled_date: "2026-09-17" } : task),
    }))

    expect(cancelSpy).toHaveBeenCalledWith({ queryKey: draggedKey, exact: true })
    expect(client.getQueryData<typeof original>(draggedKey)?.items[0].scheduled_date).toBe("2026-09-17")
    expect(client.getQueryData(siblingKey)).toEqual(sibling)

    restoreQuerySnapshot(client, snapshot)
    expect(client.getQueryData(draggedKey)).toEqual(original)
    expect(client.getQueryData(siblingKey)).toEqual(sibling)
  })

  it("does not share Inbox data between authenticated users", () => {
    expect(inboxKeys.list(7, "pending,classified")).not.toEqual(inboxKeys.list(8, "pending,classified"))
    expect(inboxKeys.count(7)).not.toEqual(inboxKeys.count(8))
  })

  it("keeps an Inbox preview distinct from the paginated list cache", () => {
    expect(inboxKeys.preview(7, "pending,classified", 5)).not.toEqual(inboxKeys.list(7, "pending,classified", 50))
  })

  it("keeps dashboard data distinct across identities, permissions, and months", () => {
    expect(dashboardKeys.overview(2026, 9, 7, "member:tasks:1")).not.toEqual(dashboardKeys.overview(2026, 9, 8, "member:tasks:1"))
    expect(dashboardKeys.overview(2026, 9, 7, "member:tasks:1")).not.toEqual(dashboardKeys.overview(2026, 9, 7, "member:tasks:0"))
    expect(dashboardKeys.overview(2026, 9, 7, "member:tasks:1")).not.toEqual(dashboardKeys.overview(2026, 8, 7, "member:tasks:1"))
  })

  it("does not share search results across identities or permission sets", () => {
    expect(searchKeys.results(7, "tasks", "reunión")).not.toEqual(searchKeys.results(8, "tasks", "reunión"))
    expect(searchKeys.results(7, "tasks", "reunión")).not.toEqual(searchKeys.results(7, "clients,tasks", "reunión"))
  })
})
