import { createElement, type ReactNode } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import type { Task } from "@/lib/types"
import { patchCachedTask, useTaskMove } from "./use-task-quick-update"

const api = vi.hoisted(() => ({ move: vi.fn() }))
vi.mock("@/lib/api", () => ({ tasksApi: { move: api.move }, changesApi: {} }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const task = (id: number, priority: Task["priority"] = "medium") => ({ id, title: `T${id}`, priority }) as Task

describe("patchCachedTask", () => {
  it("cambia la tarea en listas paginadas, agenda infinita y ficha", () => {
    const paginated = { items: [task(1), task(2)], total: 2 }
    expect((patchCachedTask(paginated, 2, { priority: "high" }) as typeof paginated).items[1].priority).toBe("high")

    const infinite = { pages: [{ items: [task(1)] }, { items: [task(2)] }], pageParams: [1, 2] }
    const patched = patchCachedTask(infinite, 2, { priority: "urgent" }) as typeof infinite
    expect(patched.pages[0]).toBe(infinite.pages[0])
    expect(patched.pages[1].items[0].priority).toBe("urgent")

    expect((patchCachedTask(task(3), 3, { priority: "low" }) as Task).priority).toBe("low")
  })

  it("deja intacto (misma referencia) lo que no contiene la tarea", () => {
    const paginated = { items: [task(1)] }
    expect(patchCachedTask(paginated, 9, { priority: "high" })).toBe(paginated)
    expect(patchCachedTask(task(1), 9, { priority: "high" })).toEqual(task(1))
    expect(patchCachedTask(undefined, 1, {})).toBeUndefined()
  })
})

describe("useTaskMove", () => {
  it("pinta al momento el orden y el estado que pondrá el servidor", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const key = ["tasks", "list", "tablero"]
    const items = [
      { id: 1, title: "A", status: "pending", sort_rank: "F" },
      { id: 2, title: "B", status: "pending", sort_rank: "V" },
      { id: 3, title: "C", status: "in_progress", sort_rank: null },
    ] as Task[]
    client.setQueryData(key, { items, total: 3 })
    api.move.mockReturnValue(new Promise(() => {}))
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children)
    const { result } = renderHook(() => useTaskMove(), { wrapper })

    // C pasa de "En curso" a "Pendiente", entre A y B.
    act(() => result.current.mutate({ task: items[2], ordered: [items[0], items[2], items[1]], status: "pending" }))
    await waitFor(() => expect(api.move).toHaveBeenCalledWith(3, { ordered_ids: [1, 3, 2], status: "pending" }))
    const moved = (client.getQueryData(key) as { items: Task[] }).items.find((item) => item.id === 3)!
    expect(moved.status).toBe("pending")
    expect(moved.sort_rank).toBe("N")
  })
})
