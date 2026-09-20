import { describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
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

    const onReviewCarryover = vi.fn()
    render(
      <MyDayView
        planned={page([task(1, "Para hoy", { scheduled_date: iso(today) })], 3)}
        carryover={page([task(2, "Arrastre", { scheduled_date: iso(old), due_date: iso(today) })])}
        unplanned={page([])}
        completed={page([])}
        retired={page([])}
        onLoadMore={onLoadMore}
        onStatusChange={vi.fn()}
        onOpenEdit={vi.fn()}
        onReviewCarryover={onReviewCarryover}
        canWrite
      />,
    )

    expect(screen.getByText("Planificadas hoy (3)")).toBeInTheDocument()
    expect(screen.getByText("Arrastre pendiente (1)")).toBeInTheDocument()
    expect(screen.getByText("No son compromisos nuevos de hoy. Reprograma, deja en espera o completa cada una.")).toBeInTheDocument()
    expect(screen.getAllByText(/Planificada/).length).toBeGreaterThan(0)
    expect(screen.getByText(/Fecha límite/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /Ver más planificadas/i }))
    expect(onLoadMore).toHaveBeenCalledWith("planned")
    fireEvent.click(screen.getByRole("button", { name: "Revisar" }))
    expect(onReviewCarryover).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }))
  })

  it("does not present carryover actions to a read-only user", () => {
    render(<MyDayView planned={page([])} carryover={page([task(2, "Arrastre")])} unplanned={page([])} completed={page([])} retired={page([])} onLoadMore={vi.fn()} onStatusChange={vi.fn()} onOpenEdit={vi.fn()} onReviewCarryover={vi.fn()} canWrite={false} />)
    expect(screen.queryByRole("button", { name: "Revisar" })).not.toBeInTheDocument()
    expect(screen.getByLabelText("Estado de Arrastre")).toBeDisabled()
  })

  it("sends reviewed work to review and opens the waiting form with its intended status", async () => {
    const onStatusChange = vi.fn()
    const onOpenEdit = vi.fn()
    const reviewed = task(5, "Revisar antes de cerrar", { project_requires_task_review: true, project_review_owner_id: 7 })
    render(<MyDayView planned={page([reviewed])} carryover={page([])} unplanned={page([])} completed={page([])} retired={page([])} onLoadMore={vi.fn()} onStatusChange={onStatusChange} onOpenEdit={onOpenEdit} onReviewCarryover={vi.fn()} canWrite canCompleteReviewedTask={() => false} />)
    await userEvent.selectOptions(screen.getByLabelText("Estado de Revisar antes de cerrar"), "completed")
    expect(onStatusChange).toHaveBeenCalledWith(5, "in_review")
    await userEvent.selectOptions(screen.getByLabelText("Estado de Revisar antes de cerrar"), "waiting")
    expect(onOpenEdit).toHaveBeenLastCalledWith(expect.objectContaining({ id: 5 }), "waiting")
  })

  it("distinguishes a retired-list error from an empty history and retries it", () => {
    const retry = vi.fn()
    render(<MyDayView planned={page([])} carryover={page([])} unplanned={page([])} completed={page([])} retired={page([])} onLoadMore={vi.fn()} onStatusChange={vi.fn()} onOpenEdit={vi.fn()} onReviewCarryover={vi.fn()} retiredError onRetryRetired={retry} />)
    fireEvent.click(screen.getByRole("button", { name: /Ver retiradas/i }))
    expect(screen.getByRole("alert")).toHaveTextContent("No se pudieron cargar")
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(retry).toHaveBeenCalledOnce()
  })

  it("keeps cached retired rows visible, formats their UTC instant in the business timezone, and opens them from the keyboard", async () => {
    const retry = vi.fn()
    const onOpenEdit = vi.fn()
    render(<MyDayView planned={page([])} carryover={page([])} unplanned={page([])} completed={page([])} retired={page([task(4, "Conservada", { retired_at: "2026-09-17T23:30:00Z", retired_reason: "Duplicada" })])} onLoadMore={vi.fn()} onStatusChange={vi.fn()} onOpenEdit={onOpenEdit} onReviewCarryover={vi.fn()} retiredError onRetryRetired={retry} />)
    fireEvent.click(screen.getByRole("button", { name: /Ver retiradas/i }))
    const retiredTask = screen.getByRole("button", { name: /Conservada/ })
    expect(retiredTask).toHaveTextContent("Retirada el 18 sept")
    retiredTask.focus()
    await userEvent.keyboard("{Enter}")
    expect(onOpenEdit).toHaveBeenCalledWith(expect.objectContaining({ id: 4 }))
    expect(screen.getByRole("alert")).toHaveTextContent("Mostramos retiradas guardadas")
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(retry).toHaveBeenCalledOnce()
  })
})
