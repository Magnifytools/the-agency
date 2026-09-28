import { describe, expect, it } from "vitest"
import { projectTypeLabel } from "./constants"

describe("projectTypeLabel", () => {
  it("devuelve la etiqueta de un tipo conocido", () => {
    expect(projectTypeLabel("local_seo")).toBe("SEO local")
    expect(projectTypeLabel("technical_seo")).toBe("SEO técnico")
  })

  it("devuelve el valor en bruto si el tipo no está en el mapa", () => {
    expect(projectTypeLabel("legacy_type")).toBe("legacy_type")
  })
})
