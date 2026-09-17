import { describe, expect, it } from "vitest"

import { projectCreateFromDraft } from "./project-draft"

describe("projectCreateFromDraft", () => {
  it("keeps the monthly fee distinct from the total budget", () => {
    const payload = projectCreateFromDraft({
      name: "SEO mensual",
      budget_amount: 5400,
      monthly_fee: 450,
      pricing_model: "monthly",
    }, 17)

    expect(payload).toMatchObject({
      name: "SEO mensual",
      client_id: 17,
      budget_amount: 5400,
      monthly_fee: 450,
      pricing_model: "monthly",
    })
  })

  it("preserves a reviewed edit without deriving missing prices", () => {
    const edited = projectCreateFromDraft({ name: "Proyecto", monthly_fee: 475 }, 3)
    const missing = projectCreateFromDraft({ name: "Sin precio" }, 3)

    expect(edited.monthly_fee).toBe(475)
    expect(edited.budget_amount).toBeUndefined()
    expect(missing.monthly_fee).toBeUndefined()
    expect(missing.budget_amount).toBeUndefined()
  })

  it("preserves only the explicitly reviewed owner", () => {
    expect(projectCreateFromDraft({ name: "Con responsable", owner_id: 8 }, 3).owner_id).toBe(8)
    expect(projectCreateFromDraft({ name: "Sin responsable", owner_id: null }, 3).owner_id).toBeUndefined()
    expect(projectCreateFromDraft({ name: "Sin contexto" }, 3).owner_id).toBeUndefined()
  })
})
