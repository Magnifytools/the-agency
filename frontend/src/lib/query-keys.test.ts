import { QueryClient } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"
import {
  clientKeys,
  invalidateTaskChange,
  optimisticallyUpdateExactQuery,
  projectKeys,
  restoreQuerySnapshot,
  taskKeys,
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
      ["unrelated", "settings"] as const,
    ]
    keys.forEach((key) => client.setQueryData(key, { ok: true }))

    await invalidateTaskChange(client, { projectId: 21, clientId: 4 })

    for (const key of keys.slice(0, 7)) {
      expect(client.getQueryState(key)?.isInvalidated).toBe(true)
    }
    expect(client.getQueryState(keys[7])?.isInvalidated).toBe(false)
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
})
