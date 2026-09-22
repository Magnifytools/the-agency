import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { ProjectWorkSummary } from "./project-work-summary"
import { projectWork, type ProjectTaskItem } from "@/lib/project-work"

const task = (id: number, patch: Partial<ProjectTaskItem> = {}): ProjectTaskItem => ({
  id, title: `Acción ${id}`, status: "pending", priority: "medium", assigned_to: null,
  assigned_user_name: null, scheduled_date: null, start_date: null, due_date: null,
  estimated_minutes: null, waiting_for: null, follow_up_date: null, ...patch,
})

describe("project next action and follow-up", () => {
  it("does not hide overdue commitments behind future plans or completed work", () => {
    const tasks = [task(1, { scheduled_date: "2026-10-01" }), task(2, { scheduled_date: "2026-09-18", due_date: "2026-09-15T00:00:00Z" }), task(3, { scheduled_date: "2026-01-01", status: "completed" })]
    expect(projectWork(tasks).next?.id).toBe(2)
  })
  it("orders ties by explicit priority and retains commitments beyond first25", () => {
    const tasks = Array.from({ length: 30 }, (_, index) => task(index + 1, { scheduled_date: "2026-09-18" }))
    tasks.push(task(31, { scheduled_date: "2026-09-18", priority: "urgent" }))
    expect(projectWork(tasks).next?.id).toBe(31)
  })
  it("keeps waiting and backlog out of planned action without inventing dates", () => {
    const tasks = [task(1, { status: "waiting", scheduled_date: "2026-01-01" }), task(2, { status: "backlog", scheduled_date: "2026-01-01" }), task(3)]
    expect(projectWork(tasks)).toMatchObject({ next: null, waiting: [tasks[0]], unplanned: 1 })
    expect(tasks[2].scheduled_date).toBeNull()
  })
  it("opens the next action and marks old planning for deliberate review", async () => {
    const onOpen = vi.fn()
    render(<ProjectWorkSummary tasks={[task(8, { scheduled_date: "2026-09-16", assigned_user_name: "Persona local" })]} today="2026-09-17" canWrite onOpen={onOpen} onAdd={vi.fn()} />)
    await userEvent.click(screen.getByRole("button", { name: /Acción 8.*Atrasada/ }))
    expect(onOpen).toHaveBeenCalledWith(8)
  })
  it("describes unplanned tasks as consultation for a reader", () => {
    render(<ProjectWorkSummary tasks={[task(9)]} today="2026-09-17" canWrite={false} onOpen={vi.fn()} onAdd={vi.fn()} />)
    expect(screen.getByText(/Hay 1 tarea sin planificar\. Puedes consultar su detalle en la lista\./)).toBeInTheDocument()
    expect(screen.queryByText(/concretar el siguiente paso/)).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Añadir una acción" })).not.toBeInTheDocument()
  })
  it("shows all waits and opens missing follow-ups without fabricating a deadline", async () => {
    const onOpen = vi.fn()
    render(<ProjectWorkSummary tasks={[task(1, { status: "waiting", waiting_for: "Material", follow_up_date: "2026-09-17" }), task(2, { status: "waiting" })]} today="2026-09-17" canWrite={false} onOpen={onOpen} onAdd={vi.fn()} />)
    expect(screen.queryByRole("button", { name: "Añadir una acción" })).not.toBeInTheDocument()
    await userEvent.click(screen.getByText("En espera (2) · 1 por revisar"))
    await userEvent.click(screen.getByRole("button", { name: /Acción 2.*Sin fecha de revisión/ }))
    expect(onOpen).toHaveBeenCalledWith(2)
    expect(screen.getByText(/Esperando a Material/)).toBeVisible()
  })
})
