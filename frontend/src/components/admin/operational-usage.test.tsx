import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import { OperationalUsagePanel } from "./operational-usage"

const get = vi.hoisted(() => vi.fn())
vi.mock("@/lib/api", () => ({ operationalUsageApi: { get } }))

const response = {
  as_of: "2026-09-21T12:00:00Z", window: { days: 30, start: "2026-08-22T12:00:00Z", end: "2026-09-21T12:00:00Z" },
  work_context: { total: 0, with_project: 0, without_project: 0, coverage_percent: null },
  work_planning: { total: 2, planned_or_waiting: 1, unplanned: 1, coverage_percent: 50 },
  incidents: { active: 1, snoozed: 2, dismissed: 3, resolved_in_window: 4 },
  dailys: { updates: 5, authors: 2, user_days: 4 },
  commands: { executed: 3, failed: 1, needs_input: 2, needs_review: 1, undone: 1, terminal_total: 4, success_percent: 75, by_channel: { app: 2, extension: 1, unknown: 0 } },
  deliveries: { sent: 0, failed: 0, uncertain: 0, expired: 0, cancelled: 0, pending: 1, sending: 0, terminal_total: 0, confirmation_percent: null },
}

function show(userId = 7) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter><OperationalUsagePanel userId={userId} /></MemoryRouter></QueryClientProvider>)
}

beforeEach(() => { get.mockReset(); get.mockResolvedValue(response) })

it("shows six bounded signals and never turns missing denominators into zero percent", async () => {
  show()
  expect(await screen.findByText("Trabajo con contexto")).toBeInTheDocument()
  expect(screen.getAllByText("Sin base suficiente")).toHaveLength(2)
  expect(screen.getByText("50 %")).toBeInTheDocument()
  expect(screen.getByText("5 actualizaciones")).toBeInTheDocument()
  expect(screen.queryByText(/cumplimiento/i)).not.toBeInTheDocument()
  expect(screen.getAllByRole("link", { name: "Abrir fuente" })).toHaveLength(6)
})

it("keeps stale data hidden after an error and retries explicitly", async () => {
  get.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(response)
  show()
  expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron cargar")
  expect(screen.queryByText("Trabajo con contexto")).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Reintentar" }))
  expect(await screen.findByText("Trabajo con contexto")).toBeInTheDocument()
})
