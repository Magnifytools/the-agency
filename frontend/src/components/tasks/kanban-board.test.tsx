import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import type { Task } from "@/lib/types"
import { KanbanBoard } from "./kanban-board"

const task: Task = {
  id: 7, title: "Preparar revisión", description: null, status: "pending", priority: "medium",
  estimated_minutes: null, actual_minutes: null, start_date: null, due_date: null, client_id: null,
  category_id: null, assigned_to: null, project_id: null, phase_id: null, is_inbox: false,
  depends_on: null, created_by: null, scheduled_date: null, waiting_for: null, follow_up_date: null,
  is_recurring: false, recurrence_pattern: null, recurrence_day: null, recurrence_end_date: null,
  recurring_parent_id: null, unit_cost: null, invoiced_at: null, link_url: null, created_at: "", updated_at: "",
  client_name: null, category_name: null, assigned_user_name: null, project_name: null, phase_name: null,
  dependency_title: null, created_by_name: null, recurring_parent_title: null, checklist_count: 0,
}

describe("KanbanBoard", () => {
  it("keeps cards readable but not draggable for readers", () => {
    render(<KanbanBoard tasks={[task]} onStatusChange={vi.fn()} onOpenEdit={vi.fn()} canWrite={false} />)
    expect(screen.getByText("Preparar revisión").closest("[draggable='false']")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Ver tarea Preparar revisión" })).toBeInTheDocument()
  })

  it("opens the waiting form with an explicit waiting intent instead of patching incomplete data", () => {
    const onStatusChange = vi.fn()
    const onOpenEdit = vi.fn()
    render(<KanbanBoard tasks={[task]} onStatusChange={onStatusChange} onOpenEdit={onOpenEdit} />)
    const card = screen.getByText("Preparar revisión").closest("[draggable='true']")!
    const waitingColumn = screen.getByText("En espera").closest("div.rounded-xl")!
    const dataTransfer = { effectAllowed: "", dropEffect: "", setData: vi.fn(), getData: vi.fn() }
    fireEvent.dragStart(card, { dataTransfer })
    fireEvent.dragOver(waitingColumn, { dataTransfer })
    fireEvent.drop(waitingColumn, { dataTransfer })
    expect(onOpenEdit).toHaveBeenCalledWith(task, "waiting")
    expect(onStatusChange).not.toHaveBeenCalled()
  })
})
