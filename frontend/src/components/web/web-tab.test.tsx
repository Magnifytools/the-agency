import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"
import { WebTab } from "./web-tab"

const api = vi.hoisted(() => ({
  targets: vi.fn(), createTarget: vi.fn(), updateTarget: vi.fn(), deleteTarget: vi.fn(), probe: vi.fn(),
}))
const perms = vi.hoisted(() => ({ write: true }))
vi.mock("@/lib/api", () => ({ webApi: api }))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ hasPermission: (module: string, write = false) => module === "web" && (!write || perms.write) }),
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const down = {
  id: 3, client_id: 7, url: "https://fit.es/", label: "Home", is_active: true, status: "down",
  status_since: "2026-10-21T08:01:00+00:00", last_checked_at: "2026-10-21T08:05:00+00:00",
  last_status_code: 503, last_error: "http_503", last_error_label: "error HTTP 503", last_response_ms: 120,
  uptime_24h: 97.5, uptime_30d: 99.91,
  open_outage: {
    id: 1, target_id: 3, kind: "down", started_at: "2026-10-21T08:00:00+00:00", confirmed_at: "2026-10-21T08:01:00+00:00",
    ended_at: null, duration_minutes: 5, cause: "http_503", cause_label: "error HTTP 503", status_code: 503,
    slack_down_status: "sent", slack_recovery_status: null,
  },
  recent_outages: [{
    id: 1, target_id: 3, kind: "down", started_at: "2026-10-21T08:00:00+00:00", confirmed_at: "2026-10-21T08:01:00+00:00",
    ended_at: null, duration_minutes: 5, cause: "http_503", cause_label: "error HTTP 503", status_code: 503,
    slack_down_status: "sent", slack_recovery_status: null,
  }],
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><WebTab clientId={7} website="https://fit.es" /></QueryClientProvider>)
}

beforeEach(() => {
  vi.resetAllMocks()
  perms.write = true
})

it("shows each URL with its state, uptime and the open outage", async () => {
  api.targets.mockResolvedValue({ enabled: true, monitored: true, website: "https://fit.es", targets: [down] })
  setup()
  const item = await screen.findByRole("listitem", { name: "Home" })
  expect(within(item).getByText("Caída")).toBeInTheDocument()
  expect(within(item).getByRole("alert")).toHaveTextContent(/No responde desde el .* \(error HTTP 503\)/)
  expect(within(item).getByText("97,5 %")).toBeInTheDocument()
  expect(within(item).getByText("99,91 %")).toBeInTheDocument()
  expect(within(item).getByText(/Últimas caídas \(1\)/)).toBeInTheDocument()
})

it("adds the first URL prefilled from the client's website", async () => {
  api.targets.mockResolvedValue({ enabled: true, monitored: true, website: "https://fit.es", targets: [] })
  api.createTarget.mockResolvedValue({ ...down, status: "unknown", open_outage: null, recent_outages: [] })
  setup()
  expect(await screen.findByText(/Todavía no vigilamos ninguna URL/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: /Añadir URL/ }))
  expect(screen.getByLabelText("URL a vigilar")).toHaveValue("https://fit.es")
  fireEvent.change(screen.getByLabelText("Nombre (opcional)"), { target: { value: "Home" } })
  fireEvent.click(screen.getByRole("button", { name: "Añadir" }))
  await waitFor(() => expect(api.createTarget).toHaveBeenCalledWith(7, { url: "https://fit.es", label: "Home" }))
})

it("probing now shows the result without touching the state", async () => {
  api.targets.mockResolvedValue({ enabled: true, monitored: true, website: null, targets: [down] })
  api.probe.mockResolvedValue({ target_id: 3, outcome: "up", cause: null, cause_label: null, status_code: 200, response_ms: 87, checked_at: "2026-10-21T08:06:00+00:00" })
  setup()
  fireEvent.click(await screen.findByRole("button", { name: /Probar ahora/ }))
  const status = await screen.findByRole("status")
  expect(status).toHaveTextContent("Ahora mismo: Responde · HTTP 200 · 87 ms (no cambia el estado)")
  expect(api.probe).toHaveBeenCalledWith(3)
})

it("readers see the state but no management buttons; disabled monitor is explained", async () => {
  perms.write = false
  api.targets.mockResolvedValue({ enabled: false, monitored: true, website: null, targets: [down] })
  setup()
  expect(await screen.findByText(/El monitor está apagado/)).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /Probar ahora/ })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: /Añadir URL/ })).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Borrar" })).not.toBeInTheDocument()
})

it("deleting asks first", async () => {
  api.targets.mockResolvedValue({ enabled: true, monitored: true, website: null, targets: [down] })
  api.deleteTarget.mockResolvedValue(undefined)
  setup()
  fireEvent.click(await screen.findByRole("button", { name: "Borrar" }))
  expect(api.deleteTarget).not.toHaveBeenCalled()
  const dialog = await screen.findByRole("dialog")
  fireEvent.click(within(dialog).getByRole("button", { name: "Borrar" }))
  await waitFor(() => expect(api.deleteTarget).toHaveBeenCalledWith(7, 3))
})
