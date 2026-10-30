import { useState } from "react"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { BrandTermsEditor } from "./brand-terms-editor"

function Harness({ initial = [] as string[], onChange = vi.fn(), disabled = false }) {
  const [terms, setTerms] = useState(initial)
  return (
    <BrandTermsEditor
      value={terms}
      onChange={(next) => { setTerms(next); onChange(next) }}
      disabled={disabled}
      client={{ name: "Fit Generation S.L.", website: "https://www.fit-generation.com", gsc_url: "sc-domain:fitgeneration.es" }}
    />
  )
}

describe("BrandTermsEditor", () => {
  it("adds chips with Enter, rejects short or duplicated terms and removes chips", async () => {
    const onChange = vi.fn()
    render(<Harness initial={["Acme"]} onChange={onChange} />)
    const input = screen.getByLabelText("Términos de marca")

    await userEvent.type(input, "ab{Enter}")
    expect(screen.getByRole("alert")).toHaveTextContent("Entre 3 y 60 caracteres.")
    await userEvent.clear(input)
    await userEvent.type(input, "ÁCME{Enter}")
    expect(screen.getByRole("alert")).toHaveTextContent("Ya está en la lista.")
    await userEvent.clear(input)
    await userEvent.type(input, "  acme   shop {Enter}")
    expect(onChange).toHaveBeenLastCalledWith(["Acme", "acme shop"])

    await userEvent.click(screen.getByRole("button", { name: "Quitar Acme" }))
    expect(onChange).toHaveBeenLastCalledWith(["acme shop"])
  })

  it("only proposes suggestions until one is accepted", async () => {
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)
    await userEvent.click(screen.getByRole("button", { name: /Sugerir/ }))

    // Dominio de Search Console, dominio de la web (otro guion, mismo término) y nombre sin "S.L.".
    expect(screen.getByRole("button", { name: "Añadir fitgeneration" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Añadir fit generation" })).not.toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole("button", { name: "Añadir fitgeneration" }))
    expect(onChange).toHaveBeenLastCalledWith(["fitgeneration"])
    expect(screen.queryByRole("button", { name: "Añadir fitgeneration" })).not.toBeInTheDocument()
  })

  it("is read-only for a client reader", () => {
    render(<Harness initial={["Acme"]} disabled />)
    expect(screen.getByText("Acme")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Quitar Acme" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Sugerir/ })).not.toBeInTheDocument()
  })
})
