import { describe, expect, it } from "vitest"
import type { Task } from "@/lib/types"
import { patchCachedTask } from "./use-task-quick-update"

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
