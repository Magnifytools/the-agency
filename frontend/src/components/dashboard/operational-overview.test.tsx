import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { OperationalOverview } from "./operational-overview"

const overview = {
  active_clients: 3,
  pending_tasks: 4,
  in_progress_tasks: 2,
  hours_this_month: 12.5,
  availability: { clients: true, tasks: true, timesheet: true },
  hours_scope: "mine" as const,
}

describe("OperationalOverview", () => {
  it("identifies the external active snapshot independently from the selected month", () => {
    render(<OperationalOverview overview={overview} isLoading={false} isError={false} onRetry={vi.fn()} />)
    const label = screen.getByText("Clientes externos activos")
    fireEvent.mouseEnter(label.querySelector("span")!)
    expect(screen.getByRole("tooltip")).toHaveTextContent("Foto actual")
  })

  it("labels personal hours and does not turn an unavailable source into zero", () => {
    render(<OperationalOverview overview={{ ...overview, hours_this_month: null, availability: { ...overview.availability, timesheet: false } }} isLoading={false} isError={false} onRetry={vi.fn()} />)
    expect(screen.getByText(/No tienes acceso a mis horas del mes/i)).toBeInTheDocument()
    expect(screen.queryByText("0h")).not.toBeInTheDocument()
  })

  it("hides cached data while a request has failed and allows retry", () => {
    const retry = vi.fn()
    const { rerender } = render(<OperationalOverview isLoading={false} isError onRetry={retry} />)
    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo cargar")
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(retry).toHaveBeenCalledOnce()

    rerender(<OperationalOverview overview={overview} isLoading={true} isError onRetry={retry} />)
    expect(screen.getByRole("alert")).toHaveTextContent("No se pudo cargar")
    expect(screen.queryByText("Clientes activos")).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }))
    expect(retry).toHaveBeenCalledTimes(2)
  })
})
