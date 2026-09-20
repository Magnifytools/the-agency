import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, it, vi } from "vitest"
import { CarryoverReviewDialog } from "./carryover-review-dialog"

const api = vi.hoisted(() => ({ carryoverDecision: vi.fn(), get: vi.fn() }))
vi.mock("@/lib/api", () => ({ tasksApi: api }))
vi.mock("@/lib/query-keys", () => ({ taskKeys: { detail: (id: number) => ["task", id] }, invalidateTaskChange: vi.fn() }))

const task = { id: 8, title: "Entrega vencida", updated_at: "2026-09-20T10:00:00Z", due_date: "2026-09-18T00:00:00Z", project_id: null, client_id: null }
function show() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><CarryoverReviewDialog task={task as never} open onOpenChange={vi.fn()} /></QueryClientProvider>)
}
beforeEach(() => { vi.clearAllMocks(); api.carryoverDecision.mockResolvedValue(task) })

it("reprograms explicitly without changing the due date", async () => {
  show()
  await userEvent.type(screen.getByLabelText("Nueva fecha"), "2026-09-23")
  await userEvent.click(screen.getByRole("button", { name: "Guardar decisión" }))
  await waitFor(() => expect(api.carryoverDecision).toHaveBeenCalledWith(8, expect.objectContaining({ action: "reschedule", scheduled_date: "2026-09-23", expected_updated_at: task.updated_at })))
  expect(api.carryoverDecision.mock.calls[0][1]).not.toHaveProperty("due_date")
  expect(screen.getByText(/Se conserva aunque reprogrames/)).toBeInTheDocument()
})

it("preserves the decision inputs across a conflict until it is explicitly reviewed", async () => {
  api.carryoverDecision.mockRejectedValueOnce({ isAxiosError: true, response: { status: 409 } })
  api.get.mockResolvedValue({ ...task, updated_at: "2026-09-20T11:00:00Z" })
  show()
  await userEvent.click(screen.getByRole("button", { name: "Esperar" }))
  await userEvent.type(screen.getByLabelText("Esperando a"), "Cliente")
  await userEvent.type(screen.getByLabelText("Revisar el"), "2026-09-25")
  await userEvent.click(screen.getByRole("button", { name: "Guardar decisión" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("cambió en otro sitio")
  expect(screen.getByLabelText("Esperando a")).toHaveValue("Cliente")
  expect(screen.getByRole("button", { name: "Guardar decisión" })).toBeDisabled()
  await userEvent.click(screen.getByRole("button", { name: "Continuar con mi decisión" }))
  expect(screen.getByRole("button", { name: "Guardar decisión" })).not.toBeDisabled()
})


it("does not carry a conflicted decision into another task", async () => {
  const secondTask = { ...task, id: 9, title: "Otra tarea", updated_at: "2026-09-20T12:00:00Z" }
  api.carryoverDecision.mockRejectedValueOnce({ isAxiosError: true, response: { status: 409, data: { detail: "Hay un temporizador activo" } } })
  api.get.mockResolvedValue({ ...task, updated_at: "2026-09-20T11:00:00Z" })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const view = render(<QueryClientProvider client={client}><CarryoverReviewDialog key={task.id} task={task as never} open onOpenChange={vi.fn()} /></QueryClientProvider>)
  await userEvent.click(screen.getByRole("button", { name: "Esperar" }))
  await userEvent.type(screen.getByLabelText("Esperando a"), "Respuesta de A")
  await userEvent.type(screen.getByLabelText("Revisar el"), "2026-09-25")
  await userEvent.click(screen.getByRole("button", { name: "Guardar decisión" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("La tarea cambió en otro sitio")

  view.rerender(<QueryClientProvider client={client}><CarryoverReviewDialog key={secondTask.id} task={secondTask as never} open onOpenChange={vi.fn()} /></QueryClientProvider>)
  expect(screen.getByText("Otra tarea")).toBeInTheDocument()
  expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  expect(screen.getByLabelText("Nueva fecha")).toHaveValue("")
  await userEvent.type(screen.getByLabelText("Nueva fecha"), "2026-09-26")
  await userEvent.click(screen.getByRole("button", { name: "Guardar decisión" }))
  await waitFor(() => expect(api.carryoverDecision).toHaveBeenLastCalledWith(9, expect.objectContaining({ expected_updated_at: secondTask.updated_at })))
})
