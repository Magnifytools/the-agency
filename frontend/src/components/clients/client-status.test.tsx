import { render, screen } from "@testing-library/react"
import { expect, it } from "vitest"

import { DigestCell } from "./client-status"

it("pinta una línea por cadencia, el informe mensual primero", () => {
  render(<DigestCell digests={[
    { cadence: "monthly", last_sent_period_end: "2026-09-30", expected_period_end: "2026-09-30", state: "ok" },
    { cadence: "weekly", last_sent_period_end: null, expected_period_end: "2026-10-18", state: "late" },
  ]} />)
  const lines = screen.getAllByText(/Informe mensual|Seguimiento semanal/).map(node => node.textContent)
  expect(lines).toEqual(["Informe mensual · Al día", "Seguimiento semanal · Atrasado"])
  expect(screen.getByText(/Último entregado hasta 30 sept/)).toBeInTheDocument()
  expect(screen.getByText("Nunca entregado")).toBeInTheDocument()
})

it("sin cadencias encendidas dice que no hay política", () => {
  render(<DigestCell digests={[]} />)
  expect(screen.getByText("Sin política")).toBeInTheDocument()
})
