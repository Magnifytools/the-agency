import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import WebChangesPage from "./web-changes-page"

const changesApi = vi.hoisted(() => ({ list: vi.fn(), ack: vi.fn(), ackAll: vi.fn() }))
const uptimeApi = vi.hoisted(() => ({ overview: vi.fn() }))
vi.mock("@/lib/api", () => ({ webChangesApi: changesApi, webApi: uptimeApi }))
vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ hasPermission: () => true }) }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const empty = { changes: [], counts: { critical: 0, warning: 0, info: 0, all: 0 }, counts_pending: { critical: 0, warning: 0, info: 0, all: 0 }, total: 0, truncated: false }

function Search() {
  return <output data-testid="search">{useLocation().search}</output>
}

function setup(url: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes><Route path="/web/cambios" element={<><WebChangesPage /><Search /></>} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.resetAllMocks()
  changesApi.list.mockResolvedValue(empty)
  uptimeApi.overview.mockResolvedValue({ enabled: true, interval_seconds: 300, clients: [
    { client_id: 7, client_name: "Fit", website: null, status: "up", targets: [] },
    { client_id: 9, client_name: "Bisiesto", website: null, status: "up", targets: [] },
  ] })
})

it("the Slack link ?cliente={id} opens that client's pending changes", async () => {
  setup("/web/cambios?cliente=7")
  await waitFor(() => expect(changesApi.list).toHaveBeenCalledWith({ client_id: 7, acknowledged: false, limit: 200 }))
  expect(await screen.findByRole("option", { name: "Fit" })).toBeInTheDocument()
  expect(screen.getByLabelText("Cliente")).toHaveValue("7")
  expect(screen.getByRole("link", { name: "Ver su web" })).toHaveAttribute("href", "/clients/7?tab=web")
})

it("filters live in the URL", async () => {
  setup("/web/cambios")
  await waitFor(() => expect(changesApi.list).toHaveBeenCalledWith({ acknowledged: false, limit: 200 }))
  fireEvent.click(within(screen.getByRole("group", { name: "Filtrar por severidad" })).getByRole("button", { name: /Avisos/ }))
  await waitFor(() => expect(screen.getByTestId("search")).toHaveTextContent("?sev=warning"))
  fireEvent.change(await screen.findByLabelText("Cliente"), { target: { value: "9" } })
  await waitFor(() => expect(screen.getByTestId("search")).toHaveTextContent("?cliente=9&sev=warning"))
  await waitFor(() => expect(changesApi.list).toHaveBeenLastCalledWith({ client_id: 9, severity: "warning", acknowledged: false, limit: 200 }))
  fireEvent.click(within(screen.getByRole("group", { name: "Filtrar por estado de revisión" })).getByRole("button", { name: /Todo/ }))
  await waitFor(() => expect(screen.getByTestId("search")).toHaveTextContent("?cliente=9&sev=warning&estado=todo"))
})
