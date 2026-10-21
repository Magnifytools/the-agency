import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import WebPage from "./web-page"

const api = vi.hoisted(() => ({ overview: vi.fn() }))
vi.mock("@/lib/api", () => ({ webApi: api }))

const target = (over: Record<string, unknown>) => ({
  id: 1, client_id: 1, url: "https://a.es/", label: null, is_active: true, status: "up",
  status_since: null, last_checked_at: "2026-10-21T08:00:00+00:00", last_status_code: 200, last_error: null,
  last_error_label: null, last_response_ms: 90, uptime_24h: 100, uptime_30d: 99.5, open_outage: null, recent_outages: [],
  ...over,
})

const overview = {
  enabled: true,
  interval_seconds: 300,
  clients: [
    { client_id: 2, client_name: "Caída SL", website: null, status: "down", targets: [target({
      id: 2, client_id: 2, url: "https://caida.es/", status: "down", uptime_24h: 80,
      open_outage: { id: 9, target_id: 2, kind: "down", started_at: "2026-10-21T07:00:00+00:00", confirmed_at: "2026-10-21T07:01:00+00:00",
        ended_at: null, duration_minutes: 60, cause: "timeout", cause_label: "no responde a tiempo", status_code: null,
        slack_down_status: "sent", slack_recovery_status: null },
    })] },
    { client_id: 1, client_name: "Bien SA", website: null, status: "up", targets: [target({})] },
    { client_id: 3, client_name: "Nueva", website: "https://nueva.es", status: null, targets: [] },
  ],
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter><WebPage /></MemoryRouter></QueryClientProvider>)
}

beforeEach(() => vi.resetAllMocks())

it("lists every active client, worst first, linking to its Web tab", async () => {
  api.overview.mockResolvedValue(overview)
  setup()
  const link = await screen.findByRole("link", { name: "Caída SL" })
  expect(link).toHaveAttribute("href", "/clients/2?tab=web")
  expect(screen.getByLabelText("Resumen")).toHaveTextContent("1 caída · 0 bloqueadas · 1 responde · 1 sin URLs")
  expect(screen.getByText(/Caída desde el/)).toBeInTheDocument()
  expect(screen.getByText("80 %")).toBeInTheDocument()
  expect(screen.getByText("Sin URLs (web: https://nueva.es)")).toBeInTheDocument()
  const names = screen.getAllByRole("link").map((a) => a.textContent)
  expect(names).toEqual(["Caída SL", "Bien SA", "Nueva"])
})

it("filters to problems and explains a disabled monitor", async () => {
  api.overview.mockResolvedValue({ ...overview, enabled: false })
  setup()
  expect(await screen.findByRole("note")).toHaveTextContent("El monitor está apagado")
  fireEvent.click(screen.getByRole("button", { name: "Sólo con problemas" }))
  expect(screen.getByRole("link", { name: "Caída SL" })).toBeInTheDocument()
  expect(screen.queryByRole("link", { name: "Bien SA" })).not.toBeInTheDocument()
  expect(screen.queryByRole("link", { name: "Nueva" })).not.toBeInTheDocument()
})
