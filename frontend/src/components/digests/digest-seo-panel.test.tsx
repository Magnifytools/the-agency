import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { DigestSeoPanel } from "./digest-seo-panel"
import type { DigestSeo } from "@/lib/types"

const mocks = vi.hoisted(() => ({ getClient: vi.fn(), getConfig: vi.fn() }))

vi.mock("@/context/auth-context", () => ({ useAuth: () => ({ hasPermission: () => true }) }))
vi.mock("@/lib/api", () => ({
  clientsApi: { get: mocks.getClient },
  engineApi: { getConfig: mocks.getConfig },
}))

const ok: DigestSeo = {
  status: "ok",
  site_url: "sc-domain:ejemplo.com",
  month: { start: "2026-09-01", end: "2026-09-30", days: 30, clicks: 1234, impressions: 56789, ctr: 2.17, position: 12.3 },
  previous: { start: "2026-08-01", end: "2026-08-31", days: 31, clicks: 1000, impressions: 50000, ctr: 2, position: 13.1 },
  year_ago: null,
  vs_previous: { clicks_pct: 23.4, impressions_pct: 13.6, ctr_delta: 0.17, position_delta: 0.8 },
  vs_year_ago: null,
}

function show(seo: DigestSeo, onIncludeChange = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <DigestSeoPanel seo={seo} clientId={5} include canWrite onIncludeChange={onIncludeChange} />
    </QueryClientProvider>,
  )
  return onIncludeChange
}

describe("DigestSeoPanel", () => {
  beforeEach(() => {
    mocks.getClient.mockResolvedValue({ id: 5, engine_project_id: 81 })
    mocks.getConfig.mockResolvedValue({ engine_frontend_url: "https://engine.example" })
  })

  it("shows the month against the previous one and lets the writer leave it out", async () => {
    const onIncludeChange = show(ok)

    expect(screen.getByText("1.234")).toBeInTheDocument()
    expect(screen.getByText("+23,4 %")).toBeInTheDocument()
    expect(screen.getByText("▲ 0,8")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("checkbox", { name: "Incluir en el resumen" }))
    expect(onIncludeChange).toHaveBeenCalledWith(false)
  })

  it("links to the client's reports in The Engine for the PDF", async () => {
    show(ok)

    const link = await screen.findByRole("link", { name: /informe SEO en PDF/ })
    expect(link).toHaveAttribute("href", "https://engine.example/p/81/reports")
  })

  it("explains why a monthly summary has no Search Console block", () => {
    show({ status: "incomplete", site_url: "sc-domain:ejemplo.com", last_data_date: "2026-09-28" })

    expect(screen.getByRole("status")).toHaveTextContent("todavía no tiene datos finales de todo el mes")
    expect(screen.getByRole("status")).toHaveTextContent("28 de septiembre de 2026")
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument()
  })
})
