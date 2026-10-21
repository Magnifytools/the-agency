import { describe, expect, it } from "vitest"

import { brandKey, brandTermProblem, normalizeSeoText, suggestBrandTerms } from "./seo-control"

describe("seo-control helpers", () => {
  it("normalizes like the backend", () => {
    expect(normalizeSeoText("  Peluquería  CANINA ")).toBe("peluqueria canina")
    expect(normalizeSeoText("Fit-Generation.com")).toBe("fit generation com")
    expect(brandKey("Fit Generation")).toBe(brandKey("FITGENERATION"))
  })

  it("validates terms", () => {
    expect(brandTermProblem("ab", [])).toMatch(/Entre 3 y 60/)
    expect(brandTermProblem("- -", [])).toMatch(/letras o números/)
    expect(brandTermProblem("acme", ["ACME"])).toBe("Ya está en la lista.")
    expect(brandTermProblem("nuevo", Array.from({ length: 20 }, (_, i) => `marca${i}`))).toMatch(/Como mucho 20/)
    expect(brandTermProblem("acme", [])).toBeNull()
  })

  it("suggests from the domain and the client name, without duplicates", () => {
    expect(suggestBrandTerms({ name: "Clínica Dental Sonrisa S.L.", website: "https://www.dental-sonrisa.com.es/es/", gsc_url: null }, []))
      .toEqual(["dental sonrisa", "clínica dental sonrisa"])
    expect(suggestBrandTerms({ name: "Acme", gsc_url: "sc-domain:acme.co.uk" }, [])).toEqual(["acme"])
    expect(suggestBrandTerms({ name: "Acme", gsc_url: "https://tienda.acme.com/" }, ["acme"])).toEqual([])
  })
})
