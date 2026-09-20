import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import { InsightsPanel } from "./insights-panel"

const api = vi.hoisted(() => ({ list: vi.fn(), decide: vi.fn() }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ user: { id: 7 } }) }))
vi.mock("@/lib/incidents-api", async (original) => ({ ...await original<object>(), incidentsApi: api }))

beforeEach(() => {
  vi.clearAllMocks()
  api.list.mockResolvedValue({ items: [{
    id: 7, revision: 1, title: "Revisar entrega", message: "Pendiente",
    condition_type: "task_overdue", state: "active", severity: "warning",
    href: "/tasks?task=12", entity_type: "task", entity_key: "12",
    created_at: "2026-09-20T10:00:00Z",
  }], next_cursor: null })
})

it("opens the shared operational source without treating navigation as a decision", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter>
    <Routes><Route path="/" element={<InsightsPanel />} />
      <Route path="/tasks" element={<p>Detalle de tarea</p>} />
    </Routes>
  </MemoryRouter></QueryClientProvider>)
  await userEvent.click(await screen.findByRole("link", { name: /Revisar entrega/ }))
  expect(await screen.findByText("Detalle de tarea")).toBeInTheDocument()
  expect(api.list).toHaveBeenCalledWith({ state: "active", cursor: undefined, limit: 5 })
  expect(api.decide).not.toHaveBeenCalled()
  expect(screen.queryByText("Generar insights")).not.toBeInTheDocument()
})
