import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"
import type { ClientWebHealth } from "@/lib/types"
import { WebExpiryCard, WebRobotsCard } from "./web-health-card"

const api = vi.hoisted(() => ({ health: vi.fn(), reviewRobots: vi.fn() }))
vi.mock("@/lib/api", () => ({ webApi: api }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const base: ClientWebHealth = {
  expiry_enabled: true,
  robots_enabled: true,
  changes_enabled: true,
  thresholds: { cert_warning_days: 14, cert_critical_days: 3, domain_warning_days: 30, domain_critical_days: 7 },
  hosts: [
    {
      host: "www.fit.es",
      checked_at: "2026-10-27T05:00:00+00:00",
      cert: { status: "ok", expires_at: "2026-11-06T10:00:00+00:00", days_left: 10, level: "warning", issuer: "Let's Encrypt", error: null },
      domain: { status: "unsupported", name: null, expires_at: null, days_left: null, level: null, error: null },
    },
    {
      host: "tienda.fit.com",
      checked_at: "2026-10-27T05:00:00+00:00",
      cert: { status: "no_https", expires_at: null, days_left: null, level: null, issuer: null, error: null },
      domain: { status: "ok", name: "fit.com", expires_at: "2026-10-30T00:00:00+00:00", days_left: 2, level: "critical", error: null },
    },
  ],
  robots: [{
    origin: "https://www.fit.es",
    checked_at: "2026-10-27T05:00:00+00:00",
    status: "ok",
    error: null,
    body: "User-agent: *\nDisallow: /",
    blocks_all: true,
    previous_body: "User-agent: *\nDisallow: /admin/",
    changed_at: "2026-10-27T05:00:00+00:00",
    reviewed_at: null,
    reviewed_by: null,
    pending_review: true,
    sitemap: { url: "https://www.fit.es/sitemap.xml", source: "default", status: "error", url_count: null, has_more: null, error: "error HTTP 404" },
  }],
}

function setup(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

beforeEach(() => {
  vi.resetAllMocks()
  api.health.mockResolvedValue(base)
})

it("shows certificate and domain expiry per host, honest about TLDs without RDAP", async () => {
  setup(<WebExpiryCard clientId={7} />)
  expect(await screen.findByText("www.fit.es")).toBeInTheDocument()
  expect(screen.getByText(/en 10 días/)).toBeInTheDocument()
  expect(screen.getByText(/en 2 días/)).toBeInTheDocument()
  expect(screen.getByText(/no publica su fecha de caducidad/)).toBeInTheDocument()
  expect(screen.getByText(/Sin HTTPS/)).toBeInTheDocument()
  expect(screen.getByText("Emisor: Let's Encrypt")).toBeInTheDocument()
})

it("says when the daily check is off", async () => {
  api.health.mockResolvedValue({ ...base, expiry_enabled: false, hosts: [] })
  setup(<WebExpiryCard clientId={7} />)
  expect(await screen.findByText(/monitor de caídas, que está apagado/)).toBeInTheDocument()
  expect(screen.getByText(/Aún no hay datos/)).toBeInTheDocument()
})

it("shows a robots.txt block, the change before/after and lets a writer review it", async () => {
  api.reviewRobots.mockResolvedValue({ ok: true })
  setup(<WebRobotsCard clientId={7} canWrite />)
  expect(await screen.findByText("Bloquea la web entera a Google")).toBeInTheDocument()
  expect(screen.getByText("Antes")).toBeInTheDocument()
  expect(screen.getByText("User-agent: * Disallow: /admin/", { normalizer: (s) => s.replace(/\s+/g, " ").trim() })).toBeInTheDocument()
  expect(screen.getByText("No responde")).toBeInTheDocument()
  expect(screen.getByText("(error HTTP 404)")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Marcar como revisado" }))
  await waitFor(() => expect(api.reviewRobots).toHaveBeenCalledWith(7, "https://www.fit.es"))
})

it("readers cannot mark a robots.txt change as reviewed", async () => {
  setup(<WebRobotsCard clientId={7} canWrite={false} />)
  await screen.findByText("Bloquea la web entera a Google")
  expect(screen.queryByRole("button", { name: "Marcar como revisado" })).not.toBeInTheDocument()
})
