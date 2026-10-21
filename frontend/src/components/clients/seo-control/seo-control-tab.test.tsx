import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { ClientSeoSummary, SeoQueryRow } from "@/lib/types"
import { SeoControlTab } from "./seo-control-tab"

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  queries: vi.fn(),
  pages: vi.fn(),
  queryHistory: vi.fn(),
  groups: vi.fn(),
  admin: false,
  canWrite: true,
}))

vi.mock("@/lib/api", () => ({
  clientSeoApi: { get: mocks.get, queries: mocks.queries, pages: mocks.pages, queryHistory: mocks.queryHistory, groups: mocks.groups },
}))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ isAdmin: mocks.admin, hasPermission: (_m: string, write = false) => (write ? mocks.canWrite : true) }),
}))
// jsdom no mide: el gráfico se sustituye por cajas vacías.
vi.mock("recharts", () => {
  const Box = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>
  const Empty = () => null
  return { ResponsiveContainer: Box, BarChart: Box, ComposedChart: Box, Bar: Empty, Line: Empty, CartesianGrid: Empty,
           XAxis: Empty, YAxis: Empty, Tooltip: Empty, Legend: Empty }
})

const client = { id: 5, name: "Acme", gsc_url: "sc-domain:acme.com" } as never

function query(q: string, overrides: Partial<SeoQueryRow> = {}): SeoQueryRow {
  return {
    query: q, is_brand: false, clicks: 10, previous_clicks: 4, clicks_delta: 6, clicks_pct: 150,
    impressions: 100, previous_impressions: 80, position: 4.2, previous_position: 6.1, position_delta: 1.9,
    state: "both", ...overrides,
  }
}

function summary(overrides: Partial<ClientSeoSummary> = {}): ClientSeoSummary {
  const side = { brand: { clicks: 40, impressions: 150 }, non_brand: { clicks: 25, impressions: 340 },
                 unclassified: { clicks: 35, impressions: 510 } }
  return {
    status: "ok", site_url: "sc-domain:acme.com", error_code: null, last_synced_at: "2026-10-19T06:00:00Z",
    window: { start: "2026-09-21", end: "2026-10-18", previous_start: "2026-08-24", previous_end: "2026-09-20", days: 28 },
    totals: {
      current: { clicks: 100, impressions: 1000, ctr: 0.1, position: 4 },
      previous: { clicks: 50, impressions: 1000, ctr: 0.05, position: 7 },
      change: { clicks_pct: 100, impressions_pct: 0, ctr_delta: 0.05, position_delta: 3 },
    },
    brand: { terms: ["Acme"], current: side, previous: side, trend: [] },
    sections: [
      { key: "/blog", label: "/blog", clicks: 40, previous_clicks: 5, clicks_pct: 700, clicks_share: 0.4,
        impressions: 400, position: 5.75, position_delta: 1, pages: 2 },
    ],
    queries: { gainers: [query("acme tienda", { is_brand: true }), query("botas", { state: "new", previous_clicks: 0 })],
               losers: [query("zapatos azules", { state: "lost", clicks: 0, clicks_delta: -10 })] },
    pages: { gainers: [], losers: [] },
    coverage: { query_clicks_share: 0.65 },
    ...overrides,
  }
}

function blocked(status: ClientSeoSummary["status"], extra: Partial<ClientSeoSummary> = {}): ClientSeoSummary {
  return { status, site_url: "sc-domain:acme.com", error_code: null, last_synced_at: null, window: null, totals: null,
           brand: null, sections: [], queries: null, pages: null, coverage: null, ...extra }
}

function show(onOpenSettings = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><SeoControlTab client={client} onOpenSettings={onOpenSettings} /></MemoryRouter>
    </QueryClientProvider>,
  )
  return onOpenSettings
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.admin = false
  mocks.canWrite = true
  mocks.get.mockResolvedValue(summary())
  mocks.queries.mockResolvedValue({ ...blocked("ok"), rows: [query("posicion sube")], total: 1 })
  mocks.pages.mockResolvedValue({ ...blocked("ok"), rows: [], total: 0 })
})

describe("SeoControlTab", () => {
  it("shows the window, KPIs, brand split and movers from the summary without extra requests", async () => {
    show()
    expect(await screen.findByText(/28 días hasta el 18 de octubre de 2026/)).toBeInTheDocument()
    expect(screen.getByText("Posición media")).toBeInTheDocument()
    expect(screen.getByText("+3,0")).toBeInTheDocument()
    expect(screen.getByText("Sin clasificar")).toBeInTheDocument()
    expect(screen.getByText("acme tienda")).toBeInTheDocument()
    expect(screen.getByText("Nueva")).toBeInTheDocument()
    expect(mocks.get).toHaveBeenCalledWith(5, 28)
    expect(mocks.queries).not.toHaveBeenCalled()
    expect(mocks.pages).not.toHaveBeenCalled()
  })

  it("asks for the 7-day window when toggled", async () => {
    show()
    await screen.findByText(/28 días hasta el/)
    await userEvent.click(screen.getByRole("button", { name: "7 d" }))
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith(5, 7))
  })

  it("requests the list with the chosen sort, brand filter and more rows", async () => {
    show()
    await screen.findByText("acme tienda")
    const group = screen.getByRole("group", { name: "Consultas: qué enseñar" })
    await userEvent.click(within(group).getByRole("button", { name: "Posición" }))
    await waitFor(() => expect(mocks.queries).toHaveBeenLastCalledWith(5, expect.objectContaining({
      days: 28, sort: "position_gain", min_impressions: 30, limit: 5,
    })))
    await userEvent.selectOptions(screen.getByLabelText("Filtrar por marca"), "non_brand")
    await waitFor(() => expect(mocks.queries).toHaveBeenLastCalledWith(5, expect.objectContaining({ brand: "non_brand" })))
    expect(await screen.findByText("posicion sube")).toBeInTheDocument()
  })

  it("filters pages by the clicked section", async () => {
    show()
    await userEvent.click(await screen.findByRole("button", { name: "/blog" }))
    await waitFor(() => expect(mocks.pages).toHaveBeenLastCalledWith(5, expect.objectContaining({ section: "/blog" })))
    expect(screen.getByText("Sección /blog")).toBeInTheDocument()
  })

  it("invites to add brand terms when there are none", async () => {
    const onOpenSettings = vi.fn()
    mocks.get.mockResolvedValue(summary({ brand: { ...summary().brand!, terms: [] } }))
    show(onOpenSettings)
    await userEvent.click(await screen.findByRole("button", { name: "Añadir términos de marca" }))
    expect(onOpenSettings).toHaveBeenCalled()
  })

  it("says it neutrally when Google has no traffic in the window", async () => {
    const empty = summary()
    empty.totals = { ...empty.totals!, current: { clicks: 0, impressions: 0, ctr: null, position: null } }
    mocks.get.mockResolvedValue(empty)
    show()
    expect(await screen.findByText("Google no registra clics ni impresiones de esta propiedad en la ventana.")).toBeInTheDocument()
    expect(screen.queryByText("Secciones")).not.toBeInTheDocument()
  })
})

describe("SeoControlTab history and URL groups", () => {
  const history = {
    status: "ok", site_url: "sc-domain:acme.com", error_code: null, last_synced_at: null,
    query: "acme tienda", is_brand: true, monthly_backfilled: true,
    months: [
      { month: "2026-08-01", clicks: 10, impressions: 100, position: 5 },
      { month: "2026-09-01", clicks: 20, impressions: 200, position: 3 },
    ],
    days: [
      { date: "2026-10-16", clicks: 1, impressions: 10, position: 4 },
      { date: "2026-10-17", clicks: 0, impressions: 0, position: null },
      { date: "2026-10-18", clicks: 2, impressions: 20, position: 2 },
    ],
  }

  it("opens a query's position history with months and the last days", async () => {
    mocks.queryHistory.mockResolvedValue(history)
    show()
    await userEvent.click(await screen.findByRole("button", { name: "acme tienda" }))
    const dialog = await screen.findByRole("dialog")
    expect(mocks.queryHistory).toHaveBeenCalledWith(5, "acme tienda")
    expect(await within(dialog).findByText("Por meses (2)")).toBeInTheDocument()
    expect(within(dialog).getByText("Últimos 3 días")).toBeInTheDocument()
    expect(within(dialog).getByText(/20 clics, posición 3,0/)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole("button", { name: "Cerrar" }))
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("says the older months are still importing", async () => {
    mocks.queryHistory.mockResolvedValue({ ...history, months: [], monthly_backfilled: false })
    show()
    await userEvent.click(await screen.findByRole("button", { name: "acme tienda" }))
    expect(await screen.findByText("Importando los meses anteriores; listo tras la próxima pasada.")).toBeInTheDocument()
  })

  it("draws the monthly position trend next to each query", async () => {
    const base = summary()
    mocks.get.mockResolvedValue(summary({
      queries: { ...base.queries!, trend_months: ["2026-08-01", "2026-09-01"],
                 gainers: [query("acme tienda", { trend: [5, 3] })] },
    }))
    show()
    expect(await screen.findByText("2 meses")).toBeInTheDocument()
    expect(screen.getByRole("img", { name: /Posición por mes: .*5,0.*3,0/ })).toBeInTheDocument()
  })

  it("switches to URL groups and filters pages by the clicked group", async () => {
    mocks.groups.mockResolvedValue({
      status: "ok", site_url: "sc-domain:acme.com", error_code: null, last_synced_at: null, window: summary().window,
      configured: 1,
      groups: [
        { key: "Blog", label: "Blog", clicks: 40, previous_clicks: 5, clicks_pct: 700, clicks_share: 0.4,
          impressions: 400, position: 5.75, position_delta: 1, pages: 2 },
        { key: "Sin grupo", label: "Sin grupo", clicks: 60, previous_clicks: 60, clicks_pct: 0, clicks_share: 0.6,
          impressions: 600, position: 3, position_delta: 0, pages: 4 },
      ],
    })
    show()
    await screen.findByText("acme tienda")
    await userEvent.click(screen.getByRole("button", { name: "Grupos" }))
    expect(await screen.findByText("Grupos de URL")).toBeInTheDocument()
    expect(mocks.groups).toHaveBeenCalledWith(5, 28)
    await userEvent.click(screen.getByRole("button", { name: "Blog" }))
    await waitFor(() => expect(mocks.pages).toHaveBeenLastCalledWith(5, expect.objectContaining({ group: "Blog" })))
    expect(screen.getByText("Grupo Blog")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Secciones" }))
    expect(await screen.findByRole("button", { name: "/blog" })).toBeInTheDocument()
    expect(screen.queryByText("Grupo Blog")).not.toBeInTheDocument()
  })

  it("invites a client writer to create groups when there are none", async () => {
    const onOpenSettings = vi.fn()
    mocks.groups.mockResolvedValue({ ...blocked("ok"), window: summary().window, groups: [], configured: 0 })
    show(onOpenSettings)
    await screen.findByText("acme tienda")
    await userEvent.click(screen.getByRole("button", { name: "Grupos" }))
    await userEvent.click(await screen.findByRole("button", { name: "Crear grupos en Configuración" }))
    expect(onOpenSettings).toHaveBeenCalled()
  })
})

describe("SeoControlTab empty states", () => {
  it("sends a client writer to Configuración when there is no property", async () => {
    const onOpenSettings = vi.fn()
    mocks.get.mockResolvedValue(blocked("no_property", { site_url: null }))
    show(onOpenSettings)
    await userEvent.click(await screen.findByRole("button", { name: "Añadir la propiedad en Configuración" }))
    expect(onOpenSettings).toHaveBeenCalled()
  })

  it("does not offer Configuración to a reader", async () => {
    mocks.canWrite = false
    mocks.get.mockResolvedValue(blocked("no_property", { site_url: null }))
    show()
    expect(await screen.findByText("Este cliente no tiene propiedad de Search Console.")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Configuración/ })).not.toBeInTheDocument()
  })

  it.each([
    ["not_connected", "Conectar en Ajustes → Search Console"],
    ["reconnect_required", "Reconectar en Ajustes → Search Console"],
  ] as const)("links an admin to Ajustes → Search Console (%s)", async (status, link) => {
    mocks.admin = true
    mocks.get.mockResolvedValue(blocked(status))
    show()
    expect(await screen.findByRole("link", { name: link })).toHaveAttribute("href", "/settings#search-console")
  })

  it("tells a member to ask an admin when the account is missing", async () => {
    mocks.get.mockResolvedValue(blocked("not_connected"))
    show()
    expect(await screen.findByText("Pide a un admin que lo revise en Ajustes → Search Console.")).toBeInTheDocument()
    expect(screen.queryByRole("link")).not.toBeInTheDocument()
  })

  it.each(["not_synced", "backfilling"] as const)("explains the import is on its way (%s)", async (status) => {
    mocks.get.mockResolvedValue(blocked(status, { last_synced_at: status === "backfilling" ? new Date().toISOString() : null }))
    show()
    expect(await screen.findByText("Importando consultas y páginas; listo tras la próxima pasada.")).toBeInTheDocument()
    expect(screen.getByText(status === "backfilling" ? /Última pasada/ : /Aún no ha corrido ninguna pasada/)).toBeInTheDocument()
  })

  it("explains an import error", async () => {
    mocks.get.mockResolvedValue(blocked("error", { error_code: "no_access" }))
    show()
    expect(await screen.findByText("La cuenta conectada no tiene acceso a esta propiedad.")).toBeInTheDocument()
  })
})
