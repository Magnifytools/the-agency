import { describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import type { PaginatedResponse, Task } from "@/lib/types"
import { MyDayView } from "./my-day-view"

const task = (id: number, title: string, overrides: Partial<Task> = {}): Task => ({
  id, title, description: null, status: "pending", priority: "medium", estimated_minutes: null,
  actual_minutes: null, start_date: null, due_date: null, client_id: null, category_id: null,
  assigned_to: 1, project_id: null, phase_id: null, is_inbox: false, depends_on: null,
  created_by: 1, scheduled_date: null, waiting_for: null, follow_up_date: null, is_recurring: false,
  recurrence_pattern: null, recurrence_day: null, recurrence_end_date: null, recurring_parent_id: null,
  unit_cost: null, invoiced_at: null, link_url: null, created_at: "2026-09-17T09:00:00Z",
  updated_at: "2026-09-17T09:00:00Z", client_name: null, category_name: null,
  assigned_user_name: null, project_name: null, phase_name: null, dependency_title: null,
  created_by_name: null, recurring_parent_title: null, checklist_count: 0, ...overrides,
})

const page = (items: Task[], total = items.length): PaginatedResponse<Task> => ({ items, total, page: 1, page_size: 25 })

describe("MyDayView", () => {
  it("separa el arrastre del compromiso de hoy y deja la carga adicional explícita", () => {
    const today = new Date()
    const old = new Date(today)
    old.setDate(today.getDate() - 2)
    const iso = (date: Date) => new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
    const onLoadMore = vi.fn()

    render(
      <MyDayView
        planned={page([task(1, "Para hoy", { scheduled_date: iso(today) })], 3)}
        carryover={page([task(2, "Arrastre", { scheduled_date: iso(old) })])}
        unplanned={page([])}
        completed={page([])}
        onLoadMore={onLoadMore}
        onStatusChange={vi.fn()}
        onOpenEdit={vi.fn()}
      />,
    )

    expect(screen.getByText("Planificadas hoy (3)")).toBeInTheDocument()
    expect(screen.getByText("Arrastre pendiente (1)")).toBeInTheDocument()
    expect(screen.getByText("No son compromisos nuevos de hoy. Reprograma, deja en espera o completa cada una.")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /Ver más planificadas/i }))
    expect(onLoadMore).toHaveBeenCalledWith("planned")
  })
})
