import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AgendaSubtasks } from "./agenda-subtasks"

const mocks = vi.hoisted(() => ({ list: vi.fn(), update: vi.fn() }))
vi.mock("@/lib/api", () => ({
  tasksApi: { agendaSubtasks: mocks.list, checklist: { update: mocks.update } },
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const item = {
  id: 7, task_id: 3, text: "Revisar enlaces", description: null, is_done: false, order_index: 0,
  assigned_to: 1, due_date: "2026-10-27", assigned_user_name: "David", created_at: "", updated_at: "",
  task_title: "Informe de Fit", task_assignee_name: "Nacho", client_name: "Fit Generation",
}

function setup(canWrite = true) {
  const onOpenTask = vi.fn()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AgendaSubtasks today="2026-10-28" userId={1} canWrite={canWrite} onOpenTask={onOpenTask} />
    </QueryClientProvider>,
  )
  return onOpenTask
}

describe("AgendaSubtasks", () => {
  beforeEach(() => { mocks.list.mockReset(); mocks.update.mockReset() })

  it("lists my subtasks with their task and lets me tick them", async () => {
    mocks.list.mockResolvedValue([item])
    mocks.update.mockResolvedValue({ ...item, is_done: true })
    const onOpenTask = setup()
    expect(await screen.findByText("Revisar enlaces")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: /En «Informe de Fit» · Fit Generation · la lleva Nacho/ }))
    expect(onOpenTask).toHaveBeenCalledWith(3)
    await userEvent.click(screen.getByLabelText("Marcar como hecha: Revisar enlaces"))
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(3, 7, { is_done: true }))
    expect(mocks.list).toHaveBeenCalledWith("2026-10-28")
  })

  it("hides when there are none and without write access offers no checkbox", async () => {
    mocks.list.mockResolvedValue([])
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <AgendaSubtasks today="2026-10-28" userId={1} canWrite onOpenTask={vi.fn()} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(mocks.list).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it("shows the subtask read-only without write access", async () => {
    mocks.list.mockResolvedValue([item])
    setup(false)
    await screen.findByText("Revisar enlaces")
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument()
  })
})
