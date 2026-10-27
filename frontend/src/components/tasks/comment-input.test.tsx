import { useState } from "react"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import { CommentInput } from "./comment-input"

const people = [
  { id: 1, name: "David", fullName: "David Carrasco" },
  { id: 2, name: "Nacho", fullName: "Ignacio Nacho" },
]

function Harness({ onSubmit, onFormSubmit = vi.fn() }: { onSubmit: (text: string, ids: number[]) => void; onFormSubmit?: () => void }) {
  const [value, setValue] = useState("")
  return (
    <form onSubmit={(event) => { event.preventDefault(); onFormSubmit() }}>
      <CommentInput value={value} onChange={setValue} candidates={people} onSubmit={onSubmit} />
    </form>
  )
}

describe("CommentInput", () => {
  it("menciona con el teclado y manda los ids al publicar con Enter", async () => {
    const onSubmit = vi.fn()
    const onFormSubmit = vi.fn()
    render(<Harness onSubmit={onSubmit} onFormSubmit={onFormSubmit} />)
    const input = screen.getByRole("combobox", { name: "Nuevo comentario" })
    await userEvent.type(input, "Mira @")
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual(["@DavidDavid Carrasco", "@NachoIgnacio Nacho"])
    await userEvent.keyboard("{ArrowDown}{Enter}")
    expect(input).toHaveValue("Mira @Nacho ")
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
    await userEvent.type(input, "esto{Enter}")
    expect(onSubmit).toHaveBeenCalledWith("Mira @Nacho esto", [2])
    // Enter publica el comentario, no guarda la tarea.
    expect(onFormSubmit).not.toHaveBeenCalled()
  })

  it("filtra por lo escrito y Escape cierra la lista sin borrar nada", async () => {
    render(<Harness onSubmit={vi.fn()} />)
    const input = screen.getByRole("combobox", { name: "Nuevo comentario" })
    await userEvent.type(input, "@ign")
    expect(screen.getAllByRole("option")).toHaveLength(1)
    await userEvent.keyboard("{Escape}")
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
    expect(input).toHaveValue("@ign")
  })

  it("si se borra la mención, no se avisa a esa persona", async () => {
    const onSubmit = vi.fn()
    render(<Harness onSubmit={onSubmit} />)
    const input = screen.getByRole("combobox", { name: "Nuevo comentario" })
    await userEvent.type(input, "@Da")
    await userEvent.click(screen.getByRole("option", { name: /David/ }))
    await userEvent.clear(input)
    await userEvent.type(input, "Sin menciones")
    await userEvent.click(screen.getByRole("button", { name: "Comentar" }))
    expect(onSubmit).toHaveBeenCalledWith("Sin menciones", [])
  })
})
