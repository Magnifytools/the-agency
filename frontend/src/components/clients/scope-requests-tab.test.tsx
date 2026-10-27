import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, it, vi } from "vitest"
import { ScopeRequestsTab } from "./scope-requests-tab"
import { formatScopeMinutes, parseEstimate } from "@/lib/scope-requests"

const mocks = vi.hoisted(() => ({
  list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), projects: vi.fn(),
  perms: { clientsWrite: true, projects: true },
}))
vi.mock("@/lib/scope-requests", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/scope-requests")>()),
  scopeRequestsApi: { list: mocks.list, create: mocks.create, update: mocks.update, delete: mocks.remove },
}))
vi.mock("@/lib/api", () => ({ projectsApi: { listAll: mocks.projects } }))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    hasPermission: (module: string, write = false) =>
      module === "clients" ? (write ? mocks.perms.clientsWrite : true) : module === "projects" ? mocks.perms.projects : false,
  }),
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const item = {
  id: 3, client_id: 7, project_id: 9, project_name: "SEO mensual", title: "Landing de Black Friday",
  detail: "Pedida por Slack", estimated_minutes: 90, requested_on: "2026-10-05", decision: "pending" as const,
  decision_note: null, decided_at: null, decided_by_name: null, created_at: "2026-10-05T09:00:00Z", created_by_name: "Nacho",
}
const listing = {
  month: "2026-10",
  totals: { absorbed_minutes: 30, billable_minutes: 120, swapped_minutes: 0, pending_minutes: 90, count: 3 },
  items: [item],
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><ScopeRequestsTab clientId={7} /></QueryClientProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.perms = { clientsWrite: true, projects: true }
  mocks.list.mockResolvedValue(listing)
  mocks.projects.mockResolvedValue([{ id: 9, name: "SEO mensual" }])
})

it("shows the month totals: absorbed, billable and pending", async () => {
  setup()
  const totals = await screen.findByLabelText("Total del mes")
  expect(within(totals).getByText("La asumimos").nextSibling).toHaveTextContent("30 min")
  expect(within(totals).getByText("A facturar").nextSibling).toHaveTextContent("2 h")
  expect(within(totals).getByText("Pendiente de decidir").nextSibling).toHaveTextContent("1 h 30 min")
  expect(screen.getByText("Landing de Black Friday")).toBeInTheDocument()
  expect(screen.getByText(/SEO mensual · apuntó Nacho/)).toBeInTheDocument()
})

it("logs a new request in minutes or hours", async () => {
  mocks.create.mockResolvedValue({ ...item, id: 4, requested_on: "2026-10-27" })
  setup()
  await screen.findByLabelText("Total del mes")
  await userEvent.type(screen.getByLabelText("Qué ha pedido"), "Informe extra")
  await userEvent.type(screen.getByLabelText("Coste estimado"), "2")
  await userEvent.selectOptions(screen.getByLabelText("Unidad"), "h")
  await screen.findByRole("option", { name: "SEO mensual" })
  await userEvent.selectOptions(screen.getByLabelText("Proyecto"), "9")
  await userEvent.click(screen.getByRole("button", { name: "Apuntar" }))
  await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(7, expect.objectContaining({
    title: "Informe extra", estimated_minutes: 120, project_id: 9, detail: null,
  })))
})

it("records the decision from the list", async () => {
  mocks.update.mockResolvedValue({ ...item, decision: "bill" })
  setup()
  await userEvent.selectOptions(await screen.findByLabelText("Decisión: Landing de Black Friday"), "bill")
  await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(7, 3, { decision: "bill" }))
})

it("a reader sees decisions but cannot log or decide", async () => {
  mocks.perms.clientsWrite = false
  mocks.list.mockResolvedValue({
    ...listing,
    items: [{ ...item, decision: "swap", decision_note: "A cambio del post de noviembre", decided_at: "2026-10-06T10:00:00Z", decided_by_name: "David" }],
  })
  setup()
  expect(await screen.findByText(/Decidió David .* A cambio del post de noviembre/)).toBeInTheDocument()
  // Una vez en los totales y otra como etiqueta de la decisión.
  expect(screen.getAllByText("A cambio de otra cosa")).toHaveLength(2)
  expect(screen.queryByRole("button", { name: "Apuntar" })).not.toBeInTheDocument()
  expect(screen.queryByLabelText(/Decisión:/)).not.toBeInTheDocument()
  expect(mocks.projects).not.toHaveBeenCalled()
})

it("parses and formats the estimate", () => {
  expect(parseEstimate("1,5", "h")).toBe(90)
  expect(parseEstimate("45", "min")).toBe(45)
  expect(parseEstimate("0", "min")).toBeNull()
  expect(parseEstimate("abc", "h")).toBeNull()
  expect(parseEstimate("1001", "h")).toBeNull()
  expect(formatScopeMinutes(45)).toBe("45 min")
  expect(formatScopeMinutes(120)).toBe("2 h")
  expect(formatScopeMinutes(95)).toBe("1 h 35 min")
})
