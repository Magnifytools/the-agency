import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { it, expect, vi } from "vitest"
import AutomationsPage from "./automations-page"

vi.mock("@/lib/api", () => ({ automationsApi: {
  list: vi.fn().mockResolvedValue([]),
  triggers: vi.fn().mockResolvedValue({ triggers: [], actions: [] }),
  logs: vi.fn().mockResolvedValue([
    { id: 1, rule_name: "Sin destino", trigger_event: "task_completed", outcome: "skipped", success: false, action_result: { reason: "No webhook_url configured" }, executed_at: "2026-09-17T00:00:00" },
    { id: 2, rule_name: "Rechazada", trigger_event: "task_completed", outcome: "error", success: false, error_message: "La acción no se completó correctamente", executed_at: "2026-09-17T00:00:00" },
    { id: 3, rule_name: "Realizada", trigger_event: "task_completed", outcome: "success", success: true, executed_at: "2026-09-17T00:00:00" },
  ]),
} }))

it("distinguishes skipped, failed and completed actions with visible reasons", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><AutomationsPage /></QueryClientProvider>)
  await userEvent.click(screen.getByRole("button", { name: /Historial/ }))
  expect(await screen.findByText("Omitida")).toBeInTheDocument()
  expect(screen.getByText("Fallida")).toBeInTheDocument()
  expect(screen.getByText("Completada")).toBeInTheDocument()
  expect(screen.getByText("No webhook_url configured")).toBeInTheDocument()
  expect(screen.getByText("La acción no se completó correctamente")).toBeInTheDocument()
})
