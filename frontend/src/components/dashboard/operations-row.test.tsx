import { fireEvent, render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"
import type { DashboardOperations } from "@/lib/types"
import { OperationsRow } from "./operations-row"

const operations: DashboardOperations = {
  recurring_fee: { total: 12500, clients: 7 },
  projects_at_risk: { count: 4, items: [{ id: 11, name: "Migración", reasons: ["Cierre vencido hace 12 días", "Horas del mes al 130 %"] }] },
  clients_to_act: { count: 2, items: [{ id: 5, name: "Acme", reason: "3 tareas vencidas" }] },
  digests_unsent: { count: 1, month: "septiembre de 2026", period_start: "2026-09-01", period_end: "2026-09-30", items: [{ id: 9, name: "Beta" }] },
}

function renderRow(props: Partial<Parameters<typeof OperationsRow>[0]> = {}) {
  return render(<MemoryRouter><OperationsRow operations={operations} isError={false} onRetry={vi.fn()} {...props} /></MemoryRouter>)
}

describe("OperationsRow", () => {
  it("shows each indicator linked to the screen where you act on it", () => {
    renderRow()

    const fee = screen.getByTestId("operations-fee")
    expect(fee).toHaveTextContent("7 clientes")
    expect(fee).toHaveTextContent(/12\.?500/)

    const projects = screen.getByTestId("operations-projects")
    expect(within(projects).getByText("4")).toBeInTheDocument()
    expect(within(projects).getByRole("link", { name: "Migración" })).toHaveAttribute("href", "/projects/11")
    expect(projects).toHaveTextContent("Cierre vencido hace 12 días · Horas del mes al 130 %")

    const clients = screen.getByTestId("operations-clients")
    expect(within(clients).getByRole("link", { name: "Acme" })).toHaveAttribute("href", "/clients/5")
    expect(within(clients).getByRole("link", { name: /Ver cartera/ })).toHaveAttribute("href", "/clients")

    const digests = screen.getByTestId("operations-digests")
    expect(digests).toHaveTextContent("de septiembre de 2026")
    expect(within(digests).getByRole("link", { name: "Beta" })).toHaveAttribute("href", "/digests?client_id=9&period_start=2026-09-01&period_end=2026-09-30")
    expect(within(digests).getByRole("link", { name: /Ver resúmenes/ })).toHaveAttribute("href", "/digests")
  })

  it("leaves out what the viewer cannot read instead of showing zero", () => {
    renderRow({ operations: { ...operations, recurring_fee: null, digests_unsent: null } })

    expect(screen.queryByTestId("operations-fee")).not.toBeInTheDocument()
    expect(screen.queryByTestId("operations-digests")).not.toBeInTheDocument()
    expect(screen.getByTestId("operations-projects")).toBeInTheDocument()
  })

  it("renders nothing when no source is readable", () => {
    const { container } = renderRow({ operations: { recurring_fee: null, projects_at_risk: null, clients_to_act: null, digests_unsent: null } })
    expect(container).toBeEmptyDOMElement()
  })

  it("says so when nothing needs attention", () => {
    renderRow({ operations: { ...operations, projects_at_risk: { count: 0, items: [] }, clients_to_act: { count: 0, items: [] } } })
    expect(screen.getByTestId("operations-projects")).toHaveTextContent("Ninguno con cierre vencido ni horas pasadas")
    expect(screen.getByTestId("operations-clients")).toHaveTextContent("Ningún cliente pide actuar")
  })

  it("offers a retry when the request fails", () => {
    const retry = vi.fn()
    renderRow({ operations: undefined, isError: true, onRetry: retry })
    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo cargar la operación")
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(retry).toHaveBeenCalledOnce()
  })
})
