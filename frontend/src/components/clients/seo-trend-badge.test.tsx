import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { SeoTrendBadge } from "./seo-trend-badge"
import { formatChangePct } from "./seo-trend"

describe("SeoTrendBadge", () => {
  it("shows the arrow and the change with Spanish formatting", () => {
    expect(formatChangePct(-42.5)).toBe("▼ 42,5 %")
    expect(formatChangePct(12)).toBe("▲ 12,0 %")
    expect(formatChangePct(0)).toBe("= 0,0 %")
  })

  it("paints an alert drop red and a rise green", () => {
    const { rerender } = render(<SeoTrendBadge linked trend="drop_alert" changePct={-30} />)
    expect(screen.getByText("▼ 30,0 %").className).toContain("bg-red-950")
    rerender(<SeoTrendBadge linked trend="up" changePct={8} />)
    expect(screen.getByText("▲ 8,0 %").className).toContain("bg-green-950")
  })

  it("never invents a trend without Engine or without a previous period", () => {
    const { rerender } = render(<SeoTrendBadge linked={false} trend={null} changePct={null} />)
    expect(screen.getByText("Sin Engine")).toBeTruthy()
    rerender(<SeoTrendBadge linked trend={null} changePct={null} />)
    expect(screen.getByText("Sin periodo anterior")).toBeTruthy()
  })
})
