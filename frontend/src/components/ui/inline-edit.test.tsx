import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { InlineDate, InlineSelect } from "./inline-edit"

const options = [{ value: "a", label: "Uno" }, { value: "b", label: "Dos" }, { value: "c", label: "Tres" }]

describe("InlineSelect", () => {
  it("se maneja con teclado: abre en la opción elegida, flechas, Enter y Escape", async () => {
    const onChange = vi.fn()
    render(<InlineSelect label="Número" valueText="Dos" value="b" options={options} onChange={onChange}>Dos</InlineSelect>)
    const trigger = screen.getByRole("button", { name: "Número: Dos" })
    await userEvent.click(trigger)
    expect(screen.getByRole("option", { name: "Dos" })).toHaveFocus()

    await userEvent.keyboard("{Escape}")
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    expect(onChange).not.toHaveBeenCalled()

    await userEvent.click(trigger)
    await userEvent.keyboard("{ArrowDown}{Enter}")
    expect(onChange).toHaveBeenCalledWith("c")
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
  })

  it("elegir lo que ya estaba no guarda nada", async () => {
    const onChange = vi.fn()
    render(<InlineSelect label="Número" valueText="Dos" value="b" options={options} onChange={onChange}>Dos</InlineSelect>)
    await userEvent.click(screen.getByRole("button", { name: "Número: Dos" }))
    await userEvent.click(screen.getByRole("option", { name: "Dos" }))
    expect(onChange).not.toHaveBeenCalled()
  })

  it("con más de 8 opciones busca y Enter elige la primera que casa", async () => {
    const onChange = vi.fn()
    const many = ["Ana", "Bea", "Carla", "Dani", "Elena", "Fran", "Gema", "Hugo", "Inés"].map((name) => ({ value: name, label: name }))
    render(<InlineSelect label="Persona" valueText="Ana" value="Ana" options={many} onChange={onChange}>Ana</InlineSelect>)
    await userEvent.click(screen.getByRole("button", { name: "Persona: Ana" }))
    expect(screen.getByRole("searchbox", { name: "Buscar" })).toHaveFocus()
    await userEvent.keyboard("ugo{Enter}")
    expect(onChange).toHaveBeenCalledWith("Hugo")
  })

  it("sin permiso enseña el valor sin botón", () => {
    render(<InlineSelect label="Número" valueText="Dos" value="b" options={options} onChange={vi.fn()} disabled>Dos</InlineSelect>)
    expect(screen.queryByRole("button")).not.toBeInTheDocument()
    expect(screen.getByText("Dos")).toBeInTheDocument()
  })
})

describe("InlineDate", () => {
  it("acepta un día elegido en el selector y quitar la fecha", async () => {
    const onChange = vi.fn()
    render(<InlineDate label="Límite" valueText="1 oct" value="2026-10-01" today="2026-10-01" clearLabel="Sin fecha límite" onChange={onChange}>1 oct</InlineDate>)
    await userEvent.click(screen.getByRole("button", { name: "Límite: 1 oct" }))
    expect(screen.getByRole("option", { name: /Hoy/ })).toHaveAttribute("aria-selected", "true")
    // Mientras se teclea el año el navegador emite valores a medias: no cuentan.
    fireEvent.change(screen.getByLabelText("Otro día"), { target: { value: "0202-11-20" } })
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText("Otro día"), { target: { value: "2026-11-20" } })
    expect(onChange).toHaveBeenCalledWith("2026-11-20")

    await userEvent.click(screen.getByRole("button", { name: "Límite: 1 oct" }))
    await userEvent.click(screen.getByRole("option", { name: "Sin fecha límite" }))
    expect(onChange).toHaveBeenLastCalledWith(null)
  })
})
