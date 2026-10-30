import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { LongTimerDialog } from "./long-timer-dialog"

describe("LongTimerDialog", () => {
  it("offers the corrected time and the counted one, capped at 8 h", async () => {
    const onStop = vi.fn()
    render(<LongTimerDialog seconds={31 * 3600} pending={false} onStop={onStop} onCancel={vi.fn()} />)
    expect(screen.getByText(/31 h 0 min/)).toBeInTheDocument()
    expect(screen.getByLabelText("Horas")).toHaveValue(8)
    await userEvent.clear(screen.getByLabelText("Horas"))
    await userEvent.type(screen.getByLabelText("Horas"), "2")
    await userEvent.clear(screen.getByLabelText("Minutos"))
    await userEvent.type(screen.getByLabelText("Minutos"), "30")
    await userEvent.click(screen.getByRole("button", { name: "Guardar 2 h 30 min" }))
    expect(onStop).toHaveBeenLastCalledWith(150)
    await userEvent.click(screen.getByRole("button", { name: "Guardar lo contado (8 h)" }))
    expect(onStop).toHaveBeenLastCalledWith()
  })

  it("does not accept an empty time", async () => {
    render(<LongTimerDialog seconds={5 * 3600} pending={false} onStop={vi.fn()} onCancel={vi.fn()} />)
    await userEvent.clear(screen.getByLabelText("Horas"))
    await userEvent.clear(screen.getByLabelText("Minutos"))
    expect(screen.getByRole("alert")).toHaveTextContent("Entre 1 minuto y 12 horas")
    expect(screen.getByRole("button", { name: "Guardar 0 h 0 min" })).toBeDisabled()
  })
})
