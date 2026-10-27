import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { DigestSeoPanel } from "./digest-seo-panel"
import type { DigestSeo } from "@/lib/types"

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
  render(<DigestSeoPanel seo={seo} include canWrite onIncludeChange={onIncludeChange} />)
  return onIncludeChange
}

describe("DigestSeoPanel", () => {
  it("shows the month against the previous one and lets the writer leave it out", async () => {
    const onIncludeChange = show(ok)

    expect(screen.getByText("1.234")).toBeInTheDocument()
    expect(screen.getByText("+23,4 %")).toBeInTheDocument()
    expect(screen.getByText("▲ 0,8")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("checkbox", { name: "Incluir en el resumen" }))
    expect(onIncludeChange).toHaveBeenCalledWith(false)
  })

  it("no longer links to The Engine's frozen PDF", () => {
    show(ok)

    expect(screen.queryByRole("link")).not.toBeInTheDocument()
    expect(screen.queryByText(/The Engine/)).not.toBeInTheDocument()
  })

  it("explains why a monthly summary has no Search Console block", () => {
    show({ status: "incomplete", site_url: "sc-domain:ejemplo.com", last_data_date: "2026-09-28" })

    expect(screen.getByRole("status")).toHaveTextContent("todavía no tiene datos finales de todo el mes")
    expect(screen.getByRole("status")).toHaveTextContent("28 de septiembre de 2026")
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument()
  })

  it("shows the full year-on-year line", () => {
    show({ ...ok, year_ago: { ...ok.month, start: "2025-09-01", end: "2025-09-30" }, vs_year_ago: { clicks_pct: 75, impressions_pct: null, ctr_delta: 0.51, position_delta: -0.4 } })

    const line = screen.getByText(/Respecto a septiembre de 2025/)
    expect(line).toHaveTextContent("clics +75,0 %, CTR +0,51 p. p., posición media ▼ 0,4.")
    expect(line).not.toHaveTextContent("impresiones")
  })

  it("shows the month's snapshot: top searches and pages, opportunities and brand", () => {
    show({
      ...ok,
      detail: {
        status: "ok",
        site_url: "https://www.ejemplo.com/",
        month: { start: "2026-09-01", end: "2026-09-30" },
        previous: { start: "2026-08-01", end: "2026-08-31" },
        queries: [
          { key: "zapatillas running", clicks: 300, impressions: 9000, position: 4, clicks_pct: 50, position_delta: 1, is_new: false },
          { key: "zapatillas trail", clicks: 40, impressions: 5000, position: 9.5, clicks_pct: null, position_delta: null, is_new: true },
        ],
        pages: [{ key: "https://www.ejemplo.com/running/", label: "/running/", clicks: 320, impressions: 9500, position: 4.2, clicks_pct: 52.4, position_delta: 0.9, is_new: false }],
        opportunities: [{ key: "zapatillas trail", clicks: 40, impressions: 5000, position: 9.5 }],
        brand: { brand: 252, non_brand: 346, unclassified: 102, previous: { brand: 260, non_brand: 210, unclassified: 50 }, non_brand_pct: 64.8, brand_pct: -3.1 },
      },
    })

    expect(screen.getByText("Búsquedas que más visitas trajeron")).toBeInTheDocument()
    expect(screen.getByText("zapatillas running")).toBeInTheDocument()
    expect(screen.getByText("nueva")).toBeInTheDocument()
    expect(screen.getByText("/running/")).toHaveAttribute("title", "https://www.ejemplo.com/running/")
    expect(screen.getAllByText("Frente a agosto")).toHaveLength(2)
    expect(screen.getByText(/posición 9,5 · 5.000 impresiones/)).toBeInTheDocument()
    expect(screen.getByText("Sin detallar por Google")).toBeInTheDocument()
    expect(screen.getByText("+64,8 %")).toBeInTheDocument()
  })
})
