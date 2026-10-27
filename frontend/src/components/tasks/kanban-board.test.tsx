import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import type { Task } from "@/lib/types"
import { KanbanBoard } from "./kanban-board"
import { boardDrop } from "./board-drop"

const task: Task = {
  id: 7, title: "Preparar revisión", description: null, status: "pending", priority: "medium",
  estimated_minutes: null, actual_minutes: null, start_date: null, due_date: null, client_id: null,
  category_id: null, assigned_to: null, project_id: null, phase_id: null, is_inbox: false,
  depends_on: null, created_by: null, scheduled_date: null, waiting_for: null, follow_up_date: null,
  is_recurring: false, recurrence_pattern: null, recurrence_day: null, recurrence_end_date: null,
  recurring_parent_id: null, link_url: null, created_at: "", updated_at: "",
  client_name: null, category_name: null, assigned_user_name: null, project_name: null, phase_name: null,
  dependency_title: null, created_by_name: null, recurring_parent_title: null, checklist_count: 0,
}

describe("KanbanBoard", () => {
  it("keeps cards readable but not draggable for readers", () => {
    render(<KanbanBoard tasks={[task]} onMove={vi.fn()} onOpenEdit={vi.fn()} canWrite={false} />)
    const card = screen.getByText("Preparar revisión").closest("[data-task-card]")!
    expect(card).not.toHaveAttribute("aria-roledescription")
    expect(screen.getByRole("button", { name: "Ver tarea Preparar revisión" })).toBeInTheDocument()
  })

  it("makes writer cards draggable", () => {
    render(<KanbanBoard tasks={[task]} onMove={vi.fn()} onOpenEdit={vi.fn()} />)
    expect(screen.getByText("Preparar revisión").closest("[data-task-card]")).toHaveAttribute("aria-roledescription", "sortable")
  })

  it("opens the task from its title", async () => {
    const onOpenEdit = vi.fn()
    render(<KanbanBoard tasks={[task]} onMove={vi.fn()} onOpenEdit={onOpenEdit} />)
    await userEvent.click(screen.getByRole("button", { name: "Preparar revisión" }))
    expect(onOpenEdit).toHaveBeenCalledWith(task)
  })

  it("shows recent completed work in a collapsed Hecho column only when asked", async () => {
    const done = { ...task, id: 8, title: "Informe enviado", status: "completed" as const }
    const { rerender } = render(<KanbanBoard tasks={[task, done]} onMove={vi.fn()} onOpenEdit={vi.fn()} />)
    expect(screen.queryByRole("region", { name: "Columna Hecho" })).not.toBeInTheDocument()

    rerender(<KanbanBoard tasks={[task, done]} onMove={vi.fn()} onOpenEdit={vi.fn()} showCompleted completedHint="últimos 7 días" />)
    const column = screen.getByRole("region", { name: "Columna Hecho" })
    expect(within(column).getByText("1")).toBeInTheDocument()
    expect(within(column).getByText("últimos 7 días")).toBeInTheDocument()
    expect(within(column).queryByText("Informe enviado")).not.toBeInTheDocument()
    await userEvent.click(within(column).getByRole("button", { name: /Mostrar/ }))
    expect(within(column).getByText("Informe enviado")).toBeInTheDocument()
  })
})

describe("boardDrop", () => {
  it("opens the waiting form instead of patching incomplete data", () => {
    expect(boardDrop(task, "waiting")).toEqual({ kind: "waiting" })
  })

  it("ignores a drop on the column the task is already in, by status group", () => {
    expect(boardDrop({ ...task, status: "backlog" }, "pending")).toEqual({ kind: "none" })
    expect(boardDrop({ ...task, status: "advanced" }, "in_progress")).toEqual({ kind: "none" })
  })

  it("moves to the target status, including closing and reopening", () => {
    expect(boardDrop(task, "completed")).toEqual({ kind: "status", status: "completed" })
    expect(boardDrop({ ...task, status: "completed" }, "pending")).toEqual({ kind: "status", status: "pending" })
  })
})
