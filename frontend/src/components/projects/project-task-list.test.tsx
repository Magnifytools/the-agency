import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { ProjectTaskList, type ProjectTaskItem } from "./project-task-list"

const defaults = { priority: "medium" as const, assigned_user_name: null, scheduled_date: null, start_date: null, due_date: null, estimated_minutes: null, waiting_for: null, follow_up_date: null }
const tasks: ProjectTaskItem[] = [
  { ...defaults, id: 1, title: "Revisar propuesta", status: "pending", assigned_to: 7, assigned_user_name: "Persona de prueba" },
  { ...defaults, id: 2, title: "Preparar borrador", status: "completed", assigned_to: null },
]
const callbacks = () => ({ onStatusChange: vi.fn(), onOpen: vi.fn() })

describe("project task working list", () => {
  it("folds history while keeping it accessible for reopening", async () => {
    const actions = callbacks()
    render(<ProjectTaskList tasks={tasks} canWrite {...actions} />)
    expect(screen.getByRole("button", { name: "Abrir tarea: Revisar propuesta" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Reabrir: Preparar borrador" })).not.toBeVisible()
    await userEvent.click(screen.getByText("Completadas (1)"))
    await userEvent.click(screen.getByRole("button", { name: "Reabrir: Preparar borrador" }))
    expect(actions.onStatusChange).toHaveBeenCalledWith(2, "pending")
  })
  it("exposes completed search matches immediately", () => {
    render(<ProjectTaskList tasks={tasks} showCompleted canWrite {...callbacks()} />)
    expect(screen.getByRole("button", { name: "Reabrir: Preparar borrador" })).toBeInTheDocument()
    expect(screen.queryByText("Completadas (1)")).not.toBeInTheDocument()
  })
  it("supports keyboard opening with no mutation controls for a reader", async () => {
    const actions = callbacks()
    render(<ProjectTaskList tasks={tasks} canWrite={false} {...actions} />)
    expect(screen.queryByRole("button", { name: "Completar: Revisar propuesta" })).not.toBeInTheDocument()
    await userEvent.tab()
    await userEvent.keyboard("{Enter}")
    expect(actions.onOpen).toHaveBeenCalledWith(1)
    expect(actions.onStatusChange).not.toHaveBeenCalled()
  })
  it("disables the pending mutation and labels unassigned work explicitly", async () => {
    const actions = callbacks()
    render(<ProjectTaskList tasks={tasks} showCompleted canWrite pendingTaskId={1} {...actions} />)
    await userEvent.click(screen.getByRole("button", { name: "Completar: Revisar propuesta" }))
    expect(actions.onStatusChange).not.toHaveBeenCalled()
    expect(screen.getByText("Sin responsable")).toBeInTheDocument()
    expect(screen.getByText("Persona de prueba")).toBeInTheDocument()
    expect(screen.queryByText("7")).not.toBeInTheDocument()
  })
})
