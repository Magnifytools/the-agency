import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { Dialog, DialogTitle } from "./dialog"

describe("dialog keyboard navigation with optional fields", () => {
  it("wraps focus to a closed disclosure summary, not its hidden controls", async () => {
    render(<Dialog open onOpenChange={vi.fn()}><DialogTitle>Alta</DialogTitle><input aria-label="Nombre" /><details><summary>Opciones</summary><input aria-label="Oculto" /><button>Acción oculta</button></details></Dialog>)
    const close = screen.getByRole("button", {name: "Cerrar"})
    close.focus()
    await userEvent.tab({shift: true})
    expect(screen.getByText("Opciones")).toHaveFocus()
    await userEvent.tab()
    expect(close).toHaveFocus()
    await userEvent.click(screen.getByText("Opciones"))
    close.focus()
    await userEvent.tab({shift: true})
    expect(screen.getByRole("button", {name: "Acción oculta"})).toHaveFocus()
  })
})
