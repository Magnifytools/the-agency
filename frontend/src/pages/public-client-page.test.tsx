import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
import { AxiosError } from "axios"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import PublicClientPage from "./public-client-page"

const api = vi.hoisted(() => ({ status: vi.fn(), create: vi.fn(), revoke: vi.fn(), publicView: vi.fn() }))
vi.mock("@/lib/client-share-link-api", () => ({ clientShareLinkApi: api }))

const view = {
  client_name: "Fit Generation",
  traffic: {
    complete_through: "2026-09-30",
    months: [
      { month: "2026-08", clicks: 1200, impressions: 40000, position: 12.3 },
      { month: "2026-09", clicks: 1500, impressions: 45000, position: 11.8 },
    ],
  },
  digests: [
    { period_start: "2026-09-01", period_end: "2026-09-30", period_label: "Septiembre 2026", delivered_at: "2026-10-02T09:00:00+00:00", html: "<p>SEPTIEMBRE</p>" },
    { period_start: "2026-08-01", period_end: "2026-08-31", period_label: "Agosto 2026", delivered_at: "2026-09-03T09:00:00+00:00", html: "<p>AGOSTO</p>" },
  ],
}

function setup(token = "abc") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/c/${token}`]}>
        <Routes><Route path="/c/:token" element={<PublicClientPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => vi.resetAllMocks())

it("shows the client, its monthly traffic and the latest delivered digest in a locked-down frame", async () => {
  api.publicView.mockResolvedValue(view)
  setup("tok_1")
  expect(await screen.findByRole("heading", { level: 1, name: "Fit Generation" })).toBeInTheDocument()
  expect(api.publicView).toHaveBeenCalledWith("tok_1")
  const rows = screen.getAllByRole("row")
  expect(rows[1]).toHaveTextContent(/sep 26.*1500.*45\.000.*11,8/)
  const frame = screen.getByTitle("Resumen Septiembre 2026")
  expect(frame).toHaveAttribute("srcdoc", "<p>SEPTIEMBRE</p>")
  const sandbox = frame.getAttribute("sandbox") ?? ""
  expect(sandbox).not.toMatch(/allow-scripts|allow-same-origin/)
  fireEvent.click(screen.getByRole("button", { name: /Agosto 2026/ }))
  expect(screen.getByTitle("Resumen Agosto 2026")).toHaveAttribute("srcdoc", "<p>AGOSTO</p>")
})

it("tells the client when there is nothing yet", async () => {
  api.publicView.mockResolvedValue({ client_name: "Nuevo", traffic: null, digests: [] })
  setup()
  expect(await screen.findByText("Todavía no hay datos de Search Console para mostrar.")).toBeInTheDocument()
  expect(screen.getByText("Aún no hay resúmenes entregados.")).toBeInTheDocument()
})

it("an unknown or revoked link shows a neutral message", async () => {
  const notFound = new AxiosError("not found")
  notFound.response = { status: 404, data: {} } as AxiosError["response"]
  api.publicView.mockRejectedValue(notFound)
  setup()
  expect(await screen.findByRole("alert")).toHaveTextContent("Este enlace no está disponible")
  expect(screen.queryByText("Fit Generation")).not.toBeInTheDocument()
})
