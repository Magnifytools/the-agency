import { describe, expect, it } from "vitest"
import { detailEntries, htmlDiffReason, htmlOnlySummary, pathOf, sentenceDiff, watchHealth } from "./change-format"
import type { WebChangeItem, WebWatch } from "@/lib/types"

const htmlItem = (detail: Record<string, unknown> | null): WebChangeItem => ({
  id: "i1", kind: "html", field: "raw_html", severity: "info", rule_code: "HTML_CHANGED", rule_label: "cambió el HTML",
  before_val: null, after_val: null, detail,
})

describe("htmlOnlySummary (lección 0decies)", () => {
  it("gives the size of a layout-only change", () => {
    expect(htmlOnlySummary({ items: [htmlItem({ added: 14, removed: 9, after_lines: 3837 })] })).toEqual({
      headline: "Solo maquetación · +14/−9 líneas de 3.837",
      note: "Ni el texto visible ni el SEO se movieron.",
    })
  })
  it("never invents a zero when the size was not measured", () => {
    expect(htmlOnlySummary({ items: [htmlItem({})] })?.note).toMatch(/No se pudo medir/)
  })
  it("only summarises when the HTML item is alone", () => {
    const title: WebChangeItem = { ...htmlItem(null), id: "i2", kind: "seo", rule_code: "TITLE_CHANGED", severity: "warning" }
    expect(htmlOnlySummary({ items: [title] })).toBeNull()
    expect(htmlOnlySummary({ items: [htmlItem({ added: 1, removed: 1 }), title] })).toBeNull()
  })
})

describe("helpers", () => {
  it("shows the path, or the domain for the home", () => {
    expect(pathOf("https://www.fit.es/")).toBe("fit.es")
    expect(pathOf("https://fit.es/blog/?p=2")).toBe("/blog/?p=2")
  })
  it("explains every reason for a missing HTML diff", () => {
    expect(htmlDiffReason("sin_anterior")).toMatch(/primer cambio con HTML guardado/)
    expect(htmlDiffReason("sin_actual")).toMatch(/Vigilar HTML/)
    expect(htmlDiffReason("demasiado_grande")).toMatch(/demasiado grande/)
    expect(htmlDiffReason(undefined)).toMatch(/Vigilar HTML/)
  })
  it("formats list details, hreflang objects included", () => {
    expect(detailEntries(["/a", { lang: "en", href: "https://fit.es/en" }])).toEqual(["/a", "en → https://fit.es/en"])
    expect(detailEntries(5)).toEqual([])
  })
  it("diffs by sentence with context and collapses the rest", () => {
    const before = "Uno. Dos. Tres. Cuatro. Cinco. Seis. Siete."
    const after = "Uno. Dos. Tres. Cuatro. Cinco. Seis cambiado. Siete."
    expect(sentenceDiff(before, after)).toEqual([
      { op: "…", text: "" },
      { op: " ", text: "Cuatro." },
      { op: " ", text: "Cinco." },
      { op: "-", text: "Seis." },
      { op: "+", text: "Seis cambiado." },
      { op: " ", text: "Siete." },
    ])
  })
  it("refuses texts too long to diff in the browser", () => {
    const a = Array.from({ length: 2100 }, (_, i) => `Frase a${i}.`).join(" ")
    const b = Array.from({ length: 2100 }, (_, i) => `Frase b${i}.`).join(" ")
    expect(sentenceDiff(a, b)).toBeNull()
  })
  it("orders the watch state by what needs attention", () => {
    const base = { archived_at: null, is_active: true, checking: false, state: null } as unknown as WebWatch
    expect(watchHealth(base)).toBe("unchecked")
    expect(watchHealth({ ...base, state: { last_error: "timeout" } } as WebWatch)).toBe("error")
    expect(watchHealth({ ...base, is_active: false })).toBe("paused")
    expect(watchHealth({ ...base, archived_at: "2026-10-01T00:00:00Z" })).toBe("archived")
  })
})
