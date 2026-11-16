import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { AxiosError, AxiosHeaders } from "axios"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { BingCheckResult, BingUrlRow, ClientBingConnection } from "@/lib/types"
import { SeoBingCard } from "./seo-bing-card"

const mocks = vi.hoisted(() => ({ connection: vi.fn(), check: vi.fn(), pageQueries: vi.fn() }))

vi.mock("@/lib/api", () => ({
  clientBingApi: { connection: mocks.connection, check: mocks.check, pageQueries: mocks.pageQueries },
}))

const SITE = "https://www.acme.com/"

function connection(overrides: Partial<ClientBingConnection> = {}): ClientBingConnection {
  return { connected: true, site_url: SITE, status: "ok", last_error: null, connected_at: "2026-11-11T09:00:00Z",
           connected_by_name: "David", ...overrides }
}

function row(overrides: Partial<BingUrlRow>): BingUrlRow {
  return { url: SITE, label: null, state: "crawled", http_status: 200, last_crawled_at: "2026-11-01T00:00:00+00:00",
           discovered_at: null, days_since_crawl: 10, impressions: 40, clicks: 2, position: 6, ...overrides }
}

function result(overrides: Partial<BingCheckResult> = {}): BingCheckResult {
  return {
    site_url: SITE, checked_at: new Date().toISOString(), window: { start: "2026-10-12", end: "2026-11-08" },
    watched_total: 2, max_urls: 25,
    urls: [
      row({ label: "Home" }),
      row({ url: `${SITE}blog/`, state: "unknown", http_status: null, last_crawled_at: null, days_since_crawl: null,
            impressions: null, clicks: null, position: null }),
    ],
    ...overrides,
  }
}

function show(isAdmin = false) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <MemoryRouter>
      <QueryClientProvider client={qc}><SeoBingCard clientId={5} isAdmin={isAdmin} /></QueryClientProvider>
    </MemoryRouter>,
  )
}

describe("SeoBingCard", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.connection.mockResolvedValue(connection())
    mocks.check.mockResolvedValue(result())
  })

  it("sin conexión, un admin va a los ajustes del cliente y no se comprueba nada", async () => {
    mocks.connection.mockResolvedValue(connection({ connected: false, site_url: null, status: null }))
    show(true)
    const link = await screen.findByRole("link", { name: "Conectar en los ajustes del cliente" })
    expect(link).toHaveAttribute("href", "/clients/5?tab=ajustes&foco=bing")
    expect(screen.queryByRole("button", { name: "Comprobar en Bing" })).not.toBeInTheDocument()
    expect(mocks.check).not.toHaveBeenCalled()
  })

  it("sin conexión, quien no es admin sabe a quién pedírselo", async () => {
    mocks.connection.mockResolvedValue(connection({ connected: false, site_url: null, status: null }))
    show()
    expect(await screen.findByText(/Pide a un admin/)).toBeInTheDocument()
    expect(screen.queryByRole("link")).not.toBeInTheDocument()
  })

  it("sólo comprueba al pulsar y enseña el estado de cada URL", async () => {
    show()
    const button = await screen.findByRole("button", { name: "Comprobar en Bing" })
    expect(mocks.check).not.toHaveBeenCalled()
    await userEvent.click(button)

    const home = (await screen.findByRole("button", { name: "Ver consultas de /" })).closest("tr")!
    expect(within(home).getByText("Home")).toBeInTheDocument()
    expect(within(home).getByText("Rastreada")).toBeInTheDocument()
    expect(within(home).getByText("hace 10 días")).toBeInTheDocument()
    const blog = screen.getByText("/blog/").closest("tr")!
    expect(within(blog).getByText("Bing no la conoce")).toBeInTheDocument()
    // Sin rendimiento no se pinta un cero.
    expect(within(blog).getAllByText("—")).toHaveLength(4)
    expect(screen.getByRole("button", { name: "Volver a comprobar" })).toBeInTheDocument()
  })

  it("avisa cuando sólo mira la web o cuando hay más URLs vigiladas que las que se miran", async () => {
    mocks.check.mockResolvedValue(result({ watched_total: 0 }))
    show()
    await userEvent.click(await screen.findByRole("button", { name: "Comprobar en Bing" }))
    expect(await screen.findByRole("link", { name: "pestaña Web" })).toHaveAttribute("href", "/clients/5?tab=web")

    mocks.check.mockResolvedValue(result({ watched_total: 30 }))
    await userEvent.click(screen.getByRole("button", { name: "Volver a comprobar" }))
    expect(await screen.findByText("Se miran las 25 primeras de 30 URLs vigiladas.")).toBeInTheDocument()
  })

  it("las consultas de una URL se piden al desplegarla, una sola vez", async () => {
    mocks.pageQueries.mockResolvedValue({ url: SITE, window: null,
      queries: [{ query: "acme botas", impressions: 30, clicks: 3, position: 4.5 }] })
    show()
    await userEvent.click(await screen.findByRole("button", { name: "Comprobar en Bing" }))
    const toggle = await screen.findByRole("button", { name: "Ver consultas de /" })
    await userEvent.click(toggle)
    expect(await screen.findByText("acme botas")).toBeInTheDocument()
    expect(mocks.pageQueries).toHaveBeenCalledWith(5, SITE)

    await userEvent.click(screen.getByRole("button", { name: "Ocultar consultas de /" }))
    await userEvent.click(screen.getByRole("button", { name: "Ver consultas de /" }))
    expect(await screen.findByText("acme botas")).toBeInTheDocument()
    expect(mocks.pageQueries).toHaveBeenCalledTimes(1)
  })

  it("enseña el error de Bing y la clave caducada", async () => {
    mocks.connection.mockResolvedValue(connection({ status: "invalid" }))
    const response = { data: { detail: { code: "invalid_key", message: "Bing no acepta la clave de esta web." } },
                       status: 409, statusText: "", headers: {}, config: { headers: new AxiosHeaders() } }
    mocks.check.mockRejectedValue(new AxiosError("409", "ERR_BAD_REQUEST", undefined, undefined, response))
    show(true)
    expect(await screen.findByRole("link", { name: "Cambiarla" })).toHaveAttribute("href", "/clients/5?tab=ajustes&foco=bing")
    await userEvent.click(screen.getByRole("button", { name: "Comprobar en Bing" }))
    expect(await screen.findByText("Bing no acepta la clave de esta web.")).toBeInTheDocument()
  })
})
