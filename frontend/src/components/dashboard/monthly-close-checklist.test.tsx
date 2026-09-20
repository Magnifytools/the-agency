import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"
import { HIDDEN_MODULES, setRuntimeHiddenModules } from "@/lib/hidden-modules"
import { MonthlyCloseChecklist } from "./monthly-close-checklist"

const monthlyClose = {
  reviewed_numbers: false,
  reviewed_margin: false,
  reviewed_cash_buffer: false,
  reviewed_reinvestment: false,
  reviewed_debt: false,
  reviewed_taxes: false,
  reviewed_personal: false,
  reviewed_holded: false,
  responsible_name: "David",
  notes: "Revisión mensual",
}

function renderChecklist() {
  render(
    <MemoryRouter>
      <MonthlyCloseChecklist
        monthlyClose={monthlyClose}
        onUpdate={vi.fn()}
        onExport={vi.fn()}
        isPending={false}
        lastHoldedSync={null}
      />
    </MemoryRouter>,
  )
}

afterEach(() => setRuntimeHiddenModules([...HIDDEN_MODULES]))

describe("MonthlyCloseChecklist", () => {
  it("keeps historical checks but hides links and warnings for inactive modules", () => {
    setRuntimeHiddenModules(["executive", "holded"])
    renderChecklist()

    expect(screen.getByRole("checkbox", { name: /Margen claro/ })).toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: /Holded sincronizado/ })).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: /Margen claro/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("link", { name: /Holded sincronizado/ })).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Holded sin sincronización reciente")).not.toBeInTheDocument()
    expect(screen.getByLabelText("Responsable")).toHaveValue("David")
    expect(screen.getByLabelText("Notas del cierre")).toHaveValue("Revisión mensual")
  })

  it("shows destinations and stale-sync warning when their modules are active", () => {
    setRuntimeHiddenModules([])
    renderChecklist()

    expect(screen.getByRole("link", { name: /Margen claro/ })).toHaveAttribute("href", "/executive")
    expect(screen.getByRole("link", { name: /Holded sincronizado/ })).toHaveAttribute("href", "/finance-holded")
    expect(screen.getByLabelText("Holded sin sincronización reciente")).toBeInTheDocument()
  })
})
