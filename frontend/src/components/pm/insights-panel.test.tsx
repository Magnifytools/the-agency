import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { InsightsPanel } from "./insights-panel"

const api = vi.hoisted(() => ({ insights: vi.fn(), actOnInsight: vi.fn() }))
vi.mock("@/lib/api", () => ({ pmApi: api }))
vi.mock("./alert-settings-dialog", () => ({ AlertSettingsButton: () => null }))

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter>
    <Routes><Route path="/" element={<InsightsPanel />} />
      <Route path="/tasks" element={<p>Detalle de tarea</p>} />
    </Routes>
  </MemoryRouter></QueryClientProvider>)
}

describe("acciones de insights", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.insights.mockResolvedValue([{
      id: 7, title: "Revisar entrega", description: "Pendiente", insight_type: "deadline",
      priority: "high", task_id: 12, suggested_action: "Abrir tarea",
    }])
    api.actOnInsight.mockResolvedValue({})
  })

  it("navegar al detalle no marca la incidencia como actuada", async () => {
    show()
    await userEvent.click(await screen.findByRole("link", { name: /Revisar entrega/ }))
    expect(await screen.findByText("Detalle de tarea")).toBeInTheDocument()
    await new Promise(resolve => setTimeout(resolve, 350))
    expect(api.actOnInsight).not.toHaveBeenCalled()
  })

  it("mantiene la acción explícita de marcar como actuado", async () => {
    show()
    await userEvent.click(await screen.findByTitle("Marcar como actuado"))
    await waitFor(() => expect(api.actOnInsight).toHaveBeenCalledWith(7))
  })
})
