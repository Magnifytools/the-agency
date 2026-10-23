import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"

import type { ClientLeads as Leads } from "@/lib/types"
import { ClientLeads } from "./client-leads"

const mocks = vi.hoisted(() => ({ leads: vi.fn() }))
vi.mock("@/lib/api", () => ({ clientSeoApi: { leads: mocks.leads } }))

function show() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><ClientLeads clientId={5} /></QueryClientProvider>)
}

const ok: Leads = {
  status: "ok", events: ["generate_lead_*"], days: 28, start: "2026-09-21", end: "2026-10-18",
  comparable: true,
  total: { leads: 1234, previous: 1000, change_pct: 23.4 },
  landings: [
    { landing_page: "go.acme.com/cpe/", leads: 800, previous: 400, change_pct: 100 },
    { landing_page: "acme.com/blog/", leads: 3, previous: 0, change_pct: null },
  ],
  landing_count: 2,
  channels: [
    { channel: "Paid Search", leads: 800, previous: 500, change_pct: 60 },
    { channel: "Referral", leads: 0, previous: 3, change_pct: -100 },
  ],
}

beforeEach(() => vi.clearAllMocks())

it("enseña el total, las landings con más leads y los canales", async () => {
  mocks.leads.mockResolvedValue(ok)
  show()
  expect(await screen.findByText("Leads por landing (GA4, 28 días)")).toBeInTheDocument()
  expect(screen.getByText(/1\.234 leads/)).toHaveTextContent("1.234 leads (+23,4 %)")
  const list = screen.getByRole("list", { name: "Landings con más leads" })
  expect(list).toHaveTextContent("go.acme.com/cpe/800 (+100,0 %)")
  expect(list).toHaveTextContent("acme.com/blog/3 (nuevo)")
  // Sólo los canales con leads en la ventana.
  expect(screen.getByText("Paid Search: 800")).toBeInTheDocument()
  expect(screen.queryByText(/Referral/)).not.toBeInTheDocument()
  expect(screen.getByText(/Eventos: generate_lead_\*/)).toBeInTheDocument()
})

it("avisa si no hay con qué comparar o aún no se ha importado", async () => {
  mocks.leads.mockResolvedValue({ ...ok, comparable: false, total: { leads: 2, previous: null, change_pct: null } })
  const { unmount } = show()
  expect(await screen.findByText(/sin datos anteriores para comparar/)).toBeInTheDocument()
  unmount()

  mocks.leads.mockResolvedValue({ status: "not_synced", events: ["generate_lead"], days: 28, error_code: null })
  show()
  expect(await screen.findByText("Se importarán en la próxima pasada diaria.")).toBeInTheDocument()
})

it("no pinta nada sin propiedad de GA4", async () => {
  mocks.leads.mockResolvedValue({ status: "no_property", events: ["generate_lead"], days: 28 })
  const { container } = show()
  await vi.waitFor(() => expect(mocks.leads).toHaveBeenCalledWith(5))
  expect(container).toBeEmptyDOMElement()
})
